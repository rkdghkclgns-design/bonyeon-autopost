"""로컬 사진 폴더로 포스팅 미리보기 (드라이브·슬랙·블로그에 아무것도 올리지 않음).

사진 폴더 구조
  <사진폴더>/작업전/*.jpg   <사진폴더>/작업중/*.jpg   <사진폴더>/작업후/*.jpg   (없는 단계는 생략 가능)
  <사진폴더>/고객후기/*.jpg  (선택 — 동의받은 실제 후기 캡처)

실행
  python scripts/preview_post.py <사진폴더> --category 로프청소 [--location 고잔동] [--day 739522]

결과 (output/preview_날짜시간/)
  preview.html  — 구글 블로그에 올라갈 모습 그대로 (사진 포함 파일 하나, 브라우저로 열기)
  tiktok.mp4    — 9:16 틱톡 영상
  post.txt      — 네이버 수동 발행용 원고
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

from autopost import templates  # noqa: E402
from autopost.ai_helper import ContentGenerator  # noqa: E402
from autopost.preview_page import write_preview  # noqa: E402
from autopost.constants import CATEGORIES, STAGES  # noqa: E402
from autopost.image_wash import wash_all  # noqa: E402
from autopost.pipeline import KST, PostMedia, _build_slides, _make_comparison  # noqa: E402
from autopost.config import load_config  # noqa: E402
from autopost.regions import pick_area, site_area  # noqa: E402
from autopost.video_maker import make_video  # noqa: E402

STAGE_DIRS = {"작업전": "before", "작업중": "during", "작업후": "after"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}

def _images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.glob("*") if p.suffix.lower() in IMAGE_EXTS) if folder.is_dir() else []


def collect(photo_dir: Path) -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = {}
    for stage in STAGES:
        folder = photo_dir / stage
        found[stage] = _images(folder if folder.is_dir() else photo_dir / STAGE_DIRS[stage])
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="로컬 포스팅 미리보기")
    parser.add_argument("photo_dir", type=Path)
    parser.add_argument("--category", default="정기청소", choices=[c.name for c in CATEGORIES])
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--location", default="", help="실제 현장 위치 (예: 고잔동). 비우면 서비스 지역 순환")
    parser.add_argument("--day", type=int, default=None, help="지역 순환 순번 (기본: 오늘 날짜)")
    args = parser.parse_args()

    load_dotenv()
    cfg = load_config()
    if not cfg.gemini_api_key:
        print("❌ .env 에 GEMINI_API_KEY 가 필요합니다")
        return 1
    originals = collect(args.photo_dir)
    if not any(originals.values()):
        print(f"❌ {args.photo_dir} 아래 작업전/작업중/작업후 폴더에 사진이 없습니다")
        return 1

    now = datetime.now(KST)
    out = args.out or cfg.output_dir / f"preview_{now:%Y%m%d_%H%M%S}"
    area = site_area(args.location) or pick_area(cfg.service_areas, args.day or now.toordinal())
    washed = {
        stage: tuple(wash_all(paths, out / "photos" / STAGE_DIRS[stage], seed=7)) if paths else ()
        for stage, paths in originals.items()
    }
    review_sources = _images(args.photo_dir / "고객후기")[: max(cfg.reviews_per_post, 0)]
    reviews = tuple(wash_all(review_sources, out / "photos" / "reviews", seed=7)) if review_sources else ()
    media = PostMedia(washed, _make_comparison(washed, out / "photos"), reviews)
    header = templates.generate_header(out / "assets" / "header.png", cfg.company_name)
    footer = templates.generate_footer(out / "assets" / "footer.png", cfg.company_name, cfg.company_phone)
    bgm = templates.generate_bgm(out / "assets" / "bgm.mp3")

    print("AI 원고 생성 중...")
    generator = ContentGenerator(
        cfg.gemini_api_key, cfg.gemini_model, cfg.company_name, cfg.company_phone,
        fallback_models=cfg.gemini_fallback_models,
    )
    content = generator.generate(args.category, washed, area=area)
    (out / "post.txt").write_text(
        content.plain_text() + f"\n\n[틱톡 캡션]\n{content.tiktok_caption}\n", encoding="utf-8"
    )
    page = write_preview(out / "preview.html", content, media.photos, header, footer,
                         media.comparison, media.reviews)

    print("틱톡 영상 생성 중...")
    video = make_video(_build_slides(cfg.company_name, media, footer), out / "tiktok.mp4",
                       bgm_path=bgm, total_seconds=cfg.video_seconds)

    where = f"{area.label} ({'실제 현장' if area.is_site else '서비스 지역'})" if area else "없음"
    print(f"\n✅ 미리보기 완료 (지역: {where}, 본문 {content.text_length():,}자)")
    print(f"  글: {page}\n  영상: {video}\n  원고: {out / 'post.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
