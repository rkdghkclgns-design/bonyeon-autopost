import pytest

from autopost import tiktok_publisher as tt
from fakes import FakeResponse, FakeSession

OK = {"code": "ok", "message": ""}


def _routes(status_sequence, refresh_token="rt", creator=None):
    return {
        tt.TOKEN_URL: [FakeResponse(payload={"access_token": "at", "refresh_token": refresh_token})],
        tt.CREATOR_INFO_URL: [FakeResponse(payload={"data": creator or {
            "creator_username": "bonyeon", "privacy_level_options": ["SELF_ONLY", "PUBLIC_TO_EVERYONE"]}, "error": OK})],
        tt.DIRECT_INIT_URL: [FakeResponse(payload={"data": {"publish_id": "p1", "upload_url": "https://up/1"}, "error": OK})],
        tt.INBOX_INIT_URL: [FakeResponse(payload={"data": {"publish_id": "p2", "upload_url": "https://up/1"}, "error": OK})],
        "https://up/1": [FakeResponse(status_code=201, payload={})],
        tt.STATUS_URL: [FakeResponse(payload={"data": s, "error": OK}) for s in status_sequence],
    }


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "v.mp4"
    path.write_bytes(b"0" * 1000)
    return path


def test_build_init_body_direct_and_inbox():
    direct = tt.build_init_body("direct", "캡션", "SELF_ONLY", 1000)
    assert direct["post_info"]["privacy_level"] == "SELF_ONLY"
    assert direct["source_info"] == {"source": "FILE_UPLOAD", "video_size": 1000, "chunk_size": 1000, "total_chunk_count": 1}
    assert "post_info" not in tt.build_init_body("inbox", "캡션", "SELF_ONLY", 1000)


@pytest.mark.parametrize("size", [0, tt.MAX_SINGLE_CHUNK + 1])
def test_build_init_body_rejects_bad_size(size):
    with pytest.raises(tt.TikTokError):
        tt.build_init_body("direct", "c", "SELF_ONLY", size)


def test_pick_privacy_level():
    assert tt.pick_privacy_level("PUBLIC_TO_EVERYONE", ["SELF_ONLY", "PUBLIC_TO_EVERYONE"]) == "PUBLIC_TO_EVERYONE"
    assert tt.pick_privacy_level("PUBLIC_TO_EVERYONE", ["SELF_ONLY"]) == "SELF_ONLY"
    assert tt.pick_privacy_level("PUBLIC_TO_EVERYONE", ["FOLLOWER_OF_CREATOR"]) == "FOLLOWER_OF_CREATOR"
    assert tt.pick_privacy_level("SELF_ONLY", []) == "SELF_ONLY"


