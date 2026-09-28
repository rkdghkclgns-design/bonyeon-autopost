import numpy as np
import pytest
from PIL import Image

from autopost import templates
from autopost.video_maker import (
    CROSSFADE,
    FIT_SECONDS,
    FRAME_SIZE,
    STILL_SECONDS,
    Slide,
    _Renderer,
    compose_frame,
    make_video,
    slide_durations,
)
from fakes import make_jpeg


def test_compose_frame_is_vertical_1080x1920(tmp_path):
    landscape = make_jpeg(tmp_path / "wide.jpg", size=(1600, 900))
    frame = compose_frame(landscape, "본연 | 작업 전")
    assert frame.size == FRAME_SIZE
    assert frame.mode == "RGB"


def _striped(path, size):
    """왼쪽 절반 빨강, 오른쪽 절반 파랑인 사진 (패닝 방향 확인용)."""
    image = Image.new("RGB", size, (220, 30, 30))
    image.paste((30, 30, 220), (size[0] // 2, 0, size[0], size[1]))
    image.save(path, "JPEG", quality=95)
    return path


def test_wide_photo_pans_left_to_right_at_full_width(tmp_path):
    renderer = _Renderer(Slide(_striped(tmp_path / "wide.jpg", (4000, 1800)), "라벨"))
    start, end = renderer.frame(0.0, 2.0), renderer.frame(2.0, 2.0)
    mid_y = 1920 // 2
    # 사진이 화면 폭 전체(1080)를 채움 — 좌우 끝도 사진 색
    assert start[mid_y, 5, 0] > 150 and end[mid_y, 1075, 2] > 150
    # 처음엔 왼쪽(빨강), 끝엔 오른쪽(파랑)이 보임
    assert start[mid_y, 540, 0] > 150 and end[mid_y, 540, 2] > 150


def test_portrait_photo_zooms_in_slowly(tmp_path):
    photo = make_jpeg(tmp_path / "tall.jpg", size=(1200, 1800), color=(10, 150, 60))
    renderer = _Renderer(Slide(photo))
    assert renderer._mode == "zoom"
    first, last = renderer.frame(0.0, 2.0), renderer.frame(2.0, 2.0)
    assert first.shape == (1920, 1080, 3) and last.shape == first.shape


def test_still_slide_renders_once(tmp_path):
    renderer = _Renderer(Slide(make_jpeg(tmp_path / "f.jpg"), motion="still"))
    assert renderer.frame(0.1, 1.0) is renderer.frame(0.9, 1.0)


def test_slightly_wide_photo_is_not_stretched(tmp_path):
    renderer = _Renderer(Slide(make_jpeg(tmp_path / "a.jpg", size=(1300, 1000))))
    assert renderer._mode == "zoom"  # 4:3 에 가까우면 늘리지 않고 전체를 보여줌


def test_slide_durations_fixed_comparison_and_footer():
    assert slide_durations(3, 15.0) == [5.0, 5.0, 5.0]
    slides = [Slide(tmp) for tmp in ("a", "b")] + [Slide("c", motion="fit"), Slide("d", motion="still")]
    durations = slide_durations(slides, 15.0, crossfade=CROSSFADE)
    assert durations[2:] == [FIT_SECONDS, STILL_SECONDS]
    assert sum(durations) - CROSSFADE * 3 == pytest.approx(15.0)
    with pytest.raises(ValueError):
        slide_durations(0, 15.0)


def test_make_video_with_bgm_crossfades_and_keeps_total_length(tmp_path):
    from moviepy import VideoFileClip

    slides = [
        Slide(make_jpeg(tmp_path / "a.jpg", size=(1600, 700), color=(200, 30, 30)), "작업 전"),
        Slide(make_jpeg(tmp_path / "b.jpg", size=(700, 1200), color=(30, 200, 30))),
        Slide(make_jpeg(tmp_path / "c.jpg", color=(30, 30, 200)), motion="still"),
    ]
    bgm = templates.generate_bgm(tmp_path / "bgm.mp3", seconds=1.0)  # 영상보다 짧음 → 반복
    out = make_video(slides, tmp_path / "out" / "video.mp4", bgm_path=bgm, total_seconds=4.0,
                     footer_text="본연클린 · 010-0000-0000")

    clip = VideoFileClip(str(out))
    try:
        assert clip.size == list(FRAME_SIZE)
        assert clip.duration == pytest.approx(4.0, abs=0.2)
        assert clip.audio is not None
        assert np.asarray(clip.get_frame(2.0)).mean() > 20  # 중간 프레임은 검은 화면이 아님
    finally:
        clip.close()


def test_make_video_without_bgm(tmp_path):
    slides = [Slide(make_jpeg(tmp_path / "a.jpg"))]
    out = make_video(slides, tmp_path / "silent.mp4", bgm_path=tmp_path / "missing.mp3", total_seconds=1.0)
    assert out.stat().st_size > 0


def test_default_bgm_uses_bundled_cc0_track(tmp_path):
    path = templates.default_bgm(tmp_path / "bgm.mp3")
    assert path.read_bytes() == templates.DEFAULT_BGM.read_bytes()
    assert "CC0" in templates.DEFAULT_BGM_CREDIT
