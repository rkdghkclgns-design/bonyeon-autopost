"""구글 블로그에 올라간 글을 네이버 블로그에 똑같이 올린다 (제목·본문·사진 순서·태그 동일).

실행
  python scripts/crosspost_naver.py https://bonyeon-clean.blogspot.com/2026/09/blog-post.html
  python scripts/crosspost_naver.py <구글 글 주소> --dry-run      # 네이버에 올리지 않고 입력 순서만 출력
  python scripts/crosspost_naver.py <구글 글 주소> --mode draft   # 임시저장
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autopost.naver_crosspost import crosspost, fetch_post_by_url  # noqa: E402
from autopost.cli import _load_dotenv  # noqa: E402
from autopost.config import load_config  # noqa: E402
from autopost.google_auth import build_blogger_service, build_credentials  # noqa: E402
from autopost.local_secrets import save_everywhere  # noqa: E402
from autopost.naver_publisher import NaverPublisher  # noqa: E402


def download(url: str, dest: Path) -> Path:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    dest.write_bytes(response.content)
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description="구글 블로그 글을 네이버에 똑같이 올리기")
    parser.add_argument("url", help="구글 블로그 글 주소")
    parser.add_argument("--mode", choices=("publish", "draft"), default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    _load_dotenv()
    cfg = load_config(dict(os.environ))
    post = fetch_post_by_url(build_blogger_service(build_credentials(cfg.google)), cfg.blogger_blog_id, args.url)
    workdir = Path(tempfile.mkdtemp(prefix="crosspost_"))
    print(f"제목: {post.title}")
    if args.dry_run:
        from autopost.blogger_import import to_blocks

        blocks, hashtags = to_blocks(post.html, workdir, download)
        print(f"블록 {len(blocks)}개 (사진 {sum(b.kind == 'image' for b in blocks)}장) · 태그 {len(hashtags)}개")
        for block in blocks:
            print(f"  [{block.kind}] {block.image.name if block.image else block.text[:40]!r}")
        return 0

    publisher = NaverPublisher(
        cfg.naver_blog_id, cfg.naver_storage_state_b64, args.mode or cfg.naver_publish_mode, cfg.output_dir,
        on_session_updated=lambda value: not save_everywhere({"NAVER_STORAGE_STATE_B64": value}, Path(".env"), True),
    )
    result = crosspost(post, workdir, download, publisher)
    print(("✅ " if result.ok else "❌ ") + result.message, result.url)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
