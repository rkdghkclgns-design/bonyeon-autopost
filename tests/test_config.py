import pytest

from autopost.config import ConfigError, load_config, platform_readiness, validate_for_mode

GOOGLE = {"GOOGLE_CLIENT_ID": "cid", "GOOGLE_CLIENT_SECRET": "sec", "GOOGLE_REFRESH_TOKEN": "rt"}


def test_defaults_when_env_empty():
    cfg = load_config({})
    assert cfg.google is None
    assert cfg.photos_per_stage == 3
    assert cfg.min_photos == 3
    assert cfg.video_seconds == 15.0
    assert cfg.naver_publish_mode == "publish"
    assert cfg.tiktok_mode == "direct"
    assert cfg.tiktok_privacy_level == "SELF_ONLY"
    assert cfg.gemini_model == "gemini-flash-latest"
    assert cfg.gemini_fallback_models[0] == "gemini-3.8-flash"


def test_service_areas_parsing():
    cfg = load_config({"SERVICE_AREA": "서울, 경기 ,인천,안산,경기"})
    assert cfg.service_areas == ("서울", "경기", "인천", "안산")
    assert load_config({}).service_areas == ()


def test_reviews_per_post_range():
    assert load_config({}).reviews_per_post == 1
    assert load_config({"REVIEWS_PER_POST": "0"}).reviews_per_post == 0
    with pytest.raises(ConfigError):
        load_config({"REVIEWS_PER_POST": "4"})


def test_gemini_fallback_models_parsing():
    cfg = load_config({"GEMINI_MODEL": "m1", "GEMINI_FALLBACK_MODELS": " m2 , ,m3 "})
    assert (cfg.gemini_model, cfg.gemini_fallback_models) == ("m1", ("m2", "m3"))
    assert load_config({"GEMINI_FALLBACK_MODELS": " "}).gemini_fallback_models[0] == "gemini-3.8-flash"
    assert not (cfg.blogger_enabled or cfg.naver_enabled or cfg.tiktok_enabled or cfg.slack_enabled)


def test_platforms_enabled_only_when_all_secrets_present():
    cfg = load_config({
        **GOOGLE,
        "BLOGGER_BLOG_ID": "123",
        "NAVER_BLOG_ID": "myblog",  # 세션 없음 → 비활성
        "TIKTOK_CLIENT_KEY": "k", "TIKTOK_CLIENT_SECRET": "s", "TIKTOK_REFRESH_TOKEN": "r",
        "SLACK_WEBHOOK_URL": "https://hooks.slack.com/x",
    })
    assert cfg.google is not None
    assert cfg.blogger_enabled
    assert not cfg.naver_enabled
    assert cfg.tiktok_enabled
    assert cfg.slack_enabled


def test_values_are_stripped():
    cfg = load_config({"COMPANY_NAME": "  본연  ", "BLOGGER_BLOG_ID": " 42 "})
    assert cfg.company_name == "본연"
    assert cfg.blogger_blog_id == "42"


@pytest.mark.parametrize("key,value", [
    ("PHOTOS_PER_STAGE", "abc"),
    ("PHOTOS_PER_STAGE", "0"),
    ("MIN_PHOTOS", "99"),
    ("VIDEO_SECONDS", "1"),
    ("VIDEO_SECONDS", "x"),
    ("NAVER_PUBLISH_MODE", "auto"),
    ("TIKTOK_MODE", "upload"),
    ("TIKTOK_PRIVACY_LEVEL", "PUBLIC"),
])
def test_invalid_values_raise(key, value):
    with pytest.raises(ConfigError):
        load_config({key: value})


def test_validate_setup_needs_only_google():
    assert validate_for_mode(load_config(GOOGLE), "setup") == []
    assert len(validate_for_mode(load_config({}), "setup")) == 1


def test_validate_post_requires_gemini_and_platform():
    errors = validate_for_mode(load_config(GOOGLE), "post")
    assert any("GEMINI_API_KEY" in e for e in errors)
    assert any("플랫폼" in e for e in errors)
    ok = load_config({**GOOGLE, "GEMINI_API_KEY": "g", "BLOGGER_BLOG_ID": "1"})
    assert validate_for_mode(ok, "post") == []


def test_validate_unknown_mode():
    assert validate_for_mode(load_config(GOOGLE), "deploy")


def test_secret_values_collects_only_filled_secrets(monkeypatch):
    monkeypatch.setenv("GH_SECRETS_TOKEN", "github_pat_x")
    cfg = load_config({**GOOGLE, "GEMINI_API_KEY": "gem", "TIKTOK_REFRESH_TOKEN": "tt"})
    assert set(cfg.secret_values()) == {"sec", "rt", "gem", "tt", "github_pat_x"}
    monkeypatch.delenv("GH_SECRETS_TOKEN")
    assert load_config({}).secret_values() == ()


def test_readiness_lists_all_integrations():
    items = platform_readiness(load_config({**GOOGLE, "GEMINI_API_KEY": "g"}))
    names = [name for name, _, _ in items]
    assert names == ["구글 드라이브", "Gemini AI", "구글 블로그", "네이버 블로그", "틱톡", "슬랙"]
    assert dict((n, ok) for n, ok, _ in items)["Gemini AI"] is True


def test_stage_channels_only_include_configured_ones():
    cfg = load_config({"SLACK_CHANNEL_PHOTOS": "C1", "SLACK_CHANNEL_VIDEO": " ", "SLACK_CHANNEL_PUBLISH": "C4"})
    assert dict(cfg.slack_stage_channels) == {"prepare": "C1", "publish": "C4"}
    assert load_config({}).slack_stage_channels == ()
