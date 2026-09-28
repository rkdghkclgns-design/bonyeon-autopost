"""환경변수 로딩 및 검증.

플랫폼(구글 블로그/네이버/틱톡)은 해당 시크릿이 모두 채워져 있을 때만 활성화된다.
시크릿을 비워두면 그 플랫폼은 자동으로 건너뛴다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

MODES = ("post", "setup")
NAVER_MODES = ("publish", "draft")
TIKTOK_MODES = ("direct", "inbox")
TIKTOK_PRIVACY_LEVELS = (
    "SELF_ONLY",
    "PUBLIC_TO_EVERYONE",
    "MUTUAL_FOLLOW_FRIENDS",
    "FOLLOWER_OF_CREATOR",
)
# 최신 flash 를 자동으로 가리키는 별칭 (특정 모델 은퇴에 영향받지 않음)
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
# 기본 모델이 과부하(503)·중단(404)일 때 순서대로 시도
DEFAULT_GEMINI_FALLBACKS = "gemini-3.8-flash,gemini-3.5-flash,gemini-3-flash-preview"
# 진행 단계별 슬랙 채널 (비우면 그 단계 결과물은 알림 채널의 진행 메시지 스레드에 올라감)
STAGE_CHANNEL_ENV = (
    ("prepare", "SLACK_CHANNEL_PHOTOS"),  # 사진 모음·전후 비교
    ("draft", "SLACK_CHANNEL_DRAFT"),  # AI 원고
    ("video", "SLACK_CHANNEL_VIDEO"),  # 틱톡 영상
    ("publish", "SLACK_CHANNEL_PUBLISH"),  # 발행 결과·수동 발행용 초안
)


class ConfigError(ValueError):
    """환경변수가 누락되었거나 형식이 잘못된 경우."""


@dataclass(frozen=True)
class GoogleConfig:
    client_id: str
    client_secret: str
    refresh_token: str


@dataclass(frozen=True)
class Config:
    company_name: str
    company_phone: str
    service_areas: tuple[str, ...]
    drive_root_name: str
    google: GoogleConfig | None
    gemini_api_key: str
    gemini_model: str
    gemini_fallback_models: tuple[str, ...]
    slack_bot_token: str
    slack_channel_id: str
    slack_webhook_url: str
    blogger_blog_id: str
    naver_blog_id: str
    naver_storage_state_b64: str
    naver_publish_mode: str
    tiktok_client_key: str
    tiktok_client_secret: str
    tiktok_refresh_token: str
    tiktok_mode: str
    tiktok_privacy_level: str
    photos_per_stage: int
    reviews_per_post: int
    min_photos: int
    video_seconds: float
    output_dir: Path
    slack_stage_channels: tuple[tuple[str, str], ...] = ()  # (진행 단계, 채널 ID)

    @property
    def blogger_enabled(self) -> bool:
        return bool(self.blogger_blog_id)

    @property
    def naver_enabled(self) -> bool:
        return bool(self.naver_blog_id and self.naver_storage_state_b64)

    @property
    def tiktok_enabled(self) -> bool:
        return bool(
            self.tiktok_client_key and self.tiktok_client_secret and self.tiktok_refresh_token
        )

    @property
    def slack_enabled(self) -> bool:
        return bool((self.slack_bot_token and self.slack_channel_id) or self.slack_webhook_url)

    def secret_values(self) -> tuple[str, ...]:
        """슬랙 전송 전 가려야 할 비밀값 목록."""
        google = (self.google.client_secret, self.google.refresh_token) if self.google else ()
        values = (
            *google,
            self.gemini_api_key,
            self.slack_bot_token,
            self.slack_webhook_url,
            self.naver_storage_state_b64,
            self.tiktok_client_secret,
            self.tiktok_refresh_token,
            os.environ.get("GH_SECRETS_TOKEN", ""),
        )
        return tuple(v for v in values if v)


def _get(env: Mapping[str, str], key: str, default: str = "") -> str:
    """공백만 있는 값도 '미설정'으로 보고 기본값을 쓴다."""
    return (env.get(key) or "").strip() or default


def _get_list(env: Mapping[str, str], key: str, default: str = "") -> tuple[str, ...]:
    """쉼표로 구분된 값을 목록으로 (빈 항목 제거, 순서·중복 정리)."""
    items = (item.strip() for item in _get(env, key, default).split(","))
    return tuple(dict.fromkeys(item for item in items if item))


def _get_int(env: Mapping[str, str], key: str, default: int, low: int, high: int) -> int:
    raw = _get(env, key, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} 값은 정수여야 합니다 (현재: {raw!r})") from exc
    if not low <= value <= high:
        raise ConfigError(f"{key} 값은 {low}~{high} 범위여야 합니다 (현재: {value})")
    return value


def _get_float(env: Mapping[str, str], key: str, default: float, low: float, high: float) -> float:
    raw = _get(env, key, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} 값은 숫자여야 합니다 (현재: {raw!r})") from exc
    if not low <= value <= high:
        raise ConfigError(f"{key} 값은 {low}~{high} 범위여야 합니다 (현재: {value})")
    return value


def _get_choice(env: Mapping[str, str], key: str, default: str, choices: tuple[str, ...]) -> str:
    value = _get(env, key, default)
    if value not in choices:
        raise ConfigError(f"{key} 값은 {', '.join(choices)} 중 하나여야 합니다 (현재: {value!r})")
    return value


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """환경변수에서 설정을 읽는다. 형식 오류는 ConfigError로 즉시 실패한다."""
    source = os.environ if env is None else env

    client_id = _get(source, "GOOGLE_CLIENT_ID")
    client_secret = _get(source, "GOOGLE_CLIENT_SECRET")
    refresh_token = _get(source, "GOOGLE_REFRESH_TOKEN")
    google = (
        GoogleConfig(client_id, client_secret, refresh_token)
        if client_id and client_secret and refresh_token
        else None
    )

    return Config(
        company_name=_get(source, "COMPANY_NAME", "우리 청소업체"),
        company_phone=_get(source, "COMPANY_PHONE", "000-0000-0000"),
        service_areas=_get_list(source, "SERVICE_AREA"),
        drive_root_name=_get(source, "DRIVE_ROOT_FOLDER_NAME", "청소업체_포스팅자동화"),
        google=google,
        gemini_api_key=_get(source, "GEMINI_API_KEY"),
        gemini_model=_get(source, "GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
        gemini_fallback_models=_get_list(source, "GEMINI_FALLBACK_MODELS", DEFAULT_GEMINI_FALLBACKS),
        slack_bot_token=_get(source, "SLACK_BOT_TOKEN"),
        slack_channel_id=_get(source, "SLACK_CHANNEL_ID"),
        slack_webhook_url=_get(source, "SLACK_WEBHOOK_URL"),
        blogger_blog_id=_get(source, "BLOGGER_BLOG_ID"),
        naver_blog_id=_get(source, "NAVER_BLOG_ID"),
        naver_storage_state_b64=_get(source, "NAVER_STORAGE_STATE_B64"),
        naver_publish_mode=_get_choice(source, "NAVER_PUBLISH_MODE", "publish", NAVER_MODES),
        tiktok_client_key=_get(source, "TIKTOK_CLIENT_KEY"),
        tiktok_client_secret=_get(source, "TIKTOK_CLIENT_SECRET"),
        tiktok_refresh_token=_get(source, "TIKTOK_REFRESH_TOKEN"),
        tiktok_mode=_get_choice(source, "TIKTOK_MODE", "direct", TIKTOK_MODES),
        tiktok_privacy_level=_get_choice(
            source, "TIKTOK_PRIVACY_LEVEL", "SELF_ONLY", TIKTOK_PRIVACY_LEVELS
        ),
        photos_per_stage=_get_int(source, "PHOTOS_PER_STAGE", 3, 1, 10),
        reviews_per_post=_get_int(source, "REVIEWS_PER_POST", 1, 0, 3),
        min_photos=_get_int(source, "MIN_PHOTOS", 3, 1, 30),
        video_seconds=_get_float(source, "VIDEO_SECONDS", 15.0, 3.0, 60.0),
        output_dir=Path(_get(source, "OUTPUT_DIR", "output")),
        slack_stage_channels=tuple(
            (stage, _get(source, key)) for stage, key in STAGE_CHANNEL_ENV if _get(source, key)
        ),
    )


def validate_for_mode(config: Config, mode: str) -> list[str]:
    """실행 모드에 필요한 필수 설정 누락 목록을 반환한다 (빈 리스트면 정상)."""
    if mode not in MODES:
        return [f"알 수 없는 실행 모드: {mode!r} (post / setup 중 선택)"]

    errors: list[str] = []
    if config.google is None:
        errors.append(
            "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN 이 필요합니다 "
            "(scripts/get_google_token.py 로 발급)"
        )
    if mode == "post":
        if not config.gemini_api_key:
            errors.append("GEMINI_API_KEY 가 필요합니다")
        if not (config.blogger_enabled or config.naver_enabled or config.tiktok_enabled):
            errors.append(
                "발행할 플랫폼이 하나도 설정되지 않았습니다 "
                "(BLOGGER_BLOG_ID / NAVER_* / TIKTOK_* 중 최소 1개)"
            )
    return errors


def platform_readiness(config: Config) -> list[tuple[str, bool, str]]:
    """슬랙 초기 세팅 보고용: (항목, 준비여부, 안내문) 목록."""
    return [
        ("구글 드라이브", config.google is not None, "GOOGLE_* 시크릿"),
        ("Gemini AI", bool(config.gemini_api_key), "GEMINI_API_KEY"),
        ("구글 블로그", config.blogger_enabled, "BLOGGER_BLOG_ID"),
        ("네이버 블로그", config.naver_enabled, "NAVER_BLOG_ID + NAVER_STORAGE_STATE_B64"),
        ("틱톡", config.tiktok_enabled, "TIKTOK_CLIENT_KEY/SECRET/REFRESH_TOKEN"),
        ("슬랙", config.slack_enabled, "SLACK_BOT_TOKEN + SLACK_CHANNEL_ID 또는 SLACK_WEBHOOK_URL"),
    ]
