"""포스팅/초기세팅 전체 흐름 오케스트레이션."""
from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

from . import blog_publisher, naver_publisher, tiktok_publisher
from .ai_helper import ContentGenerator, PostContent
from .blog_publisher import BloggerPublisher, build_blog_html, build_labels
from .config import Config, platform_readiness
from .before_after import make_comparison, make_contact_sheet, make_vertical_comparison
from .preview_page import write_naver_preview, write_preview
from .progress import ProgressReporter
from .step_summary import build_failure_summary, build_step_summary, write_step_summary
from .constants import (
    BGM_FILE,
    FOOTER_FILE,
    HEADER_FILE,
    STAGE_AFTER,
    STAGE_BEFORE,
    STAGE_LABELS,
    STAGES,
)
from .drive_helper import DriveFile, DriveHelper, folder_url, public_image_url
from .image_wash import wash_all
from .naver_publisher import NaverPublisher
from .photo_selector import PhotoSelection, UnknownCategoryError, last_posted_at, select_photos, usage_order
from .regions import pick_area, site_area
from .results import PublishResult
from .setup_engine import DriveLayout, SetupReport, ensure_layout
from .slack_helper import SlackNotifier, build_report_blocks, build_setup_blocks, escape_mrkdwn
from .tiktok_publisher import TikTokPublisher
from .video_maker import Slide, make_video

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\s]+')
VIDEO_PHOTOS_PER_STAGE = 2  # 15초에 사진이 너무 빨리 넘어가지 않도록 단계별 최대 2장 (한 장 약 1.8초)


@dataclass(frozen=True)
class RunOptions:
    category: str = ""
    dry_run: bool = False
    trigger: str = "manual"
    requested_by: str = ""
    location: str = ""  # 실제 현장 위치 (예: '고잔동', '안산 중앙동') — 없으면 서비스 지역 순환
    run_url: str = ""  # GitHub Actions 실행 로그 주소 (슬랙 진행 메시지에 링크)
    only: tuple[str, ...] = ()  # 이 플랫폼만 발행 (google / naver / tiktok). 비우면 전체


@dataclass(frozen=True)
class Services:
    drive: DriveHelper
    slack: SlackNotifier
    generator: ContentGenerator | None = None
    blogger: BloggerPublisher | None = None
    naver: NaverPublisher | None = None
    tiktok: TikTokPublisher | None = None
    washer: Callable[..., list[Path]] = wash_all
    video_maker: Callable[..., Path] = make_video
    now: Callable[[], datetime] = lambda: datetime.now(KST)


@dataclass(frozen=True)
class CommonAssets:
    header: DriveFile | None
    footer: DriveFile | None
    header_path: Path | None
    footer_path: Path | None
    bgm_path: Path | None


@dataclass(frozen=True)
class PostMedia:
    photos: Mapping[str, tuple[Path, ...]]  # 세탁된 사진 (단계별)
    comparison: Path | None = None  # 전후 비교 이미지
    reviews: tuple[Path, ...] = ()  # 실제 고객후기 캡처 (메타데이터 제거본)
    # 영상용 원본 고해상도 사진 (영상 프레임에는 사진 메타데이터가 남지 않음). 비면 photos 사용
    video_photos: Mapping[str, tuple[Path, ...]] = MappingProxyType({})
    # 작업 전·후 사진이 같은 현장끼리인지 — 이전 사진을 다시 조합했으면 False (전후 비교를 만들지 않음)
    pair_stages: bool = True


@dataclass(frozen=True)
class UsageOutcome:
    """사진 사용 기록 결과 — 사진은 옮기지 않고 드라이브 파일에 사용 횟수만 남긴다."""
    recorded: int = 0
    failed: tuple[str, ...] = ()


def safe_name(name: str) -> str:
    return UNSAFE_CHARS.sub("_", name).strip("_") or "file"


# ---------------------------------------------------------------- 초기 세팅
def _setup(cfg: Config, services: Services) -> SetupReport:
    return ensure_layout(services.drive, cfg.drive_root_name, cfg.company_name, cfg.company_phone)


def run_setup(cfg: Config, services: Services) -> int:
    report = _setup(cfg, services)
    blocks = build_setup_blocks(
        report.created_folders,
        report.created_files,
        platform_readiness(cfg),
        folder_url(report.layout.root_id),
    )
    services.slack.post("✅ [청소 자동화] 초기 세팅 완료", blocks)
    return 0


