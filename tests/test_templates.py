import numpy as np
from PIL import Image

from autopost import templates


def test_header_and_footer_sizes(tmp_path):
    header = templates.generate_header(tmp_path / "h.png", "본연")
    footer = templates.generate_footer(tmp_path / "f.png", "본연", "010-1234-5678")
    with Image.open(header) as h, Image.open(footer) as f:
        assert h.size == (1200, 300)
        assert f.size == (1200, 400)


def test_bgm_samples_shape_and_range():
    samples = templates.synthesize_bgm_samples(seconds=3.0)
    assert samples.shape == (3 * templates.SAMPLE_RATE, 2)
    assert samples.dtype == np.int16
    assert np.abs(samples).max() > 1000  # 무음이 아님
    assert abs(int(samples[0, 0])) < 50  # 페이드 인


def test_generate_bgm_writes_mp3_and_cleans_wav(tmp_path):
    path = templates.generate_bgm(tmp_path / "bgm.mp3", seconds=3.0)
    assert path.stat().st_size > 10_000
    assert not (tmp_path / "bgm.wav").exists()
