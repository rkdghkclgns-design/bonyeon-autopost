"""[내 PC 예약 작업] 오늘 구글 블로그 글을 네이버에 똑같이 올리고 슬랙에 보고.

Windows 작업 스케줄러가 매일 10:30 · 11:30 에 실행 (scripts/install_naver_task.ps1 로 등록).
이미 올린 글은 output/naver_crossposted.json 에 기록되어 두 번 올리지 않는다.

  python scripts/naver_daily.py            # 실행
  python scripts/naver_daily.py --dry-run  # 네이버에 올리지 않고 오늘 올릴 글만 확인
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # 작업 스케줄러에서 실행될 때도 .env · output 경로가 맞도록

from autopost.cli import _load_dotenv  # noqa: E402
from autopost.config import load_config  # noqa: E402
from autopost.constants import NAVER_DISABLED_REASON, NAVER_PUBLISHING_ENABLED  # noqa: E402
from autopost.google_auth import build_blogger_service, build_credentials  # noqa: E402
from autopost.local_secrets import save_everywhere  # noqa: E402
from autopost.naver_crosspost import PostedLog, run_daily, todays_posts  # noqa: E402
from autopost.naver_publisher import NaverPublisher  # noqa: E402
from autopost.token_expiry import KST  # noqa: E402

LOG_PATH = ROOT / "output" / "naver_daily.log"


def download(url: str, dest: Path) -> Path:
    import requests

    response = requests.get(url, timeout=60)
    response.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(response.content)
    return dest


def slack_notifier(cfg):
    token = cfg.slack_bot_token
    channel = os.environ.get("SLACK_CHANNEL_PUBLISH") or cfg.slack_channel_id

    def notify(text: str, image: Path | None) -> None:
        if not (token and channel):
            logging.warning("슬랙 설정이 없어 보고하지 못했습니다: %s", text.splitlines()[0])
            return
        from slack_sdk import WebClient

        client = WebClient(token=token)
        try:
            client.chat_postMessage(channel=channel, text=text, unfurl_links=False)
            if image is not None and image.is_file():
                client.files_upload_v2(channel=channel, file=str(image), title="네이버 화면",
                                       initial_comment="🖥️ 네이버 발행이 멈춘 화면")
        except Exception:
            logging.exception("슬랙 보고 실패")

    return notify


def main() -> int:
    parser = argparse.ArgumentParser(description="오늘 구글 글을 네이버에 똑같이 올리기 (PC 예약 작업)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run and not NAVER_PUBLISHING_ENABLED:
        print(NAVER_DISABLED_REASON)
        return 0
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()])

    _load_dotenv()
    cfg = load_config(dict(os.environ))
    if not (cfg.google and cfg.blogger_blog_id):
        logging.error("구글 블로그 설정이 없습니다 (.env 확인)")
        return 1
    blogger = build_blogger_service(build_credentials(cfg.google))
    now = datetime.now(KST)
    posted = PostedLog(cfg.output_dir / "naver_crossposted.json")

    if args.dry_run:
        for post in todays_posts(blogger, cfg.blogger_blog_id, now.date()):
            print(("이미 올림 " if posted.done(post.id) else "올릴 글  ") + f"| {post.title} | {post.url}")
        return 0

    started = time.time()
    publisher = NaverPublisher(
        cfg.naver_blog_id, cfg.naver_storage_state_b64, cfg.naver_publish_mode, cfg.output_dir,
        # 갱신된 로그인 정보는 .env 와 (만료 알림용) GitHub 시크릿에 저장 — GitHub 는 네이버에 접속하지 않는다
        on_session_updated=lambda value: not save_everywhere({"NAVER_STORAGE_STATE_B64": value}, Path(".env"), True),
    )

    def latest_screenshot() -> Path | None:
        shots = [p for p in cfg.output_dir.glob("naver_*.png") if p.stat().st_mtime >= started]
        return max(shots, key=lambda p: p.stat().st_mtime) if shots else None

    failures = run_daily(
        blogger, cfg.blogger_blog_id, publisher, posted, download,
        Path(tempfile.mkdtemp(prefix="naver_daily_")), slack_notifier(cfg), now, latest_screenshot,
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