# ---------------------------------------------------------------- 포스팅 단계
def _download_selection(
    drive: DriveHelper, selection: PhotoSelection, workdir: Path
) -> Mapping[str, tuple[Path, ...]]:
    result: dict[str, tuple[Path, ...]] = {}
    for stage in STAGES:
        files = selection.files_by_stage.get(stage, ())
        result[stage] = tuple(
            drive.download(f.id, workdir / "original" / stage / f"{i:02d}_{safe_name(f.name)}")
            for i, f in enumerate(files, start=1)
        )
    return MappingProxyType(result)


def _download_assets(drive: DriveHelper, layout: DriveLayout, workdir: Path) -> CommonAssets:
    def fetch(folder_id: str, name: str) -> tuple[DriveFile | None, Path | None]:
        found = drive.find_child(folder_id, name)
        if found is None:
            log.warning("공통 파일이 없습니다: %s", name)
            return None, None
        return found, drive.download(found.id, workdir / "assets" / name)

    header, header_path = fetch(layout.header_folder_id, HEADER_FILE)
    footer, footer_path = fetch(layout.footer_folder_id, FOOTER_FILE)
    _, bgm_path = fetch(layout.bgm_folder_id, BGM_FILE)
    return CommonAssets(header, footer, header_path, footer_path, bgm_path)


def _make_comparison(washed: Mapping[str, Sequence[Path]], workdir: Path) -> Path | None:
    """작업 전·후 사진이 모두 있으면 첫 장끼리 좌우 비교 이미지를 만든다 (실패해도 발행은 계속)."""
    before, after = washed.get(STAGE_BEFORE, ()), washed.get(STAGE_AFTER, ())
    if not before or not after:
        return None
    try:
        return make_comparison(before[0], after[0], workdir / "compare.jpg")
    except Exception:
        log.exception("전후 비교 이미지 생성 실패")
        return None


def _build_slides(
    company: str, media: PostMedia, footer_path: Path | None, comparison: Path | None = None
) -> list[Slide]:
    source = media.video_photos or media.photos  # 영상은 원본 고해상도 사진으로
    comparison = comparison or media.comparison
    slides = [
        Slide(path, f"{company} | {STAGE_LABELS[stage]}")
        for stage in STAGES
        for path in source.get(stage, ())[:VIDEO_PHOTOS_PER_STAGE]
    ]
    if comparison is not None:
        slides.append(Slide(comparison, f"{company} | 작업 전 · 후", motion="fit"))
    if footer_path is not None:
        slides.append(Slide(footer_path, motion="still"))
    return slides


def _publish_blogger(
    services: Services,
    layout: DriveLayout,
    content: PostContent,
    media: PostMedia,
    assets: CommonAssets,
    category: str,
    stamp: str,
) -> PublishResult:
    drive = services.drive

    def upload_public(path: Path) -> str:
        uploaded = drive.upload(layout.public_folder_id, path, name=f"{stamp}_{category}_{path.name}")
        drive.make_public(uploaded.id)
        return public_image_url(uploaded.id)

    def public(file: DriveFile | None) -> str | None:
        if file is None:
            return None
        drive.make_public(file.id)
        return public_image_url(file.id)

    urls_by_stage = {stage: tuple(upload_public(p) for p in media.photos.get(stage, ())) for stage in STAGES}
    comparison_url = upload_public(media.comparison) if media.comparison else None
    review_urls = tuple(upload_public(p) for p in media.reviews)
    html_body = build_blog_html(
        content, urls_by_stage, public(assets.header), public(assets.footer), comparison_url, review_urls
    )
    return services.blogger.publish(content.title, html_body, build_labels(category, content.hashtags))


def _write_blog_previews(
    content: PostContent, media: PostMedia, assets: CommonAssets, workdir: Path, dry_run: bool
) -> tuple[Path | None, Path | None]:
    """검토용: 구글 블로그·네이버 블로그에 올라갈 모습 그대로의 페이지 (실패해도 포스팅은 계속)."""
    note = ("검토용 미리보기 — 아직 어디에도 게시되지 않았습니다." if dry_run
            else "발행된 글의 미리보기 사본입니다.")
    args = (content, media.photos, assets.header_path, assets.footer_path, media.comparison, media.reviews)
    previews: list[Path | None] = []
    for writer, name in ((write_preview, "blog_preview_google.html"), (write_naver_preview, "blog_preview_naver.html")):
        try:
            previews.append(writer(workdir / name, *args, note=note))
        except Exception:
            log.exception("블로그 미리보기 생성 실패: %s", name)
            previews.append(None)
    return previews[0], previews[1]


