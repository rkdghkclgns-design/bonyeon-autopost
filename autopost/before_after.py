"""작업 전/후 사진을 좌우로 붙인 비교 이미지 생성 (블로그 글 끝·영상 마지막에 사용)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from .fonts import load_font

GAP = 12
MAX_WIDTH = 1800
PANEL_HEIGHT = 900


def _panel(path: Path, height: int) -> Image.Image:
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    width = max(1, round(image.width * height / image.height))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def _label(canvas: Image.Image, x: int, text: str) -> None:
    draw = ImageDraw.Draw(canvas, "RGBA")
    font = load_font(44)
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    left, top = x + 20, 20
    draw.rounded_rectangle((left, top, left + w + 40, top + h + 28), radius=18, fill=(0, 0, 0, 170))
    draw.text((left + 20 - bbox[0], top + 14 - bbox[1]), text, font=font, fill=(255, 255, 255, 255))


def make_comparison(before: Path, after: Path, out_path: Path, height: int = PANEL_HEIGHT) -> Path:
    left, right = _panel(before, height), _panel(after, height)
    total = left.width + GAP + right.width
    canvas = Image.new("RGB", (total, height), "white")
    canvas.paste(left, (0, 0))
    canvas.paste(right, (left.width + GAP, 0))
    _label(canvas, 0, "작업 전")
    _label(canvas, left.width + GAP, "작업 후")
    if canvas.width > MAX_WIDTH:
        canvas = canvas.resize((MAX_WIDTH, round(height * MAX_WIDTH / canvas.width)), Image.Resampling.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=90)
    return out_path
