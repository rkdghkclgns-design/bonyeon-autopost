"""틱톡 Content Posting API 업로드.

- direct: 바로 게시 (앱 심사(audit) 전에는 SELF_ONLY=나만보기 로만 게시 가능)
- inbox : 틱톡 앱 받은편지함으로 초안 전송 → 사용자가 앱에서 최종 게시
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from .results import PublishResult

log = logging.getLogger(__name__)

PLATFORM = "틱톡"
API_BASE = "https://open.tiktokapis.com/v2"
TOKEN_URL = f"{API_BASE}/oauth/token/"
CREATOR_INFO_URL = f"{API_BASE}/post/publish/creator_info/query/"
DIRECT_INIT_URL = f"{API_BASE}/post/publish/video/init/"
INBOX_INIT_URL = f"{API_BASE}/post/publish/inbox/video/init/"
STATUS_URL = f"{API_BASE}/post/publish/status/fetch/"

MAX_SINGLE_CHUNK = 64 * 1024 * 1024
HTTP_TIMEOUT = 60
POLL_INTERVAL = 5.0
POLL_MAX_TRIES = 36
HTTP_MAX_ATTEMPTS = 3
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
STATUS_PUBLISHED = "PUBLISH_COMPLETE"
STATUS_INBOX = "SEND_TO_USER_INBOX"


class TikTokError(RuntimeError):
    pass


@dataclass(frozen=True)
class TikTokToken:
    access_token: str
    refresh_token: str
    refresh_expires_in: int = 0  # refresh token 남은 유효기간(초) — 만료 알림용


def _check(response: requests.Response, action: str) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise TikTokError(f"{action}: JSON 이 아닌 응답 (HTTP {response.status_code})") from exc
    error = payload.get("error")
    if isinstance(error, dict) and error.get("code") not in (None, "ok"):
        raise TikTokError(f"{action}: {error.get('code')} - {error.get('message')}")
    if isinstance(error, str):
        raise TikTokError(f"{action}: {error} - {payload.get('error_description', '')}")
    if response.status_code >= 400:
        raise TikTokError(f"{action}: HTTP {response.status_code}")
    return payload


def build_init_body(mode: str, caption: str, privacy_level: str, video_size: int) -> dict:
    if video_size <= 0:
        raise TikTokError("영상 파일이 비어 있습니다")
    if video_size > MAX_SINGLE_CHUNK:
        raise TikTokError("영상이 64MB 를 넘습니다. VIDEO_SECONDS 를 줄여주세요")
    source_info = {
        "source": "FILE_UPLOAD",
        "video_size": video_size,
        "chunk_size": video_size,
        "total_chunk_count": 1,
    }
    if mode == "inbox":
        return {"source_info": source_info}
    return {
        "post_info": {
            "title": caption,
            "privacy_level": privacy_level,
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
            "video_cover_timestamp_ms": 1000,
        },
        "source_info": source_info,
    }


def pick_privacy_level(requested: str, options: list[str]) -> str:
    if not options or requested in options:
        return requested
    fallback = "SELF_ONLY" if "SELF_ONLY" in options else options[0]
    log.warning("틱톡 계정이 %s 공개범위를 허용하지 않아 %s 로 게시합니다", requested, fallback)
    return fallback


class TikTokPublisher:
    def __init__(
        self,
        client_key: str,
        client_secret: str,
        refresh_token: str,
        mode: str = "direct",
        privacy_level: str = "SELF_ONLY",
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        on_token_rotated: Callable[[str], bool] | None = None,
        on_refresh_expiry: Callable[[str], bool] | None = None,
    ) -> None:
        self._client_key = client_key
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._mode = mode
        self._privacy_level = privacy_level
        self._http = session or requests.Session()
        self._sleep = sleep
        self._on_token_rotated = on_token_rotated
        self._on_refresh_expiry = on_refresh_expiry

    def _handle_rotation(self, token: TikTokToken) -> str:
        """refresh token 이 바뀌면 업로드 전에 즉시 저장(콜백)하고 안내 문구를 반환."""
        if token.refresh_token == self._refresh_token:
            return ""
        saved = bool(self._on_token_rotated and self._on_token_rotated(token.refresh_token))
        if saved:
            return "틱톡 refresh token 갱신 → GitHub 시크릿 자동 업데이트 완료"
        return (
            "⚠️ 틱톡 refresh token 이 갱신되었지만 저장하지 못했습니다. "
            "다음 실행이 실패하면 scripts/get_tiktok_token.py 로 재발급하세요"
        )

    def _send(self, method: str, url: str, **kwargs) -> requests.Response:
        """네트워크 오류·429·5xx 는 지수 백오프로 재시도."""
        for attempt in range(1, HTTP_MAX_ATTEMPTS + 1):
            try:
                response = getattr(self._http, method)(url, **kwargs)
            except requests.RequestException as exc:
                if attempt == HTTP_MAX_ATTEMPTS:
                    raise TikTokError(f"네트워크 오류: {type(exc).__name__}") from exc
            else:
                if response.status_code not in RETRYABLE_STATUS or attempt == HTTP_MAX_ATTEMPTS:
                    return response
            log.warning("틱톡 요청 재시도 (%d/%d)", attempt, HTTP_MAX_ATTEMPTS)
            self._sleep(2 ** attempt)
        raise TikTokError("unreachable")  # pragma: no cover

    def refresh(self) -> TikTokToken:
        response = self._send(
            "post",
            TOKEN_URL,
            data={
                "client_key": self._client_key,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=HTTP_TIMEOUT,
        )
        payload = _check(response, "토큰 갱신")
        if "access_token" not in payload:
            raise TikTokError("토큰 갱신 응답에 access_token 이 없습니다")
        try:
            expires_in = int(payload.get("refresh_expires_in") or 0)
        except (TypeError, ValueError):
            expires_in = 0
        return TikTokToken(payload["access_token"], payload.get("refresh_token", self._refresh_token), expires_in)

    def _save_expiry(self, token: TikTokToken) -> None:
        """refresh token 만료일을 저장 (토큰 만료 알림용). 실패해도 업로드는 계속."""
        if not (self._on_refresh_expiry and token.refresh_expires_in > 0):
            return
        from .token_expiry import expiry_from_seconds

        try:
            self._on_refresh_expiry(expiry_from_seconds(token.refresh_expires_in))
        except Exception:
            log.exception("틱톡 토큰 만료일 저장 실패")

    def _post_json(self, url: str, token: str, body: dict, action: str) -> dict:
        response = self._send(
            "post",
            url,
            json=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
            timeout=HTTP_TIMEOUT,
        )
        return _check(response, action).get("data", {})

    def _wait_for_status(self, token: str, publish_id: str) -> dict:
        # 심사 전 앱은 direct 로 요청해도 받은편지함으로만 전달될 수 있어 둘 다 종료 상태로 본다
        data: dict = {}
        for _ in range(POLL_MAX_TRIES):
            data = self._post_json(STATUS_URL, token, {"publish_id": publish_id}, "상태 조회")
            status = data.get("status", "")
            if status in (STATUS_PUBLISHED, STATUS_INBOX):
                return data
            if status == "FAILED":
                raise TikTokError(f"틱톡 처리 실패: {data.get('fail_reason', '알 수 없음')}")
            self._sleep(POLL_INTERVAL)
        raise TikTokError(f"틱톡 처리 대기 시간 초과 (마지막 상태: {data.get('status', '없음')})")

    def publish(self, video_path: Path, caption: str) -> PublishResult:
        token = self.refresh()
        rotation_note = self._handle_rotation(token)
        self._save_expiry(token)
        if rotation_note:
            log.warning(rotation_note)
        size = video_path.stat().st_size
        username = ""
        privacy = self._privacy_level
        if self._mode == "direct":
            creator = self._post_json(CREATOR_INFO_URL, token.access_token, {}, "크리에이터 정보 조회")
            username = creator.get("creator_username", "")
            privacy = pick_privacy_level(privacy, creator.get("privacy_level_options") or [])

        init_url = INBOX_INIT_URL if self._mode == "inbox" else DIRECT_INIT_URL
        init = self._post_json(
            init_url, token.access_token, build_init_body(self._mode, caption, privacy, size), "업로드 초기화"
        )
        upload = self._send(
            "put",
            init["upload_url"],
            data=video_path.read_bytes(),
            headers={
                "Content-Type": "video/mp4",
                "Content-Range": f"bytes 0-{size - 1}/{size}",
                "Content-Length": str(size),
            },
            timeout=300,
        )
        if upload.status_code >= 400:
            raise TikTokError(f"영상 업로드 실패: HTTP {upload.status_code}")

        status = self._wait_for_status(token.access_token, init["publish_id"])
        post_ids = status.get("publicaly_available_post_id") or []
        url = f"https://www.tiktok.com/@{username}/video/{post_ids[0]}" if post_ids and username else ""
        notes = [
            f"게시 완료 (공개범위: {privacy})" if status.get("status") == STATUS_PUBLISHED
            else "⚠️ 아직 게시되지 않음 — 틱톡 앱 받은편지함(알림)에서 최종 게시하세요"
        ]
        if rotation_note:
            notes.append(rotation_note)
        return PublishResult(platform=PLATFORM, ok=True, url=url, message=" / ".join(notes))
