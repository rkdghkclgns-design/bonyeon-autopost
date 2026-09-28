import pytest

from autopost import setup_engine, templates
from autopost.constants import (
    BGM_FILE,
    BGM_FOLDER,
    CATEGORIES,
    FOOTER_FILE,
    GUIDE_FILE,
    HEADER_FILE,
    STAGES,
)
from fakes import MemoryDrive

ROOT = "테스트루트"


@pytest.fixture
def fast_templates(monkeypatch):
    def fake(path, *args, **kwargs):
        path.write_bytes(b"template")
        return path

    for name in ("generate_header", "generate_footer", "generate_bgm", "default_bgm"):
        monkeypatch.setattr(templates, name, fake)


def test_first_run_creates_full_structure(fast_templates):
    drive = MemoryDrive()
    report = setup_engine.ensure_layout(drive, ROOT, "본연", "010-1234-5678")

    # 루트 1 + 공통 3 + 카테고리 3×(1+단계3) + 고객후기 1 + 게시이미지 1 (사용완료 폴더는 더 이상 만들지 않음)
    assert len(report.created_folders) == 1 + 3 + 3 * 4 + 1 + 1
    assert drive.path_of(report.layout.review_folder_id) == f"{ROOT}/04_고객후기"
    assert set(report.created_files) == {
        f"00_공통_헤더이미지/{HEADER_FILE}",
        f"00_공통_푸터이미지/{FOOTER_FILE}",
        f"{BGM_FOLDER}/{BGM_FILE}",
        GUIDE_FILE,
    }
    assert report.changed

    layout = report.layout
    assert drive.path_of(layout.root_id) == ROOT
    assert drive.find_child(layout.root_id, "99_사용완료_사진") is None
    for category in CATEGORIES:
        for stage in STAGES:
            folder_id = layout.stage_folders[category.name][stage]
            assert drive.path_of(folder_id) == f"{ROOT}/{category.folder}/{stage}"


def test_second_run_changes_nothing(fast_templates):
    drive = MemoryDrive()
    first = setup_engine.ensure_layout(drive, ROOT, "본연", "010")
    item_count = len(drive.items)
    second = setup_engine.ensure_layout(drive, ROOT, "본연", "010")
    assert not second.changed
    assert len(drive.items) == item_count
    assert second.layout == first.layout


def test_existing_user_files_are_not_overwritten(fast_templates):
    drive = MemoryDrive()
    setup_engine.ensure_layout(drive, ROOT, "본연", "010")
    header_folder = drive.find_child(drive.find_child("root", ROOT).id, "00_공통_헤더이미지")
    header = drive.find_child(header_folder.id, HEADER_FILE)
    drive.items[header.id]["content"] = b"user-logo"
    setup_engine.ensure_layout(drive, ROOT, "본연", "010")
    assert drive.items[header.id]["content"] == b"user-logo"


def test_skip_templates(fast_templates):
    report = setup_engine.ensure_layout(MemoryDrive(), ROOT, "본연", "010", create_templates=False)
    assert report.created_files == ()


def test_layout_is_read_only(fast_templates):
    report = setup_engine.ensure_layout(MemoryDrive(), ROOT, "본연", "010")
    with pytest.raises(TypeError):
        report.layout.stage_folders["정기청소"] = {}  # type: ignore[index]