def _safely(platform: str, action: Callable[[], PublishResult]) -> PublishResult:
    try:
        return action()
    except Exception as exc:  # 한 플랫폼 실패가 다른 플랫폼 발행을 막지 않도록
        log.exception("%s 발행 실패", platform)
        return PublishResult.fail(platform, exc)


def _video_comparison(media: PostMedia, workdir: Path) -> Path | None:
    """세로 영상용 위(작업 전)/아래(작업 후) 비교 이미지 — 블로그용 가로 비교는 세로 화면에서 너무 작아진다."""
    source = media.video_photos or media.photos
    before, after = source.get(STAGE_BEFORE, ()), source.get(STAGE_AFTER, ())
    if not media.pair_stages or not before or not after:
        return None
    try:
        return make_vertical_comparison(before[0], after[0], workdir / "compare_vertical.jpg")
    except Exception:
        log.exception("영상용 전후 비교 이미지 생성 실패 — 블로그용 비교 이미지로 대신")
        return None


def _make_video(
    services: Services, cfg: Config, media: PostMedia, assets: CommonAssets, workdir: Path
) -> tuple[Path | None, str]:
    """영상 실패는 틱톡만의 실패로 처리해 블로그 발행은 계속 진행한다."""
    try:
        path = services.video_maker(
            _build_slides(cfg.company_name, media, assets.footer_path, _video_comparison(media, workdir)),
            workdir / "tiktok.mp4",
            bgm_path=assets.bgm_path,
            total_seconds=cfg.video_seconds,
            footer_text=f"{cfg.company_name} · {cfg.company_phone}",
        )
        return path, ""
    except Exception as exc:
        log.exception("틱톡 영상 생성 실패")
        return None, f"영상 생성 실패: {exc}"


def _publish_all(
    services: Services,
    layout: DriveLayout,
    content: PostContent,
    media: PostMedia,
    assets: CommonAssets,
    video: tuple[Path | None, str],
    category: str,
    stamp: str,
    only: Sequence[str] = (),
) -> list[PublishResult]:
    video_path, video_error = video
    results: list[PublishResult] = []
    excluded = "이번 실행에서 제외 (선택한 플랫폼만 발행)"
    if only and "google" not in only:
        results.append(PublishResult.skip(blog_publisher.PLATFORM, excluded))
    elif services.blogger is None:
        results.append(PublishResult.skip(blog_publisher.PLATFORM, "BLOGGER_BLOG_ID 미설정"))
    else:
        results.append(_safely(blog_publisher.PLATFORM, lambda: _publish_blogger(
            services, layout, content, media, assets, category, stamp)))

    if only and "naver" not in only:
        results.append(PublishResult.skip(naver_publisher.PLATFORM, excluded))
    elif services.naver is None:
        results.append(PublishResult.skip(naver_publisher.PLATFORM, "NAVER_* 미설정"))
    else:
        results.append(_safely(naver_publisher.PLATFORM, lambda: services.naver.publish(
            content, media.photos, assets.header_path, assets.footer_path, media.comparison, media.reviews)))

    if only and "tiktok" not in only:
        results.append(PublishResult.skip(tiktok_publisher.PLATFORM, excluded))
    elif services.tiktok is None:
        results.append(PublishResult.skip(tiktok_publisher.PLATFORM, "TIKTOK_* 미설정"))
    elif video_path is None:
        results.append(PublishResult.fail(tiktok_publisher.PLATFORM, video_error))
    else:
        results.append(_safely(tiktok_publisher.PLATFORM, lambda: services.tiktok.publish(
            video_path, content.tiktok_caption)))
    return results


def _dry_run_results(video_error: str) -> list[PublishResult]:
    reason = "테스트 실행(dry-run) — 발행 안 함"
    tiktok = (
        PublishResult.fail(tiktok_publisher.PLATFORM, video_error)
        if video_error else PublishResult.skip(tiktok_publisher.PLATFORM, reason)
    )
    return [
        PublishResult.skip(blog_publisher.PLATFORM, reason),
        PublishResult.skip(naver_publisher.PLATFORM, reason),
        tiktok,
    ]


