"""틱톡 refresh token 1회 발급 (내 PC에서 실행).

사전 준비 (README '틱톡' 항목 참고)
  1. https://developers.tiktok.com 에서 앱 생성 → Login Kit + Content Posting API 추가
  2. 스코프: user.info.basic, video.publish, video.upload
  3. Login Kit 의 Redirect URI 에 --redirect-uri 값(기본: 본연클린 구글 블로그 주소)을 등록

실행
  python scripts/get_tiktok_token.py

1. Client Key / Client Secret 을 묻는 작은 창에 붙여넣기 (.env 에 이미 있으면 묻지 않음)
2. 평소 쓰는 크롬에서 틱톡 '허용' → 이동한 페이지 주소를 작은 창에 붙여넣기
   (--playwright: 새 창을 띄워 직접 로그인하면 주소를 자동 감지)
3. 발급된 값을 .env 와 GitHub 시크릿(gh CLI)에 자동 저장 — 화면에는 값을 출력하지 않음
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import parse_qs, urlencode, urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autopost.envfile import update_env_file  # noqa: E402
from autopost.local_secrets import save_everywhere  # noqa: E402
from autopost.setup_browser import launch_visible_browser, tk_prompt  # noqa: E402
from autopost.token_expiry import expiry_from_seconds  # noqa: E402

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
SCOPES = "user.info.basic,video.publish,video.upload"
DEFAULT_REDIRECT_URI = "https://bonyeon-clean.blogspot.com/"

Prompt = Callable[[str, str, bool], str]


def build_authorize_url(client_key: str, redirect_uri: str, state: str) -> str:
    query = urlencode({
        "client_key": client_key,
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
    })
    return f"{AUTHORIZE_URL}?{query}"


def extract_code(redirected_url: str, expected_state: str) -> str:
    params = parse_qs(urlparse(redirected_url.strip()).query)
    if params.get("error"):
        raise ValueError(f"틱톡 인증 거부: {params.get('error_description', params['error'])[0]}")
    if params.get("state", [""])[0] != expected_state:
        raise ValueError("state 값이 일치하지 않습니다. 처음부터 다시 진행하세요.")
    code = params.get("code", [""])[0]
    if not code:
        raise ValueError("URL 에 code 값이 없습니다. 주소창의 전체 URL 을 붙여넣었는지 확인하세요.")
    return code


def is_redirect(url: str, redirect_uri: str) -> bool:
    """틱톡 인증 후 우리 Redirect URI 로 돌아왔는지 (code 또는 error 포함)."""
    parsed, target = urlparse(url), urlparse(redirect_uri)
    same_place = (parsed.scheme, parsed.netloc, parsed.path.rstrip("/")) == (
        target.scheme, target.netloc, target.path.rstrip("/"))
    query = parse_qs(parsed.query)
    return same_place and ("code" in query or "error" in query)


def resolve_credentials(existing: Mapping[str, str], prompt: Prompt = tk_prompt) -> tuple[str, str]:
    """.env/환경변수에 있으면 그 값을, 없으면 입력 창으로 묻는다."""
    key = existing.get("TIKTOK_CLIENT_KEY", "").strip() or prompt(
        "틱톡 설정 (1/2)", "틱톡 개발자 앱의 Client Key 를 붙여넣으세요", False).strip()
    secret = existing.get("TIKTOK_CLIENT_SECRET", "").strip() or prompt(
        "틱톡 설정 (2/2)", "틱톡 개발자 앱의 Client Secret 을 붙여넣으세요 (화면에 * 로 표시)", True).strip()
    if not key or not secret:
        raise ValueError("Client Key / Client Secret 이 입력되지 않았습니다.")
    return key, secret


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    return values


def wait_for_redirect(context, redirect_uri: str, timeout_s: float, poll_ms: int = 1000) -> str:
    """창(탭)이 여러 개가 되거나 일부가 닫혀도, 열린 창 중 하나가 Redirect URI 로 돌아오면 그 주소를 돌려준다."""
    for _ in range(max(1, int(timeout_s * 1000 / poll_ms))):
        pages = [p for p in context.pages if not p.is_closed()]
        if not pages:  # 사용자가 창을 모두 닫음
            return ""
        for page in pages:
            if is_redirect(page.url, redirect_uri):
                return page.url
        try:
            pages[-1].wait_for_timeout(poll_ms)
        except Exception:  # 기다리는 사이 그 창이 닫힘 → 남은 창으로 계속 확인
            continue
    return ""


def authorize_in_browser(client_key: str, redirect_uri: str, state: str, timeout_s: float) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = launch_visible_browser(playwright.chromium)
        context = browser.new_context(locale="ko-KR")
        context.new_page().goto(build_authorize_url(client_key, redirect_uri, state))
        print(f"열린 창에서 틱톡에 로그인하고 '허용'을 누르세요. 최대 {int(timeout_s // 60)}분 기다립니다...")
        redirected = wait_for_redirect(context, redirect_uri, timeout_s)
        try:
            browser.close()
        except Exception:
            pass
    return redirected


def authorize_in_default_browser(
    authorize_url: str, prompt: Prompt = tk_prompt, opener: Callable[[str], bool] | None = None
) -> str:
    """평소 쓰는 크롬(기본 브라우저)에서 허용 → 이동한 페이지 주소를 입력 창에 붙여넣게 한다.

    이미 틱톡에 로그인된 브라우저를 쓰므로 다시 로그인할 필요가 없다.
    """
    import webbrowser

    (opener or webbrowser.open)(authorize_url)
    print("크롬에서 틱톡 '허용'을 누른 뒤, 이동한 페이지의 주소를 입력 창에 붙여넣으세요...")
    return prompt(
        "틱톡 설정 (3/3)",
        "크롬에서 '허용'을 누르면 본연클린 블로그 페이지로 이동합니다.\n"
        "그 페이지의 주소창 주소 전체를 복사해 여기에 붙여넣으세요.",
        False,
    ).strip()


def exchange_code(client_key: str, client_secret: str, code: str, redirect_uri: str, post=requests.post) -> dict:
    response = post(
        TOKEN_URL,
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description="틱톡 refresh token 발급")
    parser.add_argument("--redirect-uri", default=DEFAULT_REDIRECT_URI,
                        help=f"Login Kit 에 등록한 Redirect URI (기본: {DEFAULT_REDIRECT_URI})")
    parser.add_argument("--env", default=".env", help="값을 저장할 .env 경로 (기본: .env)")
    parser.add_argument("--no-upload", action="store_true", help="GitHub 시크릿 등록을 건너뜀")
    parser.add_argument("--timeout", type=float, default=600, help="로그인 대기 시간(초), 기본 10분")
    parser.add_argument("--playwright", action="store_true",
                        help="평소 크롬 대신 새 브라우저 창을 띄워 주소를 자동 감지 (틱톡 재로그인 필요)")
    args = parser.parse_args()

    env_path = Path(args.env)
    try:
        client_key, client_secret = resolve_credentials({**os.environ, **read_env_file(env_path)})
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1
    # 로그인 단계에서 실패해도 다시 실행할 때 키를 또 묻지 않도록 로컬 .env 에 먼저 저장
    update_env_file(env_path, {"TIKTOK_CLIENT_KEY": client_key, "TIKTOK_CLIENT_SECRET": client_secret})

    state = secrets.token_urlsafe(16)
    if args.playwright:
        redirected = authorize_in_browser(client_key, args.redirect_uri, state, args.timeout)
    else:
        redirected = authorize_in_default_browser(build_authorize_url(client_key, args.redirect_uri, state))
    if not redirected:
        print("❌ 틱톡 허용이 확인되지 않았습니다 (시간 초과 또는 창을 닫음). 다시 실행하세요.")
        return 1
    try:
        code = extract_code(redirected, state)
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1

    payload = exchange_code(client_key, client_secret, code, args.redirect_uri)
    if "refresh_token" not in payload:
        print(f"❌ 토큰 발급 실패: {payload.get('error')} - {payload.get('error_description')}")
        return 1

    values = {
        "TIKTOK_CLIENT_KEY": client_key,
        "TIKTOK_CLIENT_SECRET": client_secret,
        "TIKTOK_REFRESH_TOKEN": payload["refresh_token"],
    }
    if int(payload.get("refresh_expires_in", 0) or 0) > 0:  # 만료 알림용 만료일
        values["TIKTOK_REFRESH_EXPIRES_AT"] = expiry_from_seconds(payload["refresh_expires_in"])
    failed = save_everywhere(values, env_path, upload=not args.no_upload)
    days = int(payload.get("refresh_expires_in", 0)) // 86400
    print(f"✅ {args.env} 에 저장: {', '.join(values)}")
    print(f"   refresh token 유효기간 약 {days}일 · 허용된 스코프: {payload.get('scope', '')}")
    if failed:
        print(f"⚠️ GitHub 시크릿 등록 실패: {', '.join(failed)} — gh CLI 로그인(gh auth status)을 확인하세요.")
        return 1
    if not args.no_upload:
        print("✅ GitHub 시크릿 등록 완료: " + ", ".join(values))
    return 0


if __name__ == "__main__":
    sys.exit(main())