def test_direct_publish_polls_until_complete(video):
    session = FakeSession(_routes([
        {"status": "PROCESSING_UPLOAD"},
        {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": ["7400000000000000000"]},
    ]))
    sleeps = []
    publisher = tt.TikTokPublisher("k", "s", "rt", "direct", "PUBLIC_TO_EVERYONE", session=session, sleep=sleeps.append)

    result = publisher.publish(video, "깨끗 ✨")

    assert result.ok
    assert result.url == "https://www.tiktok.com/@bonyeon/video/7400000000000000000"
    assert "PUBLIC_TO_EVERYONE" in result.message
    assert sleeps == [tt.POLL_INTERVAL]
    put = next(c for c in session.calls if c[0] == "PUT")
    assert put[2]["headers"]["Content-Range"] == "bytes 0-999/1000"
    init = next(c for c in session.calls if c[1] == tt.DIRECT_INIT_URL)
    assert init[2]["headers"]["Authorization"] == "Bearer at"
    assert init[2]["json"]["post_info"]["title"] == "깨끗 ✨"


def test_inbox_mode_skips_creator_info(video):
    session = FakeSession(_routes([{"status": "SEND_TO_USER_INBOX"}]))
    result = tt.TikTokPublisher("k", "s", "rt", "inbox", session=session, sleep=lambda _: None).publish(video, "c")
    assert result.ok and result.url == ""
    assert "받은편지함" in result.message
    assert all(c[1] != tt.CREATOR_INFO_URL for c in session.calls)


def test_token_rotation_saved_before_upload(video):
    saved = []
    session = FakeSession(_routes([{"status": "FAILED", "fail_reason": "spam_risk"}], refresh_token="new-rt"))
    publisher = tt.TikTokPublisher(
        "k", "s", "rt", "direct", session=session, sleep=lambda _: None,
        on_token_rotated=lambda value: saved.append(value) or True,
    )
    with pytest.raises(tt.TikTokError, match="spam_risk"):
        publisher.publish(video, "c")
    assert saved == ["new-rt"]  # 업로드가 실패해도 새 토큰은 이미 저장됨


def test_rotation_note_when_not_saved(video):
    session = FakeSession(_routes([{"status": "PUBLISH_COMPLETE"}], refresh_token="new-rt"))
    result = tt.TikTokPublisher("k", "s", "rt", session=session, sleep=lambda _: None).publish(video, "c")
    assert "저장하지 못했습니다" in result.message


def test_refresh_error_is_reported():
    session = FakeSession({tt.TOKEN_URL: [FakeResponse(status_code=400, payload={
        "error": "invalid_grant", "error_description": "expired"})]})
    with pytest.raises(tt.TikTokError, match="invalid_grant"):
        tt.TikTokPublisher("k", "s", "rt", session=session).refresh()


def test_api_error_code_is_reported(video):
    routes = _routes([])
    routes[tt.DIRECT_INIT_URL] = [FakeResponse(payload={"error": {"code": "spam_risk_too_many_posts", "message": "slow"}})]
    publisher = tt.TikTokPublisher("k", "s", "rt", session=FakeSession(routes), sleep=lambda _: None)
    with pytest.raises(tt.TikTokError, match="spam_risk_too_many_posts"):
        publisher.publish(video, "c")


def test_non_json_response_after_retries():
    sleeps = []
    session = FakeSession({tt.TOKEN_URL: [FakeResponse(status_code=502, payload=None)]})
    with pytest.raises(tt.TikTokError, match="HTTP 502"):
        tt.TikTokPublisher("k", "s", "rt", session=session, sleep=sleeps.append).refresh()
    assert len(session.calls) == tt.HTTP_MAX_ATTEMPTS
    assert sleeps == [2, 4]


def test_transient_network_error_is_retried():
    import requests

    session = FakeSession({tt.TOKEN_URL: [
        requests.ConnectionError("reset"),
        FakeResponse(status_code=503, payload={}),
        FakeResponse(payload={"access_token": "at", "refresh_token": "rt"}),
    ]})
    token = tt.TikTokPublisher("k", "s", "rt", session=session, sleep=lambda _: None).refresh()
    assert token.access_token == "at"
    assert len(session.calls) == 3


def test_persistent_network_error_does_not_leak_details():
    import requests

    session = FakeSession({tt.TOKEN_URL: [requests.ConnectionError("https://x?client_secret=s")]})
    with pytest.raises(tt.TikTokError) as info:
        tt.TikTokPublisher("k", "s", "rt", session=session, sleep=lambda _: None).refresh()
    assert "client_secret" not in str(info.value)


def test_direct_request_routed_to_inbox_is_not_reported_as_published(video):
    session = FakeSession(_routes([{"status": "SEND_TO_USER_INBOX"}]))
    result = tt.TikTokPublisher("k", "s", "rt", "direct", session=session, sleep=lambda _: None).publish(video, "c")
    assert result.ok
    assert "아직 게시되지 않음" in result.message
    assert "게시 완료" not in result.message


def test_polling_timeout(video, monkeypatch):
    monkeypatch.setattr(tt, "POLL_MAX_TRIES", 2)
    session = FakeSession(_routes([{"status": "PROCESSING_UPLOAD"}]))
    with pytest.raises(tt.TikTokError, match="시간 초과"):
        tt.TikTokPublisher("k", "s", "rt", session=session, sleep=lambda _: None).publish(video, "c")


def test_upload_http_error(video):
    routes = _routes([])
    routes["https://up/1"] = [FakeResponse(status_code=500, payload={})]
    with pytest.raises(tt.TikTokError, match="업로드 실패"):
        tt.TikTokPublisher("k", "s", "rt", session=FakeSession(routes), sleep=lambda _: None).publish(video, "c")