def _select_reviews(drive: DriveHelper, layout: DriveLayout, limit: int) -> tuple[DriveFile, ...]:
    if limit <= 0 or not layout.review_folder_id:
        return ()
    try:
        return tuple(usage_order(drive.list_images(layout.review_folder_id), random.Random())[:limit])
    except Exception:
        log.exception("고객후기 폴더 조회 실패 — 후기 없이 진행")
        return ()


def _download_reviews(
    services: Services, files: Sequence[DriveFile], workdir: Path
) -> tuple[Path, ...]:
    if not files:
        return ()
    originals = [
        services.drive.download(f.id, workdir / "original" / "reviews" / f"{i:02d}_{safe_name(f.name)}")
        for i, f in enumerate(files, start=1)
    ]
    return tuple(services.washer(originals, workdir / "washed" / "reviews"))


def _record_usage(drive: DriveHelper, files: Sequence[DriveFile], now: datetime) -> UsageOutcome:
    """사용한 사진마다 사용 횟수를 1 올린다 — 일부가 실패해도 나머지는 계속 기록하고 실패 목록을 보고한다."""
    when = now.isoformat(timespec="seconds")
    recorded, failed = 0, []
    for file in files:
        try:
            drive.record_post(file.id, file.post_count + 1, when)
            recorded += 1
        except Exception:
            log.exception("사진 사용 기록 실패: %s", file.name)
            failed.append(file.name)
    return UsageOutcome(recorded, tuple(failed))


class AlreadyReported(RuntimeError):
    """진행 상황 스레드에 이미 오류를 보고함 — 상위에서 중복 알림을 보내지 않는다."""


# 정기 실행(GitHub 예비 + Cloudflare 주 실행) — 하루 1회만 발행하도록 이미 발행했으면 건너뛴다
SCHEDULED_TRIGGERS = ("schedule", "cron")

TRIGGER_LABELS = {
    "schedule": "정기 자동 실행",
    "cron": "정기 자동 실행",
    "workflow_dispatch": "수동 실행",
    "repository_dispatch": "슬랙 명령",
    "slack": "슬랙 명령",
    "manual": "로컬 실행",
}


def _stage_counts(selection: PhotoSelection) -> str:
    return " · ".join(
        f"{STAGE_LABELS[s]} {len(selection.files_by_stage.get(s, ()))}"
        for s in STAGES if selection.files_by_stage.get(s)
    )


def _results_line(results: Sequence[PublishResult]) -> str:
    icon = {True: "✅", False: "❌"}
    return " · ".join(f"{r.platform} {'⏭️' if r.skipped else icon[r.ok]}" for r in results)


def _meta_lines(category: str, area, options: RunOptions, now: datetime) -> list[str]:
    # 지역·트리거는 Actions 수동 입력(자유 텍스트)에서 올 수 있어 멘션·링크가 되지 않도록 이스케이프
    meta = [f"카테고리 *{category}*"]
    if area is not None:
        meta.append(f"지역 {escape_mrkdwn(area.label)} ({'실제 현장' if area.is_site else '서비스 지역'})")
    meta.append(escape_mrkdwn(TRIGGER_LABELS.get(options.trigger, options.trigger)))
    if options.requested_by:
        meta.append(f"요청 {escape_mrkdwn(options.requested_by)}")
    meta.append(f"{now:%m/%d %H:%M}")
    return meta


def _latest_naver_screenshot(output_dir: Path, since: float) -> Path | None:
    """이번 실행에서 네이버가 남긴 오류 화면 (GitHub Artifacts 대신 슬랙으로 보여준다)."""
    shots = [p for p in output_dir.glob("naver_*.png") if p.stat().st_mtime >= since]
    return max(shots, key=lambda p: p.stat().st_mtime) if shots else None


def _thread_fallbacks(
    reporter: ProgressReporter,
    results: Sequence[PublishResult],
    content: PostContent,
    naver_screenshot: Path | None = None,
) -> None:
    failed = {r.platform for r in results if not r.ok and not r.skipped}
    if naver_screenshot is not None:
        reporter.file(naver_screenshot, "네이버 화면", "🖥️ 네이버 발행이 멈춘 화면 (문제 확인용)", stage="publish")
    if naver_publisher.PLATFORM in failed:
        reporter.note(f"📝 네이버 블로그 수동 발행용 초안 (원고 파일과 같음)\n\n{content.plain_text()}",
                      stage="publish")
    if tiktok_publisher.PLATFORM in failed:
        reporter.note(f"🎬 틱톡은 만들어 둔 영상을 수동 업로드하세요\n캡션: {content.tiktok_caption}",
                      stage="publish")


