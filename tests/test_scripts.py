import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tiktok = _load("get_tiktok_token")
naver = _load("export_naver_cookies")


@pytest.mark.parametrize("url,expected", [
    ("https://blog.naver.com/bonyeon_clean", "bonyeon_clean"),
    ("https://blog.naver.com/bonyeon-clean/224340083352", "bonyeon-clean"),
    ("https://m.blog.naver.com/PostList.naver?blogId=abc123", "abc123"),
    ("https://blog.naver.com/MyBlog.naver", None),  # 로그인 안 됨 / 블로그 없음
    ("https://section.blog.naver.com/BlogHome.naver", None),
    ("https://blog.naver.com/prologue/PrologueList.naver", None),
    ("https://evil.example/blog.naver.com/abc", None),
    ("https://blog.naver.com/ab", None),  # 너무 짧음
])
def test_blog_id_from_url(url, expected):
    assert naver.blog_id_from_url(url) == expected


def test_upload_secrets_sends_values_via_stdin_only():
    calls = []

    def fake_run(cmd, input, text, capture_output):
        calls.append((cmd, input))
        return type("R", (), {"returncode": 1 if cmd[-1] == "B" else 0})()

    failed = naver.upload_secrets({"A": "secret-a", "B": "secret-b"}, run=fake_run)
    assert failed == ["B"]
    assert calls[0] == (["gh", "secret", "set", "A"], "secret-a")  # 값은 명령줄 인자에 넣지 않음
    assert all("secret-" not in " ".join(cmd) for cmd, _ in calls)


class _FakeLoginPage:
    def __init__(self):
        self.waits = []

    def wait_for_timeout(self, ms):
        self.waits.append(ms)


class _FakeLoginContext:
    def __init__(self, logged_in_after: int):
        self.calls = 0
        self.logged_in_after = logged_in_after

    def cookies(self):
        self.calls += 1
        if self.calls > self.logged_in_after:
            return [{"name": "NID_AUT"}, {"name": "NID_SES"}]
        return [{"name": "NNB"}]


def test_wait_for_login_detects_cookies_without_enter():
    page = _FakeLoginPage()
    assert naver.wait_for_login(_FakeLoginContext(logged_in_after=2), page, timeout_s=10, poll_ms=1000) is True
    assert page.waits == [1000, 1000, 3000]  # 2번 기다린 뒤 로그인 감지 → 이동 대기


def test_wait_for_login_times_out():
    page = _FakeLoginPage()
    assert naver.wait_for_login(_FakeLoginContext(logged_in_after=99), page, timeout_s=3, poll_ms=1000) is False
    assert len(page.waits) == 3


def test_upload_secrets_without_gh_cli_reports_all_failed():
    def missing(*args, **kwargs):
        raise FileNotFoundError("gh")

    assert naver.upload_secrets({"A": "1", "B": "2"}, run=missing) == ["A", "B"]


def test_authorize_url_contains_required_params():
    url = tiktok.build_authorize_url("key123", "https://me.blogspot.com/", "st")
    params = parse_qs(urlparse(url).query)
    assert params["client_key"] == ["key123"]
    assert params["redirect_uri"] == ["https://me.blogspot.com/"]
    assert params["response_type"] == ["code"]
    assert "video.publish" in params["scope"][0]


def test_extract_code_decodes_and_checks_state():
    url = "https://me.blogspot.com/?code=abc%2A123%21&scopes=video.publish&state=st"
    assert tiktok.extract_code(url, "st") == "abc*123!"


@pytest.mark.parametrize("url,message", [
    ("https://me.blogspot.com/?code=x&state=other", "state"),
    ("https://me.blogspot.com/?state=st", "code"),
    ("https://me.blogspot.com/?error=access_denied&error_description=denied&state=st", "거부"),
])
def test_extract_code_errors(url, message):
    with pytest.raises(ValueError, match=message):
        tiktok.extract_code(url, "st")
