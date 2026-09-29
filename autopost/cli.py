"""명령행 진입점. main.py / setup.py 가 이 모듈을 호출한다.

인자가 없으면 환경변수(AUTOPOST_*)를 사용한다 — GitHub Actions 는 환경변수로 값을 넘긴다.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Sequence

from .ai_helper import ContentGenerator
from .blog_publisher import BloggerPublisher
from .config import MODES, Config, ConfigError, load_config, validate_for_mode
from .drive_helper import DriveHelper
from .github_secrets import update_github_secret
from .google_auth import build_blogger_service, build_credentials, build_drive_service
from .naver_publisher import NaverPublisher
from .photo_selector import split_request
from .pipeline import AlreadyReported, RunOptions, Services, run_post, run_setup
from .slack_helper import SlackNotifier
from .tiktok_publisher import TikTokPublisher

log = logging.getLogger("autopost")

TRUTHY = {"1", "true", "yes", "y", "on"}


PLATFORM_KEYS = ("google", "naver", "tiktok")


def parse_only(text: str) -> tuple[str, ...]:
    """'naver' / 'google, naver' → ('naver',) … 모르는 이름은 오류."""
    names = tuple(dict.fromkeys(t.strip().lower() for t in text.split(",") if t.strip()))
    unknown = [n for n in names if n not in PLATFORM_KEYS]
    if unknown:
        raise SystemExit(f"--only 에 알 수 없는 플랫폼: {', '.join(unknown)} (사용 가능: {', '.join(PLATFORM_KEYS)})")
    return names


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in TRUTHY


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="청소업체 올인원 포스팅 자동화")
    parser.add_argument("--mode", choices=MODES, default=os.environ.get("AUTOPOST_MODE") or "post")
    parser.add_argument("--category", default=os.environ.get("AUTOPOST_CATEGORY", ""),
                        help="정기청소 / 로프청소 / 방역소독 (비우면 사진이 가장 많은 카테고리)")
    parser.add_argument("--dry-run", action="store_true", default=_env_flag("AUTOPOST_DRY_RUN"),
                        help="발행·사진이동 없이 원고/영상만 만들어 슬랙으로 미리보기")
    parser.add_argument("--location", default=os.environ.get("AUTOPOST_LOCATION", ""),
                        help="실제 현장 위치 (예: 고잔동, '안산 중앙동'). --category 뒤에 붙여도 됨")
    parser.add_argument("--trigger", default=os.environ.get("AUTOPOST_TRIGGER", "manual"))
    parser.add_argument("--requested-by", default=os.environ.get("AUTOPOST_REQUESTED_BY", ""))
    parser.add_argument("--only", default=os.environ.get("AUTOPOST_ONLY", ""),
                        help="이 플랫폼만 발행 (쉼표 구분: google,naver,tiktok). 비우면 전체")
    return parser.parse_args(argv)


def build_services(cfg: Config, slack: SlackNotifier, mode: str) -> Services:
    creds = build_credentials(cfg.google)
    drive = DriveHelper(build_drive_service(creds))
    if mode == "setup":
        return Services(drive=drive, slack=slack)

    generator = ContentGenerator(
        cfg.gemini_api_key,
        cfg.gemini_model,
        cfg.company_name,
        cfg.company_phone,
        fallback_models=cfg.gemini_fallback_models,
    )
    blogger = (
        BloggerPublisher(build_blogger_service(creds), cfg.blogger_blog_id) if cfg.blogger_enabled else None
    )
    naver = (
        NaverPublisher(
            cfg.naver_blog_id,
            cfg.naver_storage_state_b64,
            cfg.naver_publish_mode,
            cfg.output_dir,
            on_session_updated=lambda value: update_github_secret("NAVER_STORAGE_STATE_B64", value),
        )
        if cfg.naver_enabled else None
    )
    tiktok = (
        TikTokPublisher(
            cfg.tiktok_client_key,
            cfg.tiktok_client_secret,
            cfg.tiktok_refresh_token,
            mode=cfg.tiktok_mode,
            privacy_level=cfg.tiktok_privacy_level,
            on_token_rotated=lambda value: update_github_secret("TIKTOK_REFRESH_TOKEN", value),
            on_refresh_expiry=lambda value: update_github_secret("TIKTOK_REFRESH_EXPIRES_AT", value),
        )
        if cfg.tiktok_enabled else None
    )
    return Services(drive=drive, slack=slack, generator=generator, blogger=blogger, naver=naver, tiktok=tiktok)


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    load_dotenv()


def main(argv: Sequence[str] | None = None) -> int:
    _load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    args = parse_args(argv)
    try:
        cfg = load_config()
    except ConfigError as exc:
        log.error("설정 오류: %s", exc)
        return 2

    slack = SlackNotifier(
        cfg.slack_bot_token, cfg.slack_channel_id, cfg.slack_webhook_url, secrets=cfg.secret_values()
    )
    errors = validate_for_mode(cfg, args.mode)
    if errors:
        for error in errors:
            log.error("설정 누락: %s", error)
        slack.notify_error("설정 검증", "\n".join(errors))
        return 2

    try:
        services = build_services(cfg, slack, args.mode)
        if args.mode == "setup":
            return run_setup(cfg, services)
        category, location = split_request(args.category)
        options = RunOptions(
            category=category,
            dry_run=args.dry_run,
            trigger=args.trigger,
            requested_by=args.requested_by,
            location=args.location or location,
            run_url=os.environ.get("AUTOPOST_RUN_URL", ""),
            only=parse_only(args.only),
        )
        return run_post(cfg, options, services)
    except AlreadyReported:
        log.exception("실행 중 오류 (슬랙 진행 스레드에 보고됨)")
        return 1
    except Exception as exc:
        log.exception("실행 중 오류")
        slack.notify_error("초기 세팅" if args.mode == "setup" else "포스팅", exc)
        return 1
