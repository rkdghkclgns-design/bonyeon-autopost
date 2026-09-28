import random

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


def _use(drive, ids, count, when="2026-09-29T07:00:00+09:00"):
    for file_id in ids:
        drive.record_post(file_id, count, when)


def test_fresh_photos_first_in_upload_order_then_least_used(drive_and_layout):
    drive, layout = drive_and_layout
    before = _add(drive, layout, "정기청소", "작업전", 6)
    _use(drive, before[:3], 1)  # 앞 3장은 이미 한 번 씀

    selection = select_photos(drive, layout, "정기청소", per_stage=3, min_photos=3, rng=random.Random(1))

    assert [f.id for f in selection.files_by_stage["작업전"]] == before[3:]  # 안 쓴 사진이 올린 순서대로
    assert not selection.reused and selection.fresh_count == 3


def test_all_used_photos_are_recombined_randomly(drive_and_layout):
    drive, layout = drive_and_layout
    before = _add(drive, layout, "정기청소", "작업전", 9)
    _use(drive, before, 1)

    combos = {
        tuple(f.id for f in select_photos(drive, layout, "정기청소", 3, 3, rng=random.Random(seed))
              .files_by_stage["작업전"])
        for seed in range(8)
    }
    assert len(combos) > 1  # 매번 다른 조합
    selection = select_photos(drive, layout, "정기청소", 3, 3, rng=random.Random(0))
    assert selection.reused and selection.fresh_count == 0


def test_less_used_photos_win_over_more_used(drive_and_layout):
    drive, layout = drive_and_layout
    before = _add(drive, layout, "정기청소", "작업전", 4)
    _use(drive, before[:2], 3)
    _use(drive, before[2:], 1)
    picked = select_photos(drive, layout, "정기청소", 2, 2, rng=random.Random(5)).files_by_stage["작업전"]
    assert {f.id for f in picked} == set(before[2:])


def test_category_with_new_photos_wins_else_least_recently_posted(drive_and_layout):
    drive, layout = drive_and_layout
    regular = _add(drive, layout, "정기청소", "작업후", 5)
    rope = _add(drive, layout, "로프청소", "작업후", 3)
    _use(drive, regular, 1, "2026-09-29T07:00:00+09:00")

    assert select_photos(drive, layout, "", 3, 3).category == "로프청소"  # 새 사진이 있는 카테고리 먼저

    _use(drive, rope, 1, "2026-09-29T17:00:00+09:00")
    # 둘 다 새 사진이 없으면 가장 오래전에 포스팅한 카테고리 → 번갈아 올라감
    assert select_photos(drive, layout, "", 3, 3).category == "정기청소"
