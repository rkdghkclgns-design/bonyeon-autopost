import pytest

from autopost import setup_engine
from autopost.photo_selector import UnknownCategoryError, resolve_category, select_photos, split_request
from fakes import MemoryDrive


@pytest.fixture
def drive_and_layout():
    drive = MemoryDrive()
    report = setup_engine.ensure_layout(drive, "루트", "본연", "010", create_templates=False)
    return drive, report.layout


def _add(drive, layout, category, stage, count):
    return [drive.add_file(layout.stage_folders[category][stage], f"{stage}{i}.jpg") for i in range(count)]


@pytest.mark.parametrize("text,expected", [
    ("", None), ("  ", None), ("로프청소", "로프청소"), ("02_로프청소", "로프청소"),
    ("로프", "로프청소"), ("방역 소독", "방역소독"),
])
def test_resolve_category(text, expected):
    assert resolve_category(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("정기청소 고잔동", ("정기청소", "고잔동")),
    ("안산 중앙동 로프", ("로프", "안산 중앙동")),
    ("고잔동", ("", "고잔동")),
    ("방역소독", ("방역소독", "")),
    ("", ("", "")),
])
def test_split_request(text, expected):
    assert split_request(text) == expected


def test_resolve_unknown_category():
    with pytest.raises(UnknownCategoryError, match="사용 가능"):
        resolve_category("입주청소")


def test_selects_category_with_most_photos_and_caps_per_stage(drive_and_layout):
    drive, layout = drive_and_layout
    _add(drive, layout, "정기청소", "작업전", 2)
    before = _add(drive, layout, "로프청소", "작업전", 5)
    _add(drive, layout, "로프청소", "작업후", 1)

    selection = select_photos(drive, layout, "", per_stage=3, min_photos=3)

    assert selection.category == "로프청소"
    assert [f.id for f in selection.files_by_stage["작업전"]] == before[:3]  # 오래된 순
    assert selection.total == 4
    assert len(selection.all_files()) == 4


def test_requested_category_below_minimum_returns_none(drive_and_layout):
    drive, layout = drive_and_layout
    _add(drive, layout, "방역소독", "작업후", 2)
    _add(drive, layout, "정기청소", "작업후", 9)
    assert select_photos(drive, layout, "방역소독", per_stage=3, min_photos=3) is None


def test_no_photos_returns_none(drive_and_layout):
    drive, layout = drive_and_layout
    assert select_photos(drive, layout, "", per_stage=3, min_photos=1) is None
