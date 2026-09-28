"""MoviePy 기반 9:16 숏폼 (1080×1920, 30fps).

화질을 위해
- 원본 고해상도 사진에서 바로 프레임을 만든다 (블로그용 1600px 축소본을 늘려 쓰지 않음)
- 가로 사진은 4:3 창으로 크게 보여주며 천천히 좌→우 패닝, 세로 사진은 천천히 확대(켄 번스)
- 사진 사이는 교차 전환(크로스페이드), 처음·끝은 검은 화면에서 서서히
- H.264 고화질 설정 (CRF 18, preset slow, High profile), 오디오 AAC 192kbps
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from .fonts import load_font

try:  # 아이폰 HEIC 원본도 열 수 있도록
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover
    pass

log = logging.getLogger(__name__)

FRAME_SIZE = (1080, 1920)
FPS = 30
PHOTO_TOP = 290  # 상단 라벨 아래부터 사진 영역
PHOTO_BOTTOM_MARGIN = 170  # 하단 상호·연락처 줄 공간
LANDSCAPE_BOX_RATIO = 4 / 3  # 가로 사진을 보여주는 창 비율 (좌→우 패닝)
ZOOM = 1.07  # 세로·비교 사진 켄 번스 확대 비율
CROSSFADE = 0.35
PLAIN_BACKGROUND = (22, 60, 84)  # 연락처 장면 단색 배경 (진한 청록)
STILL_SECONDS = 1.6  # 마지막 연락처(푸터) 이미지
FIT_SECONDS = 2.6  # 전후 비교 이미지
ENCODE_PARAMS = ["-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]


@dataclass(frozen=True)
class Slide:
    image_path: Path
    label: str = ""
    motion: str = "auto"  # auto(가로=패닝·세로=확대) | fit(전체가 보이게 + 살짝 확대) | still(고정)


def _open(path: Path) -> Image.Image:
    with Image.open(path) as opened:
        return ImageOps.exif_transpose(opened).convert("RGB")


def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image, size, Image.Resampling.LANCZOS)


def _draw_pill(frame: Image.Image, text: str, top: int, size: int, alpha: int = 170) -> None:
    draw = ImageDraw.Draw(frame, "RGBA")
    font = load_font(size)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = int(size * 0.7), int(size * 0.4)
    box_w, box_h = text_w + pad_x * 2, text_h + pad_y * 2
    left = (frame.width - box_w) // 2
    draw.rounded_rectangle((left, top, left + box_w, top + box_h), radius=box_h // 2, fill=(0, 0, 0, alpha))
    draw.text((left + pad_x - bbox[0], top + pad_y - bbox[1]), text, font=font, fill=(255, 255, 255, 255))


def _chrome(
    photo: Image.Image, label: str, footer_text: str, size: tuple[int, int] = FRAME_SIZE, plain: bool = False
) -> Image.Image:
    """사진 뒤 흐린 배경(plain 이면 단색) + 상단 라벨 + 하단 상호 줄 (슬라이드마다 한 번만 그림)."""
    if plain:  # 연락처 안내 같은 글자 이미지는 흐린 복제 배경이 지저분해 보여 단색으로
        frame = Image.new("RGB", size, PLAIN_BACKGROUND)
    else:
        background = _cover(photo, (size[0] // 4, size[1] // 4)).filter(ImageFilter.GaussianBlur(10))
        background = background.resize(size, Image.Resampling.BICUBIC)
        frame = Image.blend(background, Image.new("RGB", size, (0, 0, 0)), 0.45)
    if label:
        _draw_pill(frame, label, top=140, size=62)
    if footer_text:
        _draw_pill(frame, footer_text, top=size[1] - PHOTO_BOTTOM_MARGIN + 40, size=40, alpha=140)
    return frame


def _photo_area(size: tuple[int, int] = FRAME_SIZE) -> tuple[int, int]:
    return size[0], size[1] - PHOTO_TOP - PHOTO_BOTTOM_MARGIN


def _ease(progress: float) -> float:
    return 0.5 - 0.5 * np.cos(np.pi * min(max(progress, 0.0), 1.0))


class _Renderer:
    """슬라이드 한 장의 t초 시점 프레임을 만든다 (무거운 준비는 생성 시 한 번만)."""

    def __init__(self, slide: Slide, footer_text: str = "", size: tuple[int, int] = FRAME_SIZE) -> None:
        photo = _open(slide.image_path)
        self._size = size
        self._chrome = np.asarray(_chrome(photo, slide.label, footer_text, size, plain=slide.motion == "still"))
        area_w, area_h = _photo_area(size)
        # 4:3 창보다 충분히 넓은 가로 사진만 패닝 (덜 넓은 사진을 늘려 쓰지 않도록)
        landscape = photo.width / photo.height > LANDSCAPE_BOX_RATIO * 1.1
        self._mode = slide.motion if slide.motion != "auto" else ("pan" if landscape else "zoom")
        if self._mode == "pan":
            box_h = min(round(area_w / LANDSCAPE_BOX_RATIO), area_h)
            scale = box_h / photo.height
            wide = photo.resize((round(photo.width * scale), box_h), Image.Resampling.LANCZOS)
            self._source = np.asarray(wide)
            self._box = (area_w, box_h)
        else:
            fitted = ImageOps.contain(photo, (area_w, area_h), Image.Resampling.LANCZOS)
            self._box = fitted.size
            zoom = 1.0 if self._mode == "still" else ZOOM
            big = photo.resize((round(fitted.width * zoom), round(fitted.height * zoom)), Image.Resampling.LANCZOS)
            self._source_img = big
        self._offset = ((size[0] - self._box[0]) // 2, PHOTO_TOP + (area_h - self._box[1]) // 2)
        self._static: np.ndarray | None = None

    def frame(self, t: float, duration: float) -> np.ndarray:
        if self._mode == "still" and self._static is not None:
            return self._static
        progress = _ease(t / duration) if duration > 0 else 0.0
        box_w, box_h = self._box
        if self._mode == "pan":
            span = self._source.shape[1] - box_w
            x = round(span * progress)
            region = self._source[:, x:x + box_w]
        else:
            big = self._source_img
            zoom_now = 1.0 + (big.width / box_w - 1.0) * progress
            crop_w, crop_h = big.width / zoom_now, big.height / zoom_now
            left, top = (big.width - crop_w) / 2, (big.height - crop_h) / 2
            region = np.asarray(big.resize((box_w, box_h), Image.Resampling.BILINEAR,
                                           box=(left, top, left + crop_w, top + crop_h)))
        frame = self._chrome.copy()
        x0, y0 = self._offset
        frame[y0:y0 + box_h, x0:x0 + box_w] = region
        if self._mode == "still":
            self._static = frame
        return frame


def compose_frame(image_path: Path, label: str = "", size: tuple[int, int] = FRAME_SIZE) -> Image.Image:
    """슬라이드 첫 프레임 (미리보기·테스트용)."""
    return Image.fromarray(_Renderer(Slide(image_path, label), size=size).frame(0.0, 1.0))


def slide_durations(slides: Sequence[Slide] | int, total_seconds: float, crossfade: float = 0.0) -> list[float]:
    """비교·푸터는 고정 길이, 나머지 사진이 남은 시간을 나눠 갖는다 (겹치는 전환 시간 포함)."""
    if isinstance(slides, int):
        slides = [Slide(Path("x"))] * slides
    count = len(slides)
    if count <= 0:
        raise ValueError("슬라이드가 최소 1장 필요합니다")
    budget = total_seconds + crossfade * (count - 1)
    fixed = {"still": STILL_SECONDS, "fit": FIT_SECONDS}
    fixed_total = sum(fixed.get(s.motion, 0.0) for s in slides)
    flexible = [s for s in slides if s.motion not in fixed]
    if not flexible or fixed_total >= budget * 0.6:  # 고정 길이가 너무 크면 균등 분배
        return [budget / count] * count
    each = (budget - fixed_total) / len(flexible)
    return [fixed.get(s.motion, each) for s in slides]


def make_video(
    slides: Sequence[Slide],
    out_path: Path,
    bgm_path: Path | None = None,
    total_seconds: float = 15.0,
    fade: float = CROSSFADE,
    footer_text: str = "",
    renderer_factory: Callable[[Slide, str], _Renderer] = _Renderer,
) -> Path:
    # moviepy 는 import 비용이 커서 실제 영상 생성 시에만 불러온다
    from moviepy import AudioFileClip, VideoClip, afx, concatenate_videoclips, vfx

    durations = slide_durations(slides, total_seconds, fade)
    clips = []
    for index, (slide, duration) in enumerate(zip(slides, durations)):
        renderer = renderer_factory(slide, footer_text)
        clip = VideoClip(lambda t, r=renderer, d=duration: r.frame(t, d), duration=duration)
        effects = [vfx.CrossFadeIn(fade)] if index > 0 else [vfx.FadeIn(fade)]
        if index == len(slides) - 1:
            effects.append(vfx.FadeOut(fade))
        clips.append(clip.with_effects(effects))
    video = concatenate_videoclips(clips, method="compose", padding=-fade) if len(clips) > 1 else clips[0]

    audio = None
    if bgm_path is not None and bgm_path.is_file():
        audio = AudioFileClip(str(bgm_path))
        if audio.duration < video.duration:
            audio = audio.with_effects([afx.AudioLoop(duration=video.duration)])
        audio = audio.subclipped(0, video.duration).with_effects([afx.AudioFadeIn(0.3), afx.AudioFadeOut(1.2)])
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
            audio_bitrate="192k",
            preset="slow",
            ffmpeg_params=ENCODE_PARAMS,
            logger=None,
        )
    finally:
        video.close()
        if audio is not None:
            audio.close()
        for clip in clips:
            clip.close()
    return out_path