def area_turn(now: datetime) -> int:
    """지역 키워드 순번 — 하루 1회 발행이므로 날짜마다 1씩 증가 (항목·시군구·동을 빠짐없이 순환)."""
    return now.toordinal()


def run_post(cfg: Config, options: RunOptions, services: Services) -> int:
    if services.generator is None:
        raise RuntimeError("포스팅 모드에는 ContentGenerator 가 필요합니다")
    slack = services.slack

    report = _setup(cfg, services)  # 1. 셀프 세팅 점검
    if report.changed:
        slack.post(f"🛠️ 셀프 세팅: 누락된 항목 {len(report.created_folders) + len(report.created_files)}개를 자동 생성했습니다")
    layout = report.layout

    if options.trigger in SCHEDULED_TRIGGERS and not options.dry_run:
        today = services.now().date().isoformat()
        if last_posted_at(services.drive, layout)[:10] == today:
            log.info("오늘(%s) 이미 발행했습니다 — 정기 실행을 건너뜁니다", today)
            write_step_summary(f"## ⏭️ 오늘({today}) 이미 발행해 정기 실행을 건너뜀\n하루 1회 발행 (중복 방지)")
            return 0

    try:  # 2. 사진 선택
        selection = select_photos(services.drive, layout, options.category, cfg.photos_per_stage, cfg.min_photos)
    except UnknownCategoryError as exc:
        slack.notify_error("카테고리 확인", exc)
        return 1
    if selection is None:
        target = escape_mrkdwn(options.category) or "전체 카테고리"
        slack.post(f"📭 [청소 자동화] {target}에 포스팅할 사진이 부족합니다 (최소 {cfg.min_photos}장). 드라이브에 사진을 올려주세요.")
        write_step_summary(f"## 📭 포스팅할 사진 없음\n{target} — 최소 {cfg.min_photos}장 필요")
        return 0

    now = services.now()
    # 실제 현장 위치가 주어지면 그 위치, 아니면 서비스 지역(시·구·동)을 날짜마다 순환
    area = site_area(options.location) or pick_area(cfg.service_areas, area_turn(now))
    if area is not None and area.is_site and selection.reused:
        # 이전 사진을 다시 조합한 글은 그 위치의 현장이 아니므로 위치는 서비스 지역 키워드로만 쓴다
        area = replace(area, is_site=False)
    tag = " [테스트]" if options.dry_run else ""
    reporter = ProgressReporter(
        slack, f"🧹 {selection.category} 포스팅 진행 중{tag}",
        _meta_lines(selection.category, area, options, now), options.run_url,
        stage_channels=dict(cfg.slack_stage_channels),
        run_label=f"{selection.category} · {now:%m/%d %H:%M}" + (" · 테스트" if options.dry_run else ""),
    )
    reporter.start()
    reporter.step("select", "done", f"{selection.total}장 ({_stage_counts(selection)})")
    try:
        return _run_steps(cfg, options, services, layout, selection, reporter, area, now)
    except Exception as exc:
        failed_step = reporter.fail_current(exc)
        write_step_summary(build_failure_summary(selection.category, failed_step, exc))
        raise AlreadyReported(str(exc)) from exc


