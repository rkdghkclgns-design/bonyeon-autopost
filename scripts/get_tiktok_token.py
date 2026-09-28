"""틱톡 refresh token 1회 발급 (내 PC에서 실행).

사전 준비 (README '틱톡' 항목 참고)
  1. https://developers.tiktok.com 에서 앱 생성 → Login Kit + Content Posting API 추가
  2. 스코프: user.info.basic, video.publish, video.upload
  3. Redirect URI 등록 (https 주소, 예: 내 구글 블로그 주소 https://xxxx.blogspot.com/)

실행
  python scripts/get_tiktok_token.py --client-key KEY --client-secret SECRET --redirect-uri https://xxxx.blogspot.com/

1. 출력되는 주소를 브라우저로 열어 틱톡 계정으로 로그인·허용
2. Redirect URI 로 이동된 뒤의 '주소창 전체 URL' 을 복사해 터미널에 붙여넣기
"""
from __future__ import annotations

import argparse
import secrets
import sys
from urllib.parse import parse_qs, urlencode, urlparse

import requests

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
SCOPES = "user.info.basic,video.publish,video.upload"


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


def main() -> int:
    parser = argparse.ArgumentParser(description="틱톡 refresh token 발급")
    parser.add_argument("--client-key", required=True)
    parser.add_argument("--client-secret", required=True)
    parser.add_argument("--redirect-uri", required=True)
    args = parser.parse_args()

    state = secrets.token_urlsafe(16)
    print("\n1) 아래 주소를 브라우저에서 열어 로그인·허용하세요:\n")
    print(build_authorize_url(args.client_key, args.redirect_uri, state))
    redirected = input("\n2) 이동된 페이지의 주소창 URL 전체를 붙여넣으세요: ")

    try:
        code = extract_code(redirected, state)
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1

    response = requests.post(
        TOKEN_URL,
        data={
            "client_key": args.client_key,
            "client_secret": args.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": args.redirect_uri,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    payload = response.json()
    if "refresh_token" not in payload:
        print(f"❌ 토큰 발급 실패: {payload.get('error')} - {payload.get('error_description')}")
        return 1

    days = int(payload.get("refresh_expires_in", 0)) // 86400
    print("\n✅ 발급 완료! 아래 값을 GitHub 시크릿에 등록하세요 (외부에 공유 금지)\n")
    print(f"TIKTOK_CLIENT_KEY={args.client_key}")
    print(f"TIKTOK_CLIENT_SECRET={args.client_secret}")
    print(f"TIKTOK_REFRESH_TOKEN={payload['refresh_token']}")
    print(f"\n(refresh token 유효기간: 약 {days}일 — 만료 전에 이 스크립트를 다시 실행하세요)")
    print(f"(허용된 스코프: {payload.get('scope', '')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
