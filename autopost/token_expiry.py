"""네이버 로그인·틱톡 토큰 만료일 점검 → 만료 3일 전부터 슬랙 알림 채널에 보고.

실행 (GitHub Actions '로그인 토큰 만료 점검' 이 매일 실행)
  python -m autopost.token_expiry            # 만료 3일 이내일 때만 알림
  python -m autopost.token_expiry --force    # 만료일과 상관없이 지금 알림 (확인용)
  python -m autopost.token_expiry --dry-run  # 알림 없이 화면에만 출력

- 네이버: 저장된 로그인 정보(NAVER_STORAGE_STATE_B64)의 NID_AUT 쿠키 만료일
- 틱톡: 토큰 발급·갱신 때 저장해 둔 TIKTOK_REFRESH_EXPIRES_AT (refresh token 만료일)
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Mapping, Sequence

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
ALERT_DAYS = 3  # 만료 3일 전부터 알림
NAVER_AUTH_COOKIE = "NID_AUT"
RENEW_HINTS = {
    "네이버": "python scripts/export_naver_cookies.py (로그인 상태 유지 체크)",
    "틱톡": "python scripts/get_tiktok_token.py",
}


@dataclass(frozen=True)
class TokenExpiry:
    platform: str
    expires: date | None  # None = 만료일을 알 수 없음

    def days_left(self, today: date) -> int | None:
        return None if self.expires is None else (self.expires - today).days

    def line(self, today: date) -> str:
        if self.expires is None:
            return f"• {self.platform}: 확인 불가 (다시 로그인·발급 필요할 수 있음)"
        left = self.days_left(today)
        status = "만료됨" if left < 0 else "오늘 만료" if left == 0 else f"{left}일 남음"
        return f"• {self.platform}: {self.expires:%Y-%m-%d} ({status})"


def naver_expiry(storage_state_b64: str) -> TokenExpiry:
    """로그인 쿠키(NID_AUT)의 만료 시각 → 날짜(KST). 해석할 수 없으면 만료일 없음."""
    try:
        state = json.loads(base64.b64decode(storage_state_b64).decode("utf-8"))
        cookie = next(c for c in state.get("cookies", []) if c.get("name") == NAVER_AUTH_COOKIE)
        expires = float(cookie.get("expires") or -1)
    except (ValueError, UnicodeDecodeError, StopIteration, AttributeError, TypeError):
        return TokenExpiry("네이버", None)
    if expires <= 0:  # 브라우저 세션 쿠키 — '로그인 상태 유지' 없이 저장된 경우
        return TokenExpiry("네이버", None)
    return TokenExpiry("네이버", datetime.fromtimestamp(expires, KST).date())


def tiktok_expiry(expires_at: str) -> TokenExpiry:
    try:
        return TokenExpiry("틱톡", date.fromisoformat(expires_at.strip()[:10]))
    except ValueError:
        return TokenExpiry("틱톡", None)


def expiry_from_seconds(seconds: int | float | str, now: datetime | None = None) -> str:
    """'N초 뒤 만료' → 만료 날짜 문자열 (YYYY-MM-DD, KST). 틱톡 refresh_expires_in 저장용."""
    now = now or datetime.now(KST)
    return (now.astimezone(KST) + timedelta(seconds=int(seconds))).date().isoformat()


def collect(env: Mapping[str, str]) -> list[TokenExpiry]:
    """설정된 플랫폼만 점검 (네이버 로그인 정보·틱톡 토큰이 없으면 목록에서 뺌)."""
    items: list[TokenExpiry] = []
    if env.get("NAVER_STORAGE_STATE_B64", "").strip():
        items.append(naver_expiry(env["NAVER_STORAGE_STATE_B64"]))
    if env.get("TIKTOK_CONFIGURED", "").strip().lower() in ("1", "true") or env.get("TIKTOK_REFRESH_EXPIRES_AT"):
        items.append(tiktok_expiry(env.get("TIKTOK_REFRESH_EXPIRES_AT", "")))
    return items


def needs_alert(items: Sequence[TokenExpiry], today: date, days: int = ALERT_DAYS) -> bool:
    """만료일을 아는 항목 중 하나라도 'days'일 이내(이미 만료 포함)이면 알림."""
    return any(left is not None and left <= days for left in (i.days_left(today) for i in items))


def build_message(items: Sequence[TokenExpiry], today: date, days: int = ALERT_DAYS) -> str:
    soon = [i.platform for i in items if (left := i.days_left(today)) is not None and left <= days]
    head = (f"🔑 로그인 토큰 만료 알림 — {', '.join(soon)} {days}일 이내 만료" if soon
            else "🔑 로그인 토큰 만료일 (확인용)")
    lines = [head, *(i.line(today) for i in items)]
    hints = [f"   {p} 갱신: `{RENEW_HINTS[p]}`" for p in soon if p in RENEW_HINTS]
    if hints:
        lines += ["", "만료되면 그 플랫폼 발행이 실패합니다. 내 PC에서 아래 명령으로 다시 로그인·발급하세요.", *hints]
    return "\n".join(lines)


def _post(text: str, env: Mapping[str, str]) -> bool:
    token = env.get("SLACK_BOT_TOKEN", "").strip()
    channel = (env.get("SLACK_CHANNEL_TOKEN_ALERT", "") or env.get("SLACK_CHANNEL_ID", "")).strip()
    if not (token and channel):
        log.error("SLACK_BOT_TOKEN / SLACK_CHANNEL_TOKEN_ALERT 가 없어 알림을 보내지 못했습니다")
        return False
    from slack_sdk import WebClient  # 점검만 할 때는 불러오지 않음
    from slack_sdk.errors import SlackApiError

    try:
        WebClient(token=token).chat_postMessage(channel=channel, text=text, unfurl_links=False)
    except SlackApiError as exc:
        log.error("슬랙 알림 실패: %s", exc.response.get("error"))
        return False
    return True


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None,
         today: date | None = None) -> int:
    parser = argparse.ArgumentParser(description="네이버·틱톡 로그인 토큰 만료 점검")
    parser.add_argument("--force", action="store_true", help="만료일과 상관없이 알림 보내기")
    parser.add_argument("--dry-run", action="store_true", help="알림 없이 출력만")
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    today = today or datetime.now(KST).date()

    items = collect(env)
    if not items:
        print("점검할 토큰이 없습니다 (네이버·틱톡 미설정)")
        return 0
    message = build_message(items, today)
    print(message)
    if args.dry_run or not (args.force or needs_alert(items, today)):
        return 0
    return 0 if _post(message, env) else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