def _run_steps(
    cfg: Config,
    options: RunOptions,
    services: Services,
    layout: DriveLayout,
    selection: PhotoSelection,
    reporter: ProgressReporter,
    area,
    now: datetime,
) -> int:
    stamp = now.strftime("%Y%m%d_%H%M")
    workdir = cfg.output_dir / f"{stamp}_{selection.category}"
    category = selection.category
    started = time.time()

    reporter.step("prepare", "run")  # 사진 다운로드·정리·전후 비교
    originals = _download_selection(services.drive, selection, workdir)
    washed = MappingProxyType({
        stage: tuple(services.washer(list(paths), workdir / "washed" / stage)) for stage, paths in originals.items()
    })
    assets = _download_assets(services.drive, layout, workdir)
    review_files = _select_reviews(services.drive, layout, cfg.reviews_per_post)
    # 이전 사진을 다시 조합했으면 작업 전·후가 다른 장소일 수 있어 전후 비교 이미지를 만들지 않는다
    comparison = None if selection.reused else _make_comparison(washed, workdir)
    media = PostMedia(
        washed, comparison, _download_reviews(services, review_files, workdir),
        video_photos=originals, pair_stages=not selection.reused,
    )
    mix = f"새 사진 {selection.fresh_count}장" + (" · 이전 사진 재조합" if selection.reused else "")
    reporter.file(make_contact_sheet(washed, workdir / "selected.jpg"), "선택된 사진",
                  f"📸 이번 글에 쓰는 사진 ({mix})", stage="prepare")
    reporter.file(media.comparison, "전후 비교", "🖼️ 전후 비교 이미지", stage="prepare")
    reporter.step("prepare", "done",
                  f"{mix} · 전후 비교 {'O' if media.comparison else 'X'} · 고객후기 {len(media.reviews)}장")

    reporter.step("draft", "run")  # AI 원고
    content = services.generator.generate(category, washed, area=area, reused=selection.reused)
    post_txt = workdir / "post.txt"
    post_txt.write_text(content.plain_text() + f"\n\n[틱톡 캡션]\n{content.tiktok_caption}\n", encoding="utf-8")
    reporter.step("draft", "done", f"본문 {content.text_length():,}자")
    reporter.file(post_txt, "원고", f"📝 *{content.title}*\n해시태그: {' '.join(content.hashtags[:6])} …",
                  stage="draft")
    google_preview, naver_preview = _write_blog_previews(content, media, assets, workdir, options.dry_run)
    reporter.file(google_preview, "구글 블로그 미리보기",
                  "👀 구글 블로그에 올라갈 모습 — 파일을 내려받아 브라우저로 열어 확인하세요", stage="draft")
    reporter.file(naver_preview, "네이버 블로그 미리보기",
                  "👀 네이버 블로그에 올라갈 모습 (에디터 입력 순서·줄바꿈 그대로)", stage="draft")

    reporter.step("video", "run")  # 틱톡 영상
    video_path, video_error = _make_video(services, cfg, media, assets, workdir)
    if video_path is not None:
        reporter.step("video", "done", f"{cfg.video_seconds:g}초 · 9:16")
        reporter.file(video_path, "틱톡 영상", f"🎬 틱톡 영상\n캡션: {content.tiktok_caption}", stage="video")
    else:
        reporter.step("video", "fail", video_error)

    if options.dry_run:  # 발행
        results = _dry_run_results(video_error)
        reporter.step("publish", "skip", "테스트 실행 — 발행 안 함")
    else:
        reporter.step("publish", "run")
        results = _publish_all(
            services, layout, content, media, assets, (video_path, video_error), category, stamp, options.only
        )
        reporter.step("publish", "done" if any(r.ok for r in results) else "fail", _results_line(results))

    outcome = UsageOutcome()  # 사진 사용 기록 (1곳이라도 성공했을 때만 — 전부 실패면 기록 안 함)
    if options.dry_run:
        reporter.step("usage", "skip", "테스트 실행 — 기록 안 함")
    elif any(r.ok for r in results):
        reporter.step("usage", "run")
        outcome = _record_usage(services.drive, [*selection.all_files(), *review_files], now)
        reporter.step("usage", "fail" if outcome.failed else "done",
                      f"{outcome.recorded}장 기록 · 사진은 폴더에 그대로"
                      + (f", {len(outcome.failed)}장 실패" if outcome.failed else ""))
    else:
        reporter.step("usage", "skip", "발행 실패 — 기록 안 함")

    _thread_fallbacks(reporter, results, content, _latest_naver_screenshot(cfg.output_dir, started))
    blocks = build_report_blocks(category, content.title, results, outcome.recorded,
                                 options.dry_run, outcome.failed)
    reporter.note(f"🧹 [청소 자동화] {category} 포스팅 결과", blocks, stage="publish")
    ok = options.dry_run or any(r.ok for r in results)
    reporter.finish(f"🧪 {category} 테스트 완료" if options.dry_run
                    else f"✅ {category} 포스팅 완료" if ok else f"❌ {category} 포스팅 실패")
    write_step_summary(build_step_summary(category, area, content, results, outcome, options.dry_run))
    return 0 if ok else 1
