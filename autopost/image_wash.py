"""이미지 세탁: 회전 보정 → 1~2% 랜덤 크롭 → 리사이즈 → 미세 색감 조정 → EXIF 제거.

EXIF에는 촬영 위치(GPS)·기기 정보가 들어 있어 게시 전 반드시 제거한다.
아이폰 HEIC 사진도 pillow-heif 로 처리한다.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageEnhance, ImageOps

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover - 선택 의존성
    pass


@dataclass(frozen=True)
class WashOptions:
    max_side: int = 1600
    crop_min: float = 0.01
    crop_max: float = 0.02
    color_jitter: float = 0.02
    quality_range: tuple[int, int] = (88, 93)


def _random_crop(image: Image.Image, ratio: float, rng: random.Random) -> Image.Image:
    width, height = image.size
    dx, dy = int(width * ratio), int(height * ratio)
    left, top = rng.randint(0, dx), rng.randint(0, dy)
    return image.crop((left, top, width - (dx - left), height - (dy - top)))


def _jitter(image: Image.Image, amount: float, rng: random.Random) -> Image.Image:
    for enhancer in (ImageEnhance.Brightness, ImageEnhance.Contrast, ImageEnhance.Color):
        image = enhancer(image).enhance(1.0 + rng.uniform(-amount, amount))
    return image


def _strip_metadata(image: Image.Image) -> Image.Image:
    """픽셀 데이터만 복사한 새 이미지 — EXIF/ICC/XMP 등 모든 메타데이터 제거."""
    return Image.frombytes(image.mode, image.size, image.tobytes())


def wash_image(src: Path, dst: Path, rng: random.Random, options: WashOptions = WashOptions()) -> Path:
    with Image.open(src) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    image = _random_crop(image, rng.uniform(options.crop_min, options.crop_max), rng)
    image.thumbnail((options.max_side, options.max_side), Image.Resampling.LANCZOS)
    image = _strip_metadata(_jitter(image, options.color_jitter, rng))
    dst.parent.mkdir(parents=True, exist_ok=True)
    image.save(dst, "JPEG", quality=rng.randint(*options.quality_range), optimize=True)
    return dst


def wash_all(
    sources: Sequence[Path],
    out_dir: Path,
    seed: int | None = None,
    options: WashOptions = WashOptions(),
) -> list[Path]:
    rng = random.Random(seed)
    return [
        wash_image(src, out_dir / f"{index:02d}_{src.stem}.jpg", rng, options)
        for index, src in enumerate(sources, start=1)
    ]
