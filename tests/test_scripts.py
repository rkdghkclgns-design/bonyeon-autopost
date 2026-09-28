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


@pytest.mark.parametrize("url,expected", [
    ("https://bonyeon-clean.blogspot.com/?code=abc&state=s", True),
    ("https://bonyeon-clean.blogspot.com?error=access_denied&state=s", True),
    ("https://bonyeon-clean.blogspot.com/", False),  # 아직 code 없음
    ("https://www.tiktok.com/v2/auth/authorize/?redirect_uri=https://bonyeon-clean.blogspot.com/&code=x", False),
    ("https://evil.example/?code=abc", False),
])
def test_is_redirect(url, expected):
    assert tiktok.is_redirect(url, "https://bonyeon-clean.blogspot.com/") is expected


def test_resolve_credentials_uses_env_then_prompts():
    asked = []

    def prompt(title, message, secret):
        asked.append(secret)
        return " typed-secret "

    assert tiktok.resolve_credentials({"TIKTOK_CLIENT_KEY": "key"}, prompt) == ("key", "typed-secret")
    assert asked == [True]  # 이미 있는 키는 묻지 않고, 비밀값 입력창은 가림 처리
    with pytest.raises(ValueError, match="입력되지"):
        tiktok.resolve_credentials({}, lambda *a: "")


def test_read_env_file_ignores_comments(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# TIKTOK_CLIENT_KEY=nope\nTIKTOK_CLIENT_KEY= k1 \nEMPTY=\n", encoding="utf-8")
    assert tiktok.read_env_file(env) == {"TIKTOK_CLIENT_KEY": "k1", "EMPTY": ""}
    assert tiktok.read_env_file(tmp_path / "missing") == {}


class _Page:
    def __init__(self, urls, closes_after=None):
        self._urls = iter(urls)
        self.url = next(self._urls)
        self._ticks = 0
        self._closes_after = closes_after

    def is_closed(self):
        return self._closes_after is not None and self._ticks >= self._closes_after

    def wait_for_timeout(self, ms):
        self._ticks += 1
        if self.is_closed():
            raise RuntimeError("Target page, context or browser has been closed")
        self.url = next(self._urls, self.url)


class _Context:
    def __init__(self, *pages):
        self.pages = list(pages)


def test_authorize_in_default_browser_opens_url_and_takes_pasted_address():
    opened, asked = [], []

    def prompt(title, message, secret):
        asked.append((title, secret))
        return "  https://r.example/?code=c&state=s \n"

    result = tiktok.authorize_in_default_browser("https://www.tiktok.com/v2/auth/authorize/?x=1", prompt,
                                                 opener=opened.append)
    assert opened == ["https://www.tiktok.com/v2/auth/authorize/?x=1"]
    assert asked == [("틱톡 설정 (3/3)", False)]
    assert result == "https://r.example/?code=c&state=s"


def test_wait_for_redirect_polls_until_code_arrives():
    page = _Page(["https://www.tiktok.com/login", "https://r.example/?code=c&state=s"])
    assert tiktok.wait_for_redirect(_Context(page), "https://r.example/", timeout_s=5) == \
        "https://r.example/?code=c&state=s"


def test_wait_for_redirect_follows_other_window_when_one_closes():
    login_popup = _Page(["https://www.tiktok.com/login"], closes_after=1)  # 로그인 팝업이 닫힘
    main = _Page(["https://www.tiktok.com/auth", "https://r.example/?code=c&state=s"])
    ctx = _Context(main, login_popup)
    assert tiktok.wait_for_redirect(ctx, "https://r.example/", timeout_s=5) == "https://r.example/?code=c&state=s"


def test_wait_for_redirect_returns_empty_when_all_windows_closed_or_timeout():
    closed = _Page(["https://www.tiktok.com/login"], closes_after=1)
    assert tiktok.wait_for_redirect(_Context(closed), "https://r.example/", timeout_s=5) == ""
    stuck = _Page(["https://www.tiktok.com/login"])
    assert tiktok.wait_for_redirect(_Context(stuck), "https://r.example/", timeout_s=2) == ""


def test_exchange_code_posts_form():
    sent = {}

    def post(url, data, headers, timeout):
        sent.update(url=url, data=data)
        return type("R", (), {"json": lambda self: {"refresh_token": "r"}})()

    assert tiktok.exchange_code("k", "s", "c", "https://r/", post=post) == {"refresh_token": "r"}
    assert sent["data"]["grant_type"] == "authorization_code" and sent["data"]["client_secret"] == "s"
