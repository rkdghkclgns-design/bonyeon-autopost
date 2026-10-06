import pytest
from PIL import Image, ImageDraw

from autopost.before_after import GAP, MAX_WIDTH, make_comparison, make_contact_sheet, make_vertical_comparison
from fakes import make_jpeg


def test_vertical_comparison_stacks_before_over_after(tmp_path):
    before = make_jpeg(tmp_path / "b.jpg", size=(4000, 1800), color=(120, 90, 60))
    after = make_jpeg(tmp_path / "a.jpg", size=(4000, 1800), color=(235, 235, 235))
    out = make_vertical_comparison(before, after, tmp_path / "v.jpg", size=(1080, 1460), gap=16)
    with Image.open(out) as image:
        assert image.size == (1080, 1460)
        top, bottom = image.getpixel((540, 600)), image.getpixel((540, 1300))
        assert sum(top) < sum(bottom)  # 위 = 작업 전(어두움), 아래 = 작업 후(밝음)


def test_contact_sheet_has_one_row_per_stage(tmp_path):
    photos = {
        "작업전": [make_jpeg(tmp_path / f"b{i}.jpg", size=(800, 600)) for i in range(3)],
        "작업중": [],
        "작업후": [make_jpeg(tmp_path / "a.jpg", size=(600, 800))],
    }
    out = make_contact_sheet(photos, tmp_path / "out" / "sheet.jpg", thumb=100)
    with Image.open(out) as image:
        assert image.size == (150 + 3 * (100 + 8) + 8, 2 * (100 + 8) + 8)  # 빈 단계는 줄에서 제외


def test_contact_sheet_without_photos_returns_none(tmp_path):
    assert make_contact_sheet({"작업전": []}, tmp_path / "sheet.jpg") is None
    assert not (tmp_path / "sheet.jpg").exists()


@pytest.mark.parametrize("before_size,after_size", [
    ((800, 600), (600, 800)),
    ((600, 800), (800, 600)),
    ((4000, 1000), (500, 2000)),
    ((800, 600), (1600, 1200)),
])
def test_side_by_side_panels_have_equal_size(tmp_path, before_size, after_size):
    before = make_jpeg(tmp_path / "b.jpg", size=before_size, color=(120, 90, 60))
    after = make_jpeg(tmp_path / "a.jpg", size=after_size, color=(230, 230, 230))
    out = make_comparison(before, after, tmp_path / "out" / "cmp.jpg", height=400)
    with Image.open(out) as image:
        assert image.size == (400 * 2 + GAP, 400)
        # 왼쪽은 작업 전(어두운 색), 오른쪽은 작업 후(밝은 색) — 라벨 아래 영역에서 확인
        assert sum(image.getpixel((50, 350))) < sum(image.getpixel((image.width - 50, 350)))


def test_comparison_crops_from_center_without_stretching(tmp_path):
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    for path, size in ((before, (800, 400)), (after, (400, 800))):
        photo = Image.new("RGB", size, "red")
        x, y = size[0] // 2, size[1] // 2
        ImageDraw.Draw(photo).rectangle((x - 40, y - 40, x + 39, y + 39), fill="blue")
        photo.save(path)
    out = make_comparison(before, after, tmp_path / "cmp.jpg", height=400)
    with Image.open(out) as image:
        for offset in (0, 400 + GAP):
            pixels = [(x, y) for y in range(150, 250) for x in range(150, 250)
                      if image.getpixel((offset + x, y))[2] > 150]
            xs, ys = zip(*pixels)
            assert max(xs) - min(xs) + 1 == 80
            assert max(ys) - min(ys) + 1 == 80
            assert (min(xs), min(ys)) == (160, 160)


def test_wide_result_is_scaled_down(tmp_path):
    before = make_jpeg(tmp_path / "b.jpg", size=(2000, 500))
    after = make_jpeg(tmp_path / "a.jpg", size=(2000, 500))
    out = make_comparison(before, after, tmp_path / "cmp.jpg", height=900)
    with Image.open(out) as image:
        assert image.width == MAX_WIDTH
