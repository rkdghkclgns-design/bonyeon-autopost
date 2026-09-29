"""내 PC 예약 작업: 오늘 구글 블로그에 올라간 글을 네이버 블로그에 똑같이 올린다.

네이버는 접속 위치가 바뀌면(미국 GitHub 서버 ↔ 한국 PC) 로그인을 끊기 때문에, 네이버 발행은
항상 이 PC(한국 IP)에서만 한다. PC가 꺼진 날은 실행되지 않으므로 구글 글만 올라간다.
이미 올린 구글 글은 기록해 두어 같은 날 여러 번 실행돼도 한 번만 올린다.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlparse

from .blogger_import import to_blocks
from .results import PublishResult
from .token_expiry import KST

log = logging.getLogger(__name__)

PLATFORM = "네이버 블로그"


@dataclass(frozen=True)
class GooglePost:
    id: str
    title: str
    url: str
    html: str
    published: str


def _to_post(item: Mapping) -> GooglePost:
    return GooglePost(item["id"], item.get("title", ""), item.get("url", ""), item.get("content", ""),
                      item.get("published", ""))


def fetch_post_by_url(blogger, blog_id: str, url: str) -> GooglePost:
    item = blogger.posts().getByPath(blogId=blog_id, path=urlparse(url).path).execute(num_retries=3)
    return _to_post(item)


def todays_posts(blogger, blog_id: str, today: date) -> list[GooglePost]:
    """오늘(KST) 발행된 구글 글, 오래된 것부터."""
    response = blogger.posts().list(
        blogId=blog_id, maxResults=5, orderBy="PUBLISHED", status="LIVE", fetchBodies=True,
    ).execute(num_retries=3)
    posts = []
    for item in response.get("items", []):
        try:
            published = datetime.fromisoformat(item.get("published", "").replace("Z", "+00:00")).astimezone(KST).date()
        except ValueError:
            continue
        if published == today:
            posts.append(_to_post(item))
    return sorted(posts, key=lambda p: p.published)


class PostedLog:
    """네이버에 이미 올린 구글 글 기록 (output/naver_crossposted.json)."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _load(self) -> dict:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def done(self, post_id: str) -> bool:
        return post_id in self._load()

    def record(self, post: GooglePost, naver_url: str, now: datetime) -> None:
        data = self._load()
        data[post.id] = {"title": post.title, "google": post.url, "naver": naver_url,
                         "at": now.isoformat(timespec="seconds")}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def crosspost(post: GooglePost, workdir: Path, download: Callable[[str, Path], Path], publisher) -> PublishResult:
    blocks, hashtags = to_blocks(post.html, workdir, download)
    return publisher.publish_blocks(post.title, blocks, hashtags)


def run_daily(
    blogger,
    blog_id: str,
    publisher,
    posted: PostedLog,
    download: Callable[[str, Path], Path],
    workdir: Path,
    notify: Callable[[str, Path | None], None],
    now: datetime,
    screenshot_since: Callable[[], Path | None] = lambda: None,
) -> int:
    """오늘 구글 글 중 아직 네이버에 안 올린 글을 올리고 슬랙에 보고. 반환: 실패 수."""
    pending = [p for p in todays_posts(blogger, blog_id, now.date()) if not posted.done(p.id)]
    if not pending:
        log.info("오늘 네이버에 올릴 새 구글 글이 없습니다")
        return 0
    failures = 0
    for index, post in enumerate(pending):
        try:
            result = crosspost(post, workdir / f"{index:02d}", download, publisher)
        except Exception as exc:  # 로그인 만료·화면 변경 등 — 다음 예약 실행에 다시 시도
            log.exception("네이버 발행 실패: %s", post.title)
            result = PublishResult.fail(PLATFORM, str(exc)[:300])
        if result.ok:
            posted.record(post, result.url, now)
            notify(f"📗 네이버 블로그 발행 완료 (구글 글과 동일)\n*{post.title}*\n{result.url}\n{result.message}", None)
        else:
            failures += 1
            notify(
                f"❌ 네이버 블로그 발행 실패 — *{post.title}*\n{result.message}\n"
                "로그인이 끊겼으면 PC에서 `python scripts/export_naver_cookies.py` 로 다시 로그인하세요 "
                "(다음 예약 실행에 자동으로 다시 시도합니다).",
                screenshot_since(),
            )
    return failures

