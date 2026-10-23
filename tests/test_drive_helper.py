import pytest

from autopost import drive_helper
from autopost.constants import FOLDER_MIME
from autopost.drive_helper import (
    DriveHelper,
    build_query,
    escape_query_value,
    folder_url,
    public_image_url,
    public_video_embed_url,
)
from fakes import FakeDownloader, FakeDriveService


def test_escape_query_value_handles_quotes_and_backslash():
    assert escape_query_value("O'Brien") == "O\\'Brien"
    assert escape_query_value("a\\b") == "a\\\\b"


def test_build_query_combines_clauses():
    q = build_query("p1", name="사진's", mime_type=FOLDER_MIME)
    assert "'p1' in parents" in q
    assert "trashed = false" in q
    assert "name = '사진\\'s'" in q
    assert f"mimeType = '{FOLDER_MIME}'" in q
    assert "mimeType contains 'image/'" in build_query("p1", mime_prefix="image/")


def test_urls():
    assert folder_url("abc") == "https://drive.google.com/drive/folders/abc"
    assert public_image_url("xyz", 800) == "https://lh3.googleusercontent.com/d/xyz=w800"
    assert public_video_embed_url("vid") == "https://drive.google.com/file/d/vid/preview"


def test_ensure_folder_is_idempotent():
    service = FakeDriveService()
    drive = DriveHelper(service)
    first, created = drive.ensure_folder("root", "01_정기청소")
    second, created_again = drive.ensure_folder("root", "01_정기청소")
    assert created is True and created_again is False
    assert first.id == second.id
    assert first.is_folder


def test_find_child_with_apostrophe_and_folder_only():
    service = FakeDriveService()
    service.add("it's.png", "root", mime="image/png")
    drive = DriveHelper(service)
    assert drive.find_child("root", "it's.png").name == "it's.png"
    assert drive.find_child("root", "it's.png", folder_only=True) is None


def test_find_child_returns_oldest_when_duplicates():
    service = FakeDriveService()
    newer = service.add("dup", "root", created="2026-02-01T00:00:00Z")
    older = service.add("dup", "root", created="2026-01-01T00:00:00Z")
    assert DriveHelper(service).find_child("root", "dup").id == older != newer


def test_list_images_filters_non_images_and_sorts_oldest_first():
    service = FakeDriveService()
    b = service.add("b.jpg", "folder", created="2026-01-02T00:00:00Z")
    a = service.add("a.jpg", "folder", created="2026-01-01T00:00:00Z")
    service.add("memo.txt", "folder", mime="text/plain")
    service.add("other.jpg", "elsewhere")
    assert [f.id for f in DriveHelper(service).list_images("folder")] == [a, b]


def test_list_follows_pagination():
    service = FakeDriveService(page_size=2)
    for i in range(5):
        service.add(f"{i}.jpg", "folder")
    files = DriveHelper(service).list_images("folder")
    assert len(files) == 5
    assert len(service.list_calls) == 3


def test_upload_and_download(tmp_path, monkeypatch):
    monkeypatch.setattr(drive_helper, "MediaIoBaseDownload", FakeDownloader)
    service = FakeDriveService()
    drive = DriveHelper(service)
    local = tmp_path / "photo.jpg"
    local.write_bytes(b"jpeg-bytes")
    uploaded = drive.upload("root", local, name="renamed.jpg")
    assert uploaded.name == "renamed.jpg"
    assert uploaded.mime_type == "image/jpeg"

    source_id = service.add("remote.jpg", "root", content=b"remote-content")
    dest = drive.download(source_id, tmp_path / "nested" / "out.jpg")
    assert dest.read_bytes() == b"remote-content"


def test_move_replaces_parents():
    service = FakeDriveService()
    file_id = service.add("a.jpg", "old")
    DriveHelper(service).move(file_id, "new")
    assert service.files_data[file_id]["parents"] == ["new"]


def test_make_public_creates_anyone_reader_permission():
    service = FakeDriveService()
    DriveHelper(service).make_public("f1")
    assert service.permissions_created == [("f1", {"type": "anyone", "role": "reader"})]


@pytest.mark.parametrize("mime,expected", [(FOLDER_MIME, True), ("image/jpeg", False)])
def test_drive_file_is_folder(mime, expected):
    assert drive_helper.DriveFile("i", "n", mime).is_folder is expected


def test_record_post_writes_app_properties_and_list_reads_them():
    service = FakeDriveService()
    file_id = service.add("a.jpg", "folder")
    drive = DriveHelper(service)
    assert drive.list_images("folder")[0].post_count == 0

    drive.record_post(file_id, 2, "2026-09-29T07:00:00+09:00")

    assert service.files_data[file_id]["parents"] == ["folder"]  # 옮기지 않음
    listed = drive.list_images("folder")[0]
    assert listed.post_count == 2 and listed.last_posted == "2026-09-29T07:00:00+09:00"


def test_broken_post_count_is_treated_as_unused():
    service = FakeDriveService()
    file_id = service.add("a.jpg", "folder")
    service.files_data[file_id]["appProperties"] = {drive_helper.POST_COUNT_KEY: "x"}
    assert DriveHelper(service).list_images("folder")[0].post_count == 0
