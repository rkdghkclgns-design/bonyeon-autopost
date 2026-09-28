"""셀프 세팅용 기본 템플릿(헤더/푸터 이미지, BGM) 자동 생성.

BGM은 코드로 직접 합성한 음원이라 저작권 문제가 없다.
사용자는 드라이브에서 같은 파일명으로 교체만 하면 된다.
"""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw

from .fonts import load_font

BRAND_BG = (20, 108, 148)
BRAND_ACCENT = (255, 255, 255)
SAMPLE_RATE = 44100

# 부드러운 I-V-vi-IV 진행 (C - G - Am - F), 각 코드의 구성음 주파수(Hz)
CHORDS = (
    (261.63, 329.63, 392.00),
    (196.00, 246.94, 293.66),
    (220.00, 261.63, 329.63),
    (174.61, 220.00, 261.63),
)


def _draw_centered(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, font, fill) -> None:
    left, top, right, bottom = box
    bbox = draw.textbbox((0, 0), text, font=font)
    width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = left + (right - left - width) / 2 - bbox[0]
    y = top + (bottom - top - height) / 2 - bbox[1]
    draw.text((x, y), text, font=font, fill=fill)


def generate_header(path: Path, company_name: str, size: tuple[int, int] = (1200, 300)) -> Path:
    image = Image.new("RGB", size, BRAND_BG)
    draw = ImageDraw.Draw(image)
    width, height = size
    draw.rectangle((0, height - 12, width, height), fill=(255, 196, 0))
    _draw_centered(draw, (0, 30, width, 190), company_name, load_font(96), BRAND_ACCENT)
    _draw_centered(draw, (0, 190, width, 270), "전문 청소 · 로프 청소 · 방역 소독", load_font(40, bold=False), (220, 236, 245))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG")
    return path


def generate_footer(
    path: Path, company_name: str, phone: str, size: tuple[int, int] = (1200, 400)
) -> Path:
    image = Image.new("RGB", size, (245, 248, 250))
    draw = ImageDraw.Draw(image)
    width, height = size
    draw.rectangle((0, 0, width, 14), fill=BRAND_BG)
    _draw_centered(draw, (0, 40, width, 130), f"{company_name} 상담 문의", load_font(64), BRAND_BG)
    _draw_centered(draw, (0, 140, width, 250), f"☎ {phone}", load_font(80), (30, 30, 30))
    _draw_centered(draw, (0, 270, width, 350), "무료 견적 · 현장 방문 상담 가능", load_font(40, bold=False), (90, 90, 90))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG")
    return path


def synthesize_bgm_samples(seconds: float = 30.0, bpm: int = 88) -> np.ndarray:
    """잔잔한 아르페지오 + 패드 음원을 int16 스테레오 샘플로 합성."""
    total = int(seconds * SAMPLE_RATE)
    t_all = np.arange(total) / SAMPLE_RATE
    signal = np.zeros(total, dtype=np.float64)

    beat = 60.0 / bpm
    bar = beat * 4
    note_len = beat / 2
    for bar_index in range(int(np.ceil(seconds / bar))):
        chord = CHORDS[bar_index % len(CHORDS)]
        bar_start = bar_index * bar
        # 패드: 한 마디 동안 코드 전체를 은은하게
        start, end = int(bar_start * SAMPLE_RATE), min(total, int((bar_start + bar) * SAMPLE_RATE))
        if start >= total:
            break
        t = t_all[start:end] - bar_start
        pad = sum(np.sin(2 * np.pi * (f / 2) * t) for f in chord) / len(chord)
        pad_env = np.minimum(1.0, t / 0.4) * np.minimum(1.0, (bar - t) / 0.4)
        signal[start:end] += 0.18 * pad * pad_env
        # 아르페지오: 8분음표로 구성음 순환
        for step in range(8):
            freq = chord[step % 3] * (2 if step >= 4 else 1)
            n_start = int((bar_start + step * note_len) * SAMPLE_RATE)
            n_end = min(total, n_start + int(note_len * 1.6 * SAMPLE_RATE))
            if n_start >= total:
                break
            tn = t_all[n_start:n_end] - t_all[n_start]
            env = np.exp(-tn * 4.0) * np.minimum(1.0, tn / 0.01)
            signal[n_start:n_end] += 0.22 * np.sin(2 * np.pi * freq * tn) * env

    fade = int(min(2.0, seconds / 4) * SAMPLE_RATE)
    signal[:fade] *= np.linspace(0, 1, fade)
    signal[-fade:] *= np.linspace(1, 0, fade)
    peak = np.max(np.abs(signal)) or 1.0
    mono = (signal / peak * 0.7 * 32767).astype(np.int16)
    return np.column_stack([mono, mono])


def _write_wav(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(samples.tobytes())


DEFAULT_BGM = Path(__file__).resolve().parent / "data" / "bgm_default.mp3"
# 기본 배경음악: "Sunglasses" — Loyalty Freak Music (CC0 1.0 퍼블릭 도메인, 상업 이용·출처 표기 불필요)
# https://commons.wikimedia.org/wiki/File:Loyalty_Freak_Music_-_01_-_Sunglasses.ogg  (앞 40초, 음량 -14 LUFS)
DEFAULT_BGM_CREDIT = "Sunglasses — Loyalty Freak Music (CC0)"


def default_bgm(path: Path) -> Path:
    """기본 배경음악(무료 CC0 음원)을 복사한다. 음원 파일이 없으면 합성 음원으로 대신한다."""
    if DEFAULT_BGM.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(DEFAULT_BGM.read_bytes())
        return path
    return generate_bgm(path)


def generate_bgm(path: Path, seconds: float = 30.0) -> Path:
    """합성 음원을 mp3로 저장 (moviepy에 포함된 ffmpeg 바이너리 사용)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    wav_path = path.with_suffix(".wav")
    _write_wav(wav_path, synthesize_bgm_samples(seconds))
    try:
        subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(wav_path),
             "-codec:a", "libmp3lame", "-b:a", "160k", str(path)],
            check=True,
            capture_output=True,
        )
    finally:
        wav_path.unlink(missing_ok=True)
    return path
