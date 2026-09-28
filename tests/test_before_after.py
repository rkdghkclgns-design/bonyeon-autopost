from PIL import Image

from autopost.before_after import GAP, MAX_WIDTH, make_comparison, make_contact_sheet
from fakes import make_jpeg


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


def test_side_by_side_same_height(tmp_path):
    before = make_jpeg(tmp_path / "b.jpg", size=(800, 600), color=(120, 90, 60))
    after = make_jpeg(tmp_path / "a.jpg", size=(600, 800), color=(230, 230, 230))
    out = make_comparison(before, after, tmp_path / "out" / "cmp.jpg", height=400)
    with Image.open(out) as image:
        assert image.height == 400
        assert image.width == round(800 * 400 / 600) + GAP + round(600 * 400 / 800)
        # 왼쪽은 작업 전(어두운 색), 오른쪽은 작업 후(밝은 색) — 라벨 아래 영역에서 확인
        assert sum(image.getpixel((50, 350))) < sum(image.getpixel((image.width - 50, 350)))


def test_wide_result_is_scaled_down(tmp_path):
    before = make_jpeg(tmp_path / "b.jpg", size=(2000, 500))
    after = make_jpeg(tmp_path / "a.jpg", size=(2000, 500))
    out = make_comparison(before, after, tmp_path / "cmp.jpg", height=900)
    with Image.open(out) as image:
        assert image.width == MAX_WIDTH
