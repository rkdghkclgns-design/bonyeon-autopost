"""MoviePy 기반 9:16 숏폼 슬라이드쇼 (페이드 + BGM + 단계 라벨)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from .fonts import load_font

log = logging.getLogger(__name__)

FRAME_SIZE = (1080, 1920)
PHOTO_BOX = (1000, 1480)
FPS = 30


@dataclass(frozen=True)
class Slide:
    image_path: Path
    label: str = ""


def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image, size, Image.Resampling.LANCZOS)


def _draw_label(frame: Image.Image, label: str) -> None:
    draw = ImageDraw.Draw(frame, "RGBA")
    font = load_font(64)
    bbox = draw.textbbox((0, 0), label, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 44, 26
    box_w, box_h = text_w + pad_x * 2, text_h + pad_y * 2
    left = (frame.width - box_w) // 2
    top = 150
    draw.rounded_rectangle((left, top, left + box_w, top + box_h), radius=box_h // 2, fill=(0, 0, 0, 170))
    draw.text((left + pad_x - bbox[0], top + pad_y - bbox[1]), label, font=font, fill=(255, 255, 255, 255))


def compose_frame(image_path: Path, label: str = "", size: tuple[int, int] = FRAME_SIZE) -> Image.Image:
    """흐린 배경 + 중앙 사진 + 상단 라벨 형태의 세로 프레임 생성."""
    with Image.open(image_path) as opened:
        photo = ImageOps.exif_transpose(opened).convert("RGB")
    background = _cover(photo, size).filter(ImageFilter.GaussianBlur(40))
    background = Image.blend(background, Image.new("RGB", size, (0, 0, 0)), 0.35)

    foreground = ImageOps.contain(photo, PHOTO_BOX, Image.Resampling.LANCZOS)
    frame = background.copy()
    offset = ((size[0] - foreground.width) // 2, (size[1] - foreground.height) // 2 + 60)
    frame.paste(foreground, offset)
    if label:
        _draw_label(frame, label)
    return frame


def slide_durations(count: int, total_seconds: float) -> list[float]:
    if count <= 0:
        raise ValueError("슬라이드가 최소 1장 필요합니다")
    return [total_seconds / count] * count


def make_video(
    slides: Sequence[Slide],
    out_path: Path,
    bgm_path: Path | None = None,
    total_seconds: float = 15.0,
    fade: float = 0.4,
) -> Path:
    # moviepy 는 import 비용이 커서 실제 영상 생성 시에만 불러온다
    from moviepy import AudioFileClip, ImageClip, afx, concatenate_videoclips, vfx

    durations = slide_durations(len(slides), total_seconds)
    clips = [
        ImageClip(np.asarray(compose_frame(slide.image_path, slide.label)))
        .with_duration(duration)
        .with_effects([vfx.FadeIn(min(fade, duration / 3)), vfx.FadeOut(min(fade, duration / 3))])
        for slide, duration in zip(slides, durations)
    ]
    video = concatenate_videoclips(clips, method="chain")

    audio = None
    if bgm_path is not None and bgm_path.is_file():
        audio = AudioFileClip(str(bgm_path))
        if audio.duration < video.duration:
            audio = audio.with_effects([afx.AudioLoop(duration=video.duration)])
        audio = audio.subclipped(0, video.duration).with_effects([afx.AudioFadeOut(1.0)])
        video = video.with_audio(audio)
    else:
        log.warning("BGM 파일이 없어 무음 영상으로 생성합니다")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        video.write_videofile(
            str(out_path),
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
            logger=None,
        )
    finally:
        video.close()
        if audio is not None:
            audio.close()
        for clip in clips:
            clip.close()
    return out_path
