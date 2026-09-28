"""테스트용 가짜 외부 서비스 (Drive / Slack / Gemini / HTTP)."""
from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from autopost.constants import FOLDER_MIME
from autopost.drive_helper import DriveFile


def make_jpeg(path: Path, size=(640, 480), color=(120, 160, 200), exif: bytes | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, color)
    kwargs = {"exif": exif} if exif else {}
    image.save(path, "JPEG", **kwargs)
    return path


def jpeg_bytes(size=(320, 240), color=(10, 200, 90)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "JPEG")
    return buffer.getvalue()


# ------------------------------------------------------------------ Drive (DriveHelper 인터페이스)
class MemoryDrive:
    """DriveHelper 와 같은 메서드를 가진 인메모리 드라이브."""

    def __init__(self) -> None:
        self.items: dict[str, dict] = {"root": {"name": "My Drive", "mime": FOLDER_MIME, "parent": None}}
        self.public: set[str] = set()
        self._seq = 0

    def _new(self, parent: str, name: str, mime: str, content: bytes = b"") -> str:
        self._seq += 1
        file_id = f"id{self._seq}"
        self.items[file_id] = {
            "name": name, "mime": mime, "parent": parent, "content": content,
            "created": f"2026-01-01T00:00:{self._seq:02d}Z",
        }
        return file_id

    def _file(self, file_id: str) -> DriveFile:
        item = self.items[file_id]
        return DriveFile(file_id, item["name"], item["mime"], item.get("created", ""))

    # 테스트 헬퍼
    def add_file(self, parent: str, name: str, content: bytes = b"", mime: str = "image/jpeg") -> str:
        return self._new(parent, name, mime, content)

    def children(self, parent: str) -> list[DriveFile]:
        return [self._file(i) for i, item in self.items.items() if item["parent"] == parent]

    def path_of(self, file_id: str) -> str:
        parts = []
        current = file_id
        while current and current != "root":
            parts.append(self.items[current]["name"])
            current = self.items[current]["parent"]
        return "/".join(reversed(parts))

    # DriveHelper 인터페이스
    def find_child(self, parent_id: str, name: str, folder_only: bool = False) -> DriveFile | None:
        for child in self.children(parent_id):
            if child.name == name and (not folder_only or child.is_folder):
                return child
        return None

    def ensure_folder(self, parent_id: str, name: str) -> tuple[DriveFile, bool]:
        existing = self.find_child(parent_id, name, folder_only=True)
        if existing:
            return existing, False
        return self._file(self._new(parent_id, name, FOLDER_MIME)), True

    def list_images(self, folder_id: str) -> list[DriveFile]:
        images = [c for c in self.children(folder_id) if c.mime_type.startswith("image/")]
        return sorted(images, key=lambda f: f.created_time)

    def upload(self, parent_id: str, local_path: Path, name: str | None = None, mime_type: str | None = None) -> DriveFile:
        file_id = self._new(parent_id, name or local_path.name, mime_type or "application/octet-stream",
                            local_path.read_bytes())
        return self._file(file_id)

    def download(self, file_id: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.items[file_id]["content"])
        return dest

    def move(self, file_id: str, new_parent_id: str) -> None:
        self.items[file_id]["parent"] = new_parent_id

    def make_public(self, file_id: str) -> None:
        self.public.add(file_id)


# ------------------------------------------------------------------ Drive API service (googleapiclient 흉내)
class _Req:
    def __init__(self, fn):
        self._fn = fn

    def execute(self, num_retries: int = 0):
        return self._fn()


def _unescape(value: str) -> str:
    return re.sub(r"\\(.)", r"\1", value)


class FakeDriveService:
    def __init__(self, page_size: int | None = None) -> None:
        self.files_data: dict[str, dict] = {}
        self.permissions_created: list[tuple[str, dict]] = []
        self.list_calls: list[dict] = []
        self._seq = 0
        self._page_size = page_size

    def add(self, name: str, parent: str, mime: str = "image/jpeg", created: str = "", content: bytes = b"") -> str:
        self._seq += 1
        file_id = f"f{self._seq}"
        self.files_data[file_id] = {
            "id": file_id, "name": name, "mimeType": mime, "parents": [parent],
            "createdTime": created or f"2026-01-01T00:00:{self._seq:02d}Z", "content": content,
        }
        return file_id

    def _query(self, q: str) -> list[dict]:
        parent = re.search(r"'((?:[^'\\]|\\.)*)' in parents", q)
        name = re.search(r"name = '((?:[^'\\]|\\.)*)'", q)
        mime = re.search(r"mimeType = '((?:[^'\\]|\\.)*)'", q)
        prefix = re.search(r"mimeType contains '((?:[^'\\]|\\.)*)'", q)
        rows = list(self.files_data.values())
        if parent:
            rows = [r for r in rows if _unescape(parent.group(1)) in r["parents"]]
        if name:
            rows = [r for r in rows if r["name"] == _unescape(name.group(1))]
        if mime:
            rows = [r for r in rows if r["mimeType"] == _unescape(mime.group(1))]
        if prefix:
            rows = [r for r in rows if _unescape(prefix.group(1)) in r["mimeType"]]
        return rows

    def files(self):
        return _FakeFiles(self)

    def permissions(self):
        return _FakePermissions(self)


