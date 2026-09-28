import pytest

from autopost import cli
from autopost.pipeline import AlreadyReported, Services
from autopost.slack_helper import SlackNotifier
from fakes import MemoryDrive

ENV_PREFIXES = ("GOOGLE_", "GEMINI_", "SLACK_", "BLOGGER_", "NAVER_", "TIKTOK_", "AUTOPOST_", "PHOTOS_", "MIN_", "VIDEO_")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    import os

    for key in list(os.environ):
        if key.startswith(ENV_PREFIXES):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(cli, "_load_dotenv", lambda: None)


def _google(monkeypatch):
    for key, value in {"GOOGLE_CLIENT_ID": "c", "GOOGLE_CLIENT_SECRET": "s", "GOOGLE_REFRESH_TOKEN": "r"}.items():
        monkeypatch.setenv(key, value)


def test_parse_args_uses_env_defaults(monkeypatch):
    monkeypatch.setenv("AUTOPOST_MODE", "setup")
    monkeypatch.setenv("AUTOPOST_CATEGORY", "로프청소")
    monkeypatch.setenv("AUTOPOST_DRY_RUN", "true")
    monkeypatch.setenv("AUTOPOST_TRIGGER", "repository_dispatch")
    args = cli.parse_args([])
    assert (args.mode, args.category, args.dry_run, args.trigger) == ("setup", "로프청소", True, "repository_dispatch")


def test_parse_args_cli_overrides():
    args = cli.parse_args(["--mode", "post", "--category", "방역", "--dry-run"])
    assert (args.mode, args.category, args.dry_run) == ("post", "방역", True)


def test_missing_config_returns_2():
    assert cli.main(["--mode", "setup"]) == 2


def test_invalid_config_returns_2(monkeypatch):
    monkeypatch.setenv("PHOTOS_PER_STAGE", "many")
    assert cli.main(["--mode", "setup"]) == 2


def test_setup_mode_runs(monkeypatch):
    _google(monkeypatch)
    called = {}
    monkeypatch.setattr(cli, "build_services", lambda cfg, slack, mode: Services(drive=MemoryDrive(), slack=slack))
    monkeypatch.setattr(cli, "run_setup", lambda cfg, services: called.setdefault("setup", 0))
    assert cli.main(["--mode", "setup"]) == 0
    assert "setup" in called


def test_post_mode_passes_options(monkeypatch):
    _google(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("BLOGGER_BLOG_ID", "1")
    captured = {}
    monkeypatch.setattr(cli, "build_services", lambda cfg, slack, mode: Services(drive=MemoryDrive(), slack=slack))
    monkeypatch.setattr(cli, "run_post", lambda cfg, options, services: captured.setdefault("options", options) and 0)
    assert cli.main(["--category", "로프 고잔동", "--requested-by", "홍길동"]) == 0
    assert captured["options"].category == "로프"
    assert captured["options"].location == "고잔동"  # 슬랙 '/posting 로프 고잔동' 형태
    assert captured["options"].requested_by == "홍길동"


def test_post_mode_passes_run_url_from_env(monkeypatch):
    _google(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("BLOGGER_BLOG_ID", "1")
    monkeypatch.setenv("AUTOPOST_RUN_URL", "https://github.com/o/r/actions/runs/1")
    monkeypatch.setenv("AUTOPOST_TRIGGER", "slack")
    captured = {}
    monkeypatch.setattr(cli, "build_services", lambda cfg, slack, mode: Services(drive=MemoryDrive(), slack=slack))
    monkeypatch.setattr(cli, "run_post", lambda cfg, options, services: captured.setdefault("options", options) and 0)
    assert cli.main([]) == 0
    assert captured["options"].run_url == "https://github.com/o/r/actions/runs/1"
    assert captured["options"].trigger == "slack"


def test_already_reported_error_is_not_notified_twice(monkeypatch):
    _google(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("BLOGGER_BLOG_ID", "1")
    sent = []
    monkeypatch.setattr(SlackNotifier, "notify_error", lambda self, stage, error: sent.append(stage))
    monkeypatch.setattr(cli, "build_services", lambda cfg, slack, mode: Services(drive=MemoryDrive(), slack=slack))

    def reported(cfg, options, services):
        raise AlreadyReported("Gemini 503")

    monkeypatch.setattr(cli, "run_post", reported)
    assert cli.main([]) == 1
    assert sent == []  # 진행 스레드에 이미 보고됨


def test_unexpected_error_returns_1_and_notifies(monkeypatch):
    _google(monkeypatch)
    sent = []
    monkeypatch.setattr(SlackNotifier, "notify_error", lambda self, stage, error: sent.append((stage, str(error))))

    def boom(cfg, slack, mode):
        raise RuntimeError("token revoked")

    monkeypatch.setattr(cli, "build_services", boom)
    assert cli.main(["--mode", "setup"]) == 1
    assert sent == [("초기 세팅", "token revoked")]
