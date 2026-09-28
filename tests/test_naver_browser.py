"""NaverPublisher 의 Playwright 조작 흐름을 로컬 가짜 에디터로 검증.

실제 네이버 셀렉터 검증이 아니라 '팝업 닫기 → 제목 → 본문/사진 → 태그 → 발행 → URL 추출
→ 세션 저장' 로직이 의도대로 동작하는지 확인한다. Chromium 이 없으면 건너뛴다.
"""
import base64
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from autopost.ai_helper import parse_content
from autopost.naver_publisher import NaverPublisher, NaverSessionExpired, decode_storage_state
from fakes import ai_json, make_jpeg

FAKE_DIR = Path(__file__).parent / "naver_fake"
EMPTY_STATE = base64.b64encode(json.dumps({"cookies": [], "origins": []}).encode()).decode()


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            playwright.chromium.launch().close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _chromium_available(), reason="Playwright Chromium 미설치")


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    handler = functools.partial(_QuietHandler, directory=str(FAKE_DIR))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _local_storage(encoded_state: str, key: str) -> dict:
    state = decode_storage_state(encoded_state)
    for origin in state["origins"]:
        for item in origin.get("localStorage", []):
            if item["name"] == key:
                return json.loads(item["value"])
    raise AssertionError(f"localStorage '{key}' 없음")


def test_publish_flow(server, tmp_path):
    saved_sessions = []
    publisher = NaverPublisher(
        "myblog", EMPTY_STATE, "publish", tmp_path,
        on_session_updated=lambda value: saved_sessions.append(value) or True,
        write_url=server + "/index.html?blog={blog_id}",
    )
    content = parse_content(ai_json(), "로프청소", "본연")
    images = {"작업전": [make_jpeg(tmp_path / "before.jpg")], "작업후": [make_jpeg(tmp_path / "after.jpg")]}

    result = publisher.publish(content, images, header=make_jpeg(tmp_path / "header.jpg"))

    assert result.ok
    assert result.url == "https://blog.naver.com/myblog/223456789012"
    summary = _local_storage(saved_sessions[0], "summary")
    assert summary["title"] == content.title
    assert summary["images"] == ["header.jpg", "before.jpg", "after.jpg"]
    assert "“ 작업전 모습 ”" in summary["body"]
    assert "작업후 첫 사진 설명" in summary["body"]
    assert "상담은 000-0000-0000" in summary["body"]
    assert summary["tags"] == [tag.lstrip("#") for tag in content.hashtags]


def test_draft_mode_saves_without_publishing(server, tmp_path):
    saved_sessions = []
    publisher = NaverPublisher(
        "myblog", EMPTY_STATE, "draft", tmp_path,
        on_session_updated=lambda value: saved_sessions.append(value) or True,
        write_url=server + "/index.html",
    )
    content = parse_content(ai_json(stages=("작업후",)), "로프청소", "본연")
    result = publisher.publish(content, {"작업후": [make_jpeg(tmp_path / "a.jpg")]})
    assert result.ok and result.url == ""
    assert "임시저장" in result.message
    assert _local_storage(saved_sessions[0], "saved")["title"] == content.title


def test_unconfirmed_publish_is_soft_success_to_avoid_duplicates(server, tmp_path):
    publisher = NaverPublisher(
        "myblog", EMPTY_STATE, "publish", tmp_path,
        write_url=server + "/index_noredirect.html", confirm_timeout_s=1.0,
    )
    content = parse_content(ai_json(stages=("작업후",)), "로프청소", "본연")
    result = publisher.publish(content, {"작업후": [make_jpeg(tmp_path / "a.jpg")]})
    assert result.ok
    assert result.url == "https://blog.naver.com/myblog"
    assert "확인하지 못했습니다" in result.message
    assert list(tmp_path.glob("naver_unconfirmed_*.png"))


def test_expired_session_raises_and_saves_screenshot(server, tmp_path):
    publisher = NaverPublisher("myblog", EMPTY_STATE, "publish", tmp_path, write_url=server + "/nidlogin.html")
    content = parse_content(ai_json(), "로프청소", "본연")
    with pytest.raises(NaverSessionExpired):
        publisher.publish(content, {})
    assert list(tmp_path.glob("naver_error_*.png"))