class _FakeFiles:
    def __init__(self, service: FakeDriveService) -> None:
        self.s = service

    def list(self, q, spaces=None, fields=None, pageSize=100, orderBy=None, pageToken=None):
        self.s.list_calls.append({"q": q, "orderBy": orderBy, "pageToken": pageToken})

        def run():
            rows = self.s._query(q)
            if orderBy == "createdTime":
                rows = sorted(rows, key=lambda r: r["createdTime"])
            size = self.s._page_size or len(rows) or 1
            start = int(pageToken or 0)
            page = rows[start:start + size]
            response = {"files": [{k: v for k, v in r.items() if k != "content"} for r in page]}
            if start + size < len(rows):
                response["nextPageToken"] = str(start + size)
            return response

        return _Req(run)

    def create(self, body, media_body=None, fields=None):
        def run():
            file_id = self.s.add(body["name"], body["parents"][0], body.get("mimeType", ""))
            if media_body is not None:
                self.s.files_data[file_id]["mimeType"] = media_body.mimetype()
            return {k: v for k, v in self.s.files_data[file_id].items() if k != "content"}

        return _Req(run)

    def get(self, fileId, fields=None):
        return _Req(lambda: {"parents": list(self.s.files_data[fileId]["parents"])})

    def update(self, fileId, addParents=None, removeParents=None, fields=None):
        def run():
            row = self.s.files_data[fileId]
            removed = set((removeParents or "").split(","))
            row["parents"] = [p for p in row["parents"] if p not in removed] + [addParents]
            return {"id": fileId, "parents": row["parents"]}

        return _Req(run)

    def get_media(self, fileId):
        return _MediaRequest(self.s.files_data[fileId]["content"])


@dataclass
class _MediaRequest:
    content: bytes


class FakeDownloader:
    """googleapiclient.http.MediaIoBaseDownload 대체."""

    def __init__(self, fh, request: _MediaRequest) -> None:
        self._fh = fh
        self._request = request

    def next_chunk(self, num_retries: int = 0):
        self._fh.write(self._request.content)
        return None, True


class _FakePermissions:
    def __init__(self, service: FakeDriveService) -> None:
        self.s = service

    def create(self, fileId, body, fields=None):
        def run():
            self.s.permissions_created.append((fileId, body))
            return {"id": "perm"}

        return _Req(run)


# ------------------------------------------------------------------ Slack
@dataclass
class FakeWebClient:
    messages: list[dict] = field(default_factory=list)
    uploads: list[dict] = field(default_factory=list)
    fail: bool = False

    def chat_postMessage(self, **kwargs):
        if self.fail:
            raise RuntimeError("slack down")
        self.messages.append(kwargs)

    def files_upload_v2(self, **kwargs):
        if self.fail:
            raise RuntimeError("slack down")
        self.uploads.append(kwargs)

    def texts(self) -> list[str]:
        return [m["text"] for m in self.messages]


# ------------------------------------------------------------------ Gemini
@dataclass
class FakeGeminiResponse:
    text: str


class FakeGeminiModels:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeGeminiResponse(item)


class FakeGeminiClient:
    def __init__(self, responses: list) -> None:
        self.models = FakeGeminiModels(responses)


def ai_json(stages=("작업전", "작업중", "작업후"), **overrides) -> str:
    data = {
        "title": "상가 로프청소 현장 후기",
        "intro": "안녕하세요.\n오늘은 로프청소 현장을 소개합니다.",
        "sections": [
            {"stage": s, "heading": f"{s} 모습", "body": f"{s} 설명입니다.",
             "photo_captions": [f"{s} 첫 사진 설명", f"{s} 둘째 사진 설명"]}
            for s in stages
        ],
        "tips": "간판은 6개월마다 점검하면 좋아요.",
        "outro": "상담은 000-0000-0000 으로 연락주세요.",
        "hashtags": ["로프청소", "#외벽청소", "외벽 청소", "로프청소"],
        "tiktok_caption": "깨끗해진 외벽 ✨ #로프청소",
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


# ------------------------------------------------------------------ HTTP (requests.Session 흉내)
@dataclass
class FakeResponse:
    status_code: int = 200
    payload: object = None

    def json(self):
        if self.payload is None:
            raise ValueError("no json")
        return self.payload


class FakeSession:
    """URL 별 응답 큐. 마지막 항목은 계속 반복된다. 예외 객체를 넣으면 그 예외를 발생시킨다."""

    def __init__(self, routes: dict[str, list]) -> None:
        self._routes = {k: list(v) for k, v in routes.items()}
        self.calls: list[tuple[str, str, dict]] = []

    def _next(self, method: str, url: str, kwargs: dict) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        queue = self._routes.get(url)
        if not queue:
            raise AssertionError(f"예상하지 못한 요청: {method} {url}")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def post(self, url, **kwargs):
        return self._next("POST", url, kwargs)

    def put(self, url, **kwargs):
        return self._next("PUT", url, kwargs)
