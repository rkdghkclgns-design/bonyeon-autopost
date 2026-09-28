"""네이버 로그인 세션 저장 (내 PC에서 1회 실행).

실행
  python -m playwright install chromium     # 최초 1회
  python scripts/export_naver_cookies.py

1. 크롬 창이 열리면 네이버에 '직접' 로그인하세요 ('로그인 상태 유지' 체크 권장).
   (보안문자·2단계 인증도 직접 처리합니다. 이 스크립트는 비밀번호를 다루지 않습니다)
2. 로그인이 끝나면 터미널로 돌아와 Enter.
3. 생성된 naver_state.b64 파일 내용 전체를 GitHub 시크릿 NAVER_STORAGE_STATE_B64 에 붙여넣고,
   파일은 삭제하세요. (이 파일이 있으면 누구나 내 네이버 계정으로 로그인할 수 있습니다)

주의: 네이버 '해외 로그인 차단'이 켜져 있으면 GitHub Actions(해외 서버)에서 세션이 막힐 수 있습니다.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

LOGIN_URL = "https://nid.naver.com/nidlogin.login"
REQUIRED_COOKIES = {"NID_AUT", "NID_SES"}
OUTPUT = Path("naver_state.b64")


def main() -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(locale="ko-KR")
        page = context.new_page()
        page.goto(LOGIN_URL)
        input("\n브라우저에서 네이버 로그인을 마친 뒤 이 창에서 Enter 를 누르세요... ")
        state = context.storage_state()
        browser.close()

    names = {cookie["name"] for cookie in state.get("cookies", [])}
    missing = REQUIRED_COOKIES - names
    if missing:
        print(f"❌ 로그인 쿠키({', '.join(sorted(missing))})가 없습니다. 로그인이 완료되었는지 확인 후 다시 실행하세요.")
        return 1

    OUTPUT.write_text(base64.b64encode(json.dumps(state).encode("utf-8")).decode("ascii"), encoding="ascii")
    print(f"\n✅ 저장 완료: {OUTPUT.resolve()}")
    print("   → 파일 내용 전체를 GitHub 시크릿 NAVER_STORAGE_STATE_B64 에 등록한 뒤 파일을 삭제하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
