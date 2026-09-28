import base64
import json
from datetime import date, datetime

import pytest

from autopost import token_expiry
from autopost.token_expiry import (
    KST,
    TokenExpiry,
    build_message,
    collect,
    expiry_from_seconds,
    naver_expiry,
    needs_alert,
    tiktok_expiry,
)

TODAY = date(2026, 10, 26)


def _naver_state(expires: float) -> str:
    state = {"cookies": [{"name": "NID_SES", "expires": 1}, {"name": "NID_AUT", "expires": expires}]}
    return base64.b64encode(json.dumps(state).encode()).decode()


def test_naver_expiry_reads_auth_cookie_date_in_kst():
    stamp = datetime(2026, 10, 29, 1, 0, tzinfo=KST).timestamp()
    assert naver_expiry(_naver_state(stamp)) == TokenExpiry("네이버", date(2026, 10, 29))


@pytest.mark.parametrize("encoded", ["!!!", _naver_state(-1), base64.b64encode(b'{"cookies": []}').decode()])
def test_naver_expiry_unknown_when_session_cookie_or_broken(encoded):
    assert naver_expiry(encoded).expires is None


def test_tiktok_expiry_and_seconds_conversion():
    assert tiktok_expiry("2027-09-28").expires == date(2027, 9, 28)
    assert tiktok_expiry("").expires is None
    now = datetime(2026, 9, 29, 23, 30, tzinfo=KST)
    assert expiry_from_seconds(86400 * 365, now) == "2027-09-29"


def test_alert_only_within_three_days_including_expired():
    far = TokenExpiry("틱톡", date(2027, 9, 28))
    assert not needs_alert([far, TokenExpiry("네이버", date(2026, 10, 30))], TODAY)  # 4일 남음
    assert needs_alert([far, TokenExpiry("네이버", date(2026, 10, 29))], TODAY)  # 3일 남음
    assert needs_alert([TokenExpiry("네이버", date(2026, 10, 20))], TODAY)  # 이미 만료
    assert not needs_alert([TokenExpiry("틱톡", None)], TODAY)  # 모르는 날짜로는 매일 울리지 않음


def test_message_lists_each_platform_with_date():
    items = [TokenExpiry("네이버", date(2026, 10, 29)), TokenExpiry("틱톡", date(2027, 9, 28))]
    text = build_message(items, TODAY)
    lines = text.splitlines()
    assert lines[0] == "🔑 로그인 토큰 만료 알림 — 네이버 3일 이내 만료"
    assert lines[1] == "• 네이버: 2026-10-29 (3일 남음)"
    assert lines[2] == "• 틱톡: 2027-09-28 (337일 남음)"
    assert "export_naver_cookies.py" in text and "get_tiktok_token.py" not in text


def test_collect_skips_unconfigured_platforms():
    assert collect({}) == []
    items = collect({"NAVER_STORAGE_STATE_B64": _naver_state(-1), "TIKTOK_CONFIGURED": "true"})
    assert [i.platform for i in items] == ["네이버", "틱톡"]


def test_main_posts_only_when_due(monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(token_expiry, "_post", lambda text, env: sent.append(text) or True)
    stamp = datetime(2026, 12, 1, tzinfo=KST).timestamp()
    env = {"NAVER_STORAGE_STATE_B64": _naver_state(stamp)}

    assert token_expiry.main([], env, TODAY) == 0 and sent == []  # 한 달 넘게 남음
    assert token_expiry.main(["--force"], env, TODAY) == 0 and len(sent) == 1  # 확인용 강제 알림
    assert "• 네이버: 2026-12-01" in sent[0]
    assert token_expiry.main([], env, date(2026, 11, 29)) == 0 and len(sent) == 2  # 2일 남음
    assert token_expiry.main(["--dry-run"], env, date(2026, 11, 29)) == 0 and len(sent) == 2
    assert "네이버" in capsys.readouterr().out


def test_extension_report_detects_extended_unchanged_and_not_saved():
    base = date(2026, 10, 29)
    today = date(2026, 9, 30)
    saved = "2026-09-30T01:12:00Z"  # KST 10:12
    extended = token_expiry.build_extension_report(base, TokenExpiry("네이버", date(2026, 10, 30)), saved, today)
    assert "• 이전 만료일: 2026-10-29" in extended and "• 현재 만료일: 2026-10-30" in extended
    assert "• 로그인 정보 저장: 2026-09-30 10:12" in extended and "✅" in extended

    same = token_expiry.build_extension_report(base, TokenExpiry("네이버", base), saved, today)
    assert "❌ 만료일이 그대로입니다" in same

    stale = token_expiry.build_extension_report(base, TokenExpiry("네이버", base), "2026-09-28T23:05:08Z", today)
    assert "오늘 저장 안 됨" in stale and "⚠️" in stale


def test_main_with_baseline_always_reports(monkeypatch):
    sent = []
    monkeypatch.setattr(token_expiry, "_post", lambda text, env: sent.append(text) or True)
    env = {"NAVER_STORAGE_STATE_B64": _naver_state(datetime(2026, 10, 30, tzinfo=KST).timestamp()),
           "NAVER_STATE_UPDATED_AT": "2026-09-30T01:12:00Z"}
    assert token_expiry.main(["--naver-baseline", "2026-10-29"], env, date(2026, 9, 30)) == 0
    assert len(sent) == 1 and "✅" in sent[0]
