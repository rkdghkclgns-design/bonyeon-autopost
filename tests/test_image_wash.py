import random

from PIL import Image

from autopost.image_wash import WashOptions, wash_all, wash_image
from fakes import make_jpeg

GPS_TAG = 0x8825
ORIENTATION_TAG = 0x0112


def _exif_with_gps_and_rotation() -> bytes:
    exif = Image.Exif()
    exif[ORIENTATION_TAG] = 6  # 90도 회전 필요
    exif[0x010F] = "PhoneMaker"
    exif[GPS_TAG] = {1: "N", 2: (37.0, 30.0, 0.0)}
    return exif.tobytes()


def test_wash_removes_exif_and_applies_rotation(tmp_path):
    src = make_jpeg(tmp_path / "src.jpg", size=(800, 400), exif=_exif_with_gps_and_rotation())
    with Image.open(src) as original:
        assert original.getexif().get(ORIENTATION_TAG) == 6

    out = wash_image(src, tmp_path / "out.jpg", random.Random(1))
    with Image.open(out) as washed:
        assert len(washed.getexif()) == 0
        assert "exif" not in washed.info
        width, height = washed.size
    assert height > width  # 세로로 회전됨


def test_wash_crops_between_one_and_two_percent(tmp_path):
    src = make_jpeg(tmp_path / "src.jpg", size=(1000, 800))
    out = wash_image(src, tmp_path / "out.jpg", random.Random(3))
    with Image.open(out) as washed:
        width, height = washed.size
    assert 980 <= width <= 990
    assert 784 <= height <= 792


def test_wash_limits_longest_side(tmp_path):
    src = make_jpeg(tmp_path / "big.jpg", size=(3000, 2000))
    out = wash_image(src, tmp_path / "out.jpg", random.Random(0), WashOptions(max_side=1200))
    with Image.open(out) as washed:
        assert max(washed.size) == 1200


def test_wash_all_is_deterministic_with_seed_and_keeps_order(tmp_path):
    sources = [make_jpeg(tmp_path / f"s{i}.png", color=(i * 40, 50, 50)) for i in range(3)]
    first = wash_all(sources, tmp_path / "a", seed=7)
    second = wash_all(sources, tmp_path / "b", seed=7)
    assert [p.name for p in first] == ["01_s0.jpg", "02_s1.jpg", "03_s2.jpg"]
    assert [p.read_bytes() for p in first] == [p.read_bytes() for p in second]


def test_wash_converts_non_rgb(tmp_path):
    src = tmp_path / "gray.png"
    Image.new("LA", (300, 300), (128, 255)).save(src)
    out = wash_image(src, tmp_path / "out.jpg", random.Random(0))
    with Image.open(out) as washed:
        assert washed.mode == "RGB"
