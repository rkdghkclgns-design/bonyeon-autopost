"""작업 전/후 사진을 좌우로 붙인 비교 이미지 생성 (블로그 글 끝·영상 마지막에 사용)."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from PIL import Image, ImageDraw, ImageOps

from .constants import STAGE_LABELS
from .fonts import load_font

GAP = 12
MAX_WIDTH = 1800
PANEL_HEIGHT = 900


def _panel(path: Path, height: int) -> Image.Image:
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    # 원본 방향과 무관하게 같은 정사각형 칸을 채운다. 비율을 유지해 중앙에서 자른다.
    return ImageOps.fit(image, (height, height), Image.Resampling.LANCZOS)


def _label(canvas: Image.Image, x: int, text: str) -> None:
    draw = ImageDraw.Draw(canvas, "RGBA")
    font = load_font(44)
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    left, top = x + 20, 20
    draw.rounded_rectangle((left, top, left + w + 40, top + h + 28), radius=18, fill=(0, 0, 0, 170))
    draw.text((left + 20 - bbox[0], top + 14 - bbox[1]), text, font=font, fill=(255, 255, 255, 255))


def make_contact_sheet(
    photos_by_stage: Mapping[str, Sequence[Path]], out_path: Path, thumb: int = 280
) -> Path | None:
    """선택된 사진을 단계별 한 줄씩 모은 미리보기 이미지 (슬랙 진행 스레드용)."""
    rows = [(stage, list(paths)) for stage, paths in photos_by_stage.items() if paths]
    if not rows:
        return None
    label_w, gap = 150, 8
    cols = max(len(paths) for _, paths in rows)
    canvas = Image.new("RGB", (label_w + cols * (thumb + gap) + gap, len(rows) * (thumb + gap) + gap), "white")
    draw = ImageDraw.Draw(canvas)
    font = load_font(34)
    for r, (stage, paths) in enumerate(rows):
        top = gap + r * (thumb + gap)
        draw.text((16, top + thumb // 2 - 20), STAGE_LABELS.get(stage, stage), font=font, fill=(40, 40, 40))
        for c, path in enumerate(paths):
            with Image.open(path) as opened:
                image = ImageOps.fit(ImageOps.exif_transpose(opened).convert("RGB"), (thumb, thumb))
            canvas.paste(image, (label_w + gap + c * (thumb + gap), top))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=85)
    return out_path


def make_vertical_comparison(
    before: Path, after: Path, out_path: Path, size: tuple[int, int] = (1080, 1460), gap: int = 16
) -> Path:
    """세로 영상용: 위 작업 전 / 아래 작업 후 (각 칸을 꽉 채우도록 잘라 크게 보여줌)."""
    panel = (size[0], (size[1] - gap) // 2)
    canvas = Image.new("RGB", size, "white")
    for index, (path, text) in enumerate(((before, "작업 전"), (after, "작업 후"))):
        with Image.open(path) as opened:
            photo = ImageOps.fit(ImageOps.exif_transpose(opened).convert("RGB"), panel, Image.Resampling.LANCZOS)
        top = index * (panel[1] + gap)
        canvas.paste(photo, (0, top))
        region = canvas.crop((0, top, panel[0], top + panel[1]))
        _label(region, 0, text)
        canvas.paste(region, (0, top))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=92)
    return out_path


def make_comparison(before: Path, after: Path, out_path: Path, height: int = PANEL_HEIGHT) -> Path:
    """블로그용: 작업 전·후를 동일한 정사각형 칸에 50:50으로 배치한다."""
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
