from datetime import date, datetime
from pathlib import Path

from autopost.blog_publisher import build_blog_html
from autopost.ai_helper import parse_content
from autopost.naver_crosspost import PostedLog, run_daily, todays_posts
from autopost.results import PublishResult
from autopost.token_expiry import KST
from fakes import ai_json

NOW = datetime(2026, 9, 30, 10, 30, tzinfo=KST)


class _Req:
    def __init__(self, value):
        self.value = value

    def execute(self, num_retries=0):
        return self.value


class FakeBlogger:
    def __init__(self, items):
        self.items = items

    def posts(self):
        return self

    def list(self, **kwargs):
        return _Req({"items": self.items})


class FakeNaver:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def publish_blocks(self, title, blocks, hashtags):
        self.calls.append((title, [b.kind for b in blocks], tuple(hashtags)))
        if self.fail:
            raise RuntimeError("네이버 로그인 세션이 만료되었습니다")
        return PublishResult("네이버 블로그", True, url="https://blog.naver.com/evbank/1", message="발행 완료")


def _item(post_id, published):
    content = parse_content(ai_json(), "정기청소", "본연")
    html = build_blog_html(content, {"작업후": ["https://img/a"]}, header_url="https://img/h")
    return {"id": post_id, "title": f"글 {post_id}", "url": f"https://g/{post_id}", "content": html,
            "published": published}


def _download(url, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"jpg")
    return dest


def test_todays_posts_uses_kst_date():
    blogger = FakeBlogger([
        _item("today", "2026-09-30T01:05:00Z"),      # KST 10:05
        _item("yesterday", "2026-09-29T14:00:00Z"),  # KST 09-29 23:00
        _item("late", "2026-09-30T15:30:00Z"),       # KST 10-01 00:30 → 내일
    ])
    assert [p.id for p in todays_posts(blogger, "b", date(2026, 9, 30))] == ["today"]


def test_run_daily_posts_once_and_reports(tmp_path):
    blogger = FakeBlogger([_item("p1", "2026-09-30T01:05:00Z")])
    naver = FakeNaver()
    log = PostedLog(tmp_path / "posted.json")
    notes = []

    assert run_daily(blogger, "b", naver, log, _download, tmp_path, lambda t, img: notes.append(t), NOW) == 0
    assert run_daily(blogger, "b", naver, log, _download, tmp_path, lambda t, img: notes.append(t), NOW) == 0

    assert len(naver.calls) == 1  # 두 번째 예약 실행은 이미 올린 글이라 건너뜀
    title, kinds, hashtags = naver.calls[0]
    assert title == "글 p1" and kinds[0] == "image" and "heading" in kinds and len(hashtags) == 15
    assert len(notes) == 1 and "네이버 블로그 발행 완료" in notes[0] and "https://blog.naver.com/evbank/1" in notes[0]
    assert log.done("p1")


def test_failure_is_reported_with_screenshot_and_retried_next_time(tmp_path):
    blogger = FakeBlogger([_item("p1", "2026-09-30T01:05:00Z")])
    log = PostedLog(tmp_path / "posted.json")
    shot = tmp_path / "naver_error.png"
    shot.write_bytes(b"png")
    notes = []

    failures = run_daily(blogger, "b", FakeNaver(fail=True), log, _download, tmp_path,
                         lambda t, img: notes.append((t, img)), NOW, lambda: shot)

    assert failures == 1 and not log.done("p1")  # 기록 안 함 → 다음 실행에 다시 시도
    text, image = notes[0]
    assert "네이버 블로그 발행 실패" in text and "export_naver_cookies.py" in text and image == shot


def test_nothing_to_do_without_todays_google_post(tmp_path):
    notes = []
    assert run_daily(FakeBlogger([]), "b", FakeNaver(), PostedLog(tmp_path / "p.json"), _download, tmp_path,
                     lambda t, img: notes.append(t), NOW) == 0
    assert notes == []
