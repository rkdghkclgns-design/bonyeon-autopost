"""네이버 로그인 세션 점검 — 글쓰기 화면이 열리는지만 확인 (글 입력·저장·발행하지 않음).

실행 (GitHub Actions '네이버 로그인 점검' 또는 내 PC)
  python scripts/naver_session_check.py            # 결과 출력 + (GH_SECRETS_TOKEN 있으면) 갱신된 세션 저장
  python scripts/naver_session_check.py --no-save  # 저장 없이 확인만

GitHub(해외 서버)에서 사용해도 네이버 로그인이 끊기지 않는지 확인하는 용도.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autopost.github_secrets import update_github_secret  # noqa: E402
from autopost.naver_publisher import (  # noqa: E402
    WRITE_URL,
    NaverSelectors,
    decode_storage_state,
    encode_storage_state,
)
from autopost.token_expiry import naver_expiry  # noqa: E402

WAIT_MS = 8000


def check(storage_state_b64: str, blog_id: str, save: bool) -> tuple[bool, str]:
    from playwright.sync_api import sync_playwright

    state = decode_storage_state(storage_state_b64)
    sel = NaverSelectors()
    write_url = WRITE_URL.format(blog_id=blog_id)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(storage_state=state, locale="ko-KR", viewport={"width": 1400, "height": 900})
        page = context.new_page()
        page.goto(write_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(WAIT_MS)
        on_login_page = "nidlogin" in page.url or "nid.naver.com" in page.url
        editor_ok = any(frame.locator(sel.title).count() for frame in page.frames)
        refreshed = ""
        if editor_ok and save:
            refreshed = encode_storage_state(context.storage_state(), extra_hosts=(urlparse(write_url).hostname or "",))
        browser.close()
    ok = editor_ok and not on_login_page
    if not ok:
        return False, "❌ 글쓰기 화면 대신 로그인 화면으로 이동 — 세션이 끊겼습니다"
    note = "✅ 로그인 유지 — 글쓰기 화면 열림"
    if refreshed:
        expiry = naver_expiry(refreshed).expires
        saved = update_github_secret("NAVER_STORAGE_STATE_B64", refreshed)
        note += f" · 만료일 {expiry or '확인 불가'} · 세션 저장 {'완료' if saved else '안 함'}"
    return True, note


def main() -> int:
    parser = argparse.ArgumentParser(description="네이버 로그인 세션 점검")
    parser.add_argument("--no-save", action="store_true", help="갱신된 세션을 저장하지 않음")
    args = parser.parse_args()
    if not os.environ.get("NAVER_STORAGE_STATE_B64"):
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
    encoded = os.environ.get("NAVER_STORAGE_STATE_B64", "")
    blog_id = os.environ.get("NAVER_BLOG_ID", "")
    if not (encoded and blog_id):
        print("❌ NAVER_STORAGE_STATE_B64 / NAVER_BLOG_ID 가 없습니다")
        return 1
    ok, note = check(encoded, blog_id, save=not args.no_save)
    print(note)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"## 네이버 로그인 점검\n{note}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
