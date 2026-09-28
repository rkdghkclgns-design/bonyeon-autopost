import pytest

from autopost import templates
from autopost.video_maker import FRAME_SIZE, Slide, compose_frame, make_video, slide_durations
from fakes import make_jpeg


def test_compose_frame_is_vertical_1080x1920(tmp_path):
    landscape = make_jpeg(tmp_path / "wide.jpg", size=(1600, 900))
    frame = compose_frame(landscape, "본연 | 작업 전")
    assert frame.size == FRAME_SIZE
    assert frame.mode == "RGB"


def test_slide_durations_split_evenly():
    assert slide_durations(3, 15.0) == [5.0, 5.0, 5.0]
    with pytest.raises(ValueError):
        slide_durations(0, 15.0)


def test_make_video_with_bgm(tmp_path):
    from moviepy import VideoFileClip

    slides = [
        Slide(make_jpeg(tmp_path / "a.jpg", color=(200, 30, 30)), "작업 전"),
        Slide(make_jpeg(tmp_path / "b.jpg", color=(30, 200, 30))),
    ]
    bgm = templates.generate_bgm(tmp_path / "bgm.mp3", seconds=1.0)  # 영상보다 짧음 → 반복
    out = make_video(slides, tmp_path / "out" / "video.mp4", bgm_path=bgm, total_seconds=2.0)

    clip = VideoFileClip(str(out))
    try:
        assert clip.size == list(FRAME_SIZE)
        assert clip.duration == pytest.approx(2.0, abs=0.15)
        assert clip.audio is not None
    finally:
        clip.close()


def test_make_video_without_bgm(tmp_path):
    slides = [Slide(make_jpeg(tmp_path / "a.jpg"))]
    out = make_video(slides, tmp_path / "silent.mp4", bgm_path=tmp_path / "missing.mp3", total_seconds=1.0)
    assert out.stat().st_size > 0
