from pathlib import Path

import pytest

from autopost.results import PublishResult
from autopost.slack_helper import (
    SlackNotifier,
    build_report_blocks,
    build_setup_blocks,
    escape_mrkdwn,
    redact,
)
from fakes import FakeWebClient


@pytest.mark.parametrize("raw,expected", [
    ("key AIza" + "X" * 32 + " failed", "key *** failed"),  # 테스트용 가짜 값 (실제 키 형식과 길이가 다름)
    ("https://x.googleapis.com/v1/models?key=abcdEFG123&alt=json", "https://x.googleapis.com/v1/models?key=***&alt=json"),
    ("Authorization: Bearer eyJhbGciOi.xyz", "Authorization: Bearer ***"),
    ("token xoxb-111-222-abc leaked", "token *** leaked"),
    ("pat github_pat_11ABCDEF_xyz", "pat ***"),
    ("nothing secret here", "nothing secret here"),
])
def test_redact_patterns(raw, expected):
    assert redact(raw) == expected


def test_redact_known_values_and_ignores_short_ones():
    assert redact("refresh=my-refresh-token-value!", ["my-refresh-token-value"]) == "refresh=***!"
    assert redact("abc", ["abc"]) == "abc"  # 너무 짧은 값은 오탐 방지로 무시


def test_escape_mrkdwn_blocks_mentions_and_fence_breaks():
    assert escape_mrkdwn("```<!channel> & <http://evil|click>") == "'''&lt;!channel&gt; &amp; &lt;http://evil|click&gt;"


def test_notifier_redacts_text_blocks_and_comments(tmp_path):
    client = FakeWebClient()
    slack = SlackNotifier(channel_id="C1", client=client, secrets=["super-secret-gemini-key"])
    slack.post("err super-secret-gemini-key", [{"type": "section", "text": {"type": "mrkdwn", "text": "x super-secret-gemini-key"}}])
    slack.notify_error("AI", RuntimeError("bad key super-secret-gemini-key ```<!channel>"))
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    slack.upload_file(video, "t", "caption super-secret-gemini-key")

    dumped = str(client.messages) + str(client.uploads)
    assert "super-secret-gemini-key" not in dumped
    assert client.messages[0]["blocks"][0]["text"]["text"] == "x ***"
    assert "<!channel>" not in client.messages[1]["text"]
    assert client.messages[1]["text"].count("```") == 2


def test_report_blocks_list_record_failures():
    blocks = build_report_blocks("정기청소", "t", [PublishResult("x", True)], used_count=2, record_failures=["a.jpg", "<b>.jpg"])
    text = "\n".join(b.get("text", {}).get("text", "") for b in blocks)
    assert "사진 2장 사용 기록 실패" in text
    assert "a.jpg, &lt;b&gt;.jpg" in text


def test_report_blocks_show_status_and_links():
    results = [
        PublishResult("구글 블로그", True, url="https://b/1", message="발행 완료"),
        PublishResult("네이버 블로그", False, message="세션 만료"),
        PublishResult.skip("틱톡", "미설정"),
    ]
    blocks = build_report_blocks("로프청소", "제목", results, used_count=6)
    texts = [b.get("text", {}).get("text", "") for b in blocks]
    joined = "\n".join(texts)
    assert blocks[0]["text"]["text"].startswith("🧹")
    assert "✅ *구글 블로그*  <https://b/1|게시글 열기>" in joined
    assert "❌ *네이버 블로그*\n세션 만료" in joined
    assert "⏭️ *틱톡*" in joined
    footer = blocks[-1]["elements"][0]["text"]
    assert "사용한 사진 6장" in footer and "폴더에 그대로" in footer and "99_사용완료" not in footer


def test_report_blocks_dry_run_and_truncation():
    long_message = "가" * 5000
    blocks = build_report_blocks("정기청소", "t", [PublishResult("x", False, message=long_message)], dry_run=True)
    assert "테스트" in blocks[0]["text"]["text"]
    assert all(len(b.get("text", {}).get("text", "")) <= 2900 for b in blocks)
    assert "사진 사용 기록 없음" in blocks[-1]["elements"][0]["text"]


def test_setup_blocks():
    changed = build_setup_blocks(["루트/폴더"], ["헤더.png"], [("슬랙", True, ""), ("틱톡", False, "TIKTOK_*")], "https://d")
    text = "\n".join(b.get("text", {}).get("text", "") for b in changed)
    assert "📁 루트/폴더" in text and "📄 헤더.png" in text
    assert "⬜ 틱톡  _(필요: TIKTOK_*)_" in text
    unchanged = build_setup_blocks([], [], [], "https://d")
    assert "변경 없음" in unchanged[1]["text"]["text"]


def test_notifier_posts_with_bot_client(tmp_path):
    client = FakeWebClient()
    slack = SlackNotifier(channel_id="C1", client=client)
    assert slack.enabled and slack.can_thread
    ts = slack.post("시작")
    slack.notify_error("테스트", ValueError("boom"))
    assert ts == "1700000000.000001"
    assert client.messages[0]["channel"] == "C1"
    assert client.messages[0]["thread_ts"] is None
    assert "boom" in client.messages[1]["text"]

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    assert slack.upload_file(video, "영상", "코멘트", thread_ts=ts) is True
    assert client.uploads[0]["channel"] == "C1"
    assert client.uploads[0]["thread_ts"] == ts


def test_notifier_threads_and_updates_messages():
    client = FakeWebClient()
    slack = SlackNotifier(channel_id="C1", client=client, secrets=["hidden-value-123"])
    ts = slack.post("부모")
    slack.post("답글", thread_ts=ts)
    assert slack.update(ts, "수정됨 hidden-value-123", [{"type": "divider"}]) is True
    assert client.thread(ts)[0]["text"] == "답글"
    assert client.updates[0] == {"channel": "C1", "ts": ts, "text": "수정됨 ***", "blocks": [{"type": "divider"}]}
    assert slack.update("", "x") is False  # ts 없으면 수정 불가


def test_update_failure_and_webhook_only_update_are_not_raised():
    failing = SlackNotifier(channel_id="C1", client=FakeWebClient(fail_update=True))
    assert failing.update("1.2", "x") is False

    class Hook:
        def send(self, **kwargs):
            return None

    webhook_only = SlackNotifier(webhook=Hook())
    assert not webhook_only.can_thread
    assert webhook_only.post("x") is None  # 웹훅은 ts 를 돌려주지 않음
    assert webhook_only.update("1.2", "x") is False


def test_notifier_never_raises_on_slack_failure(tmp_path):
    slack = SlackNotifier(channel_id="C1", client=FakeWebClient(fail=True))
    assert slack.post("hello") is None  # 예외가 전파되지 않아야 함
    assert slack.upload_file(tmp_path / "x.mp4", "t") is False


def test_bot_failure_falls_back_to_webhook():
    class Hook:
        def __init__(self):
            self.sent = []

        def send(self, **kwargs):
            self.sent.append(kwargs)

    hook = Hook()
    healthy = FakeWebClient()
    SlackNotifier(channel_id="C1", client=healthy, webhook=hook).post("봇 정상")
    assert healthy.messages and hook.sent == []  # 봇이 되면 웹훅은 안 씀

    SlackNotifier(channel_id="C1", client=FakeWebClient(fail=True), webhook=hook).post("봇 장애")
    assert hook.sent[-1]["text"] == "봇 장애"


def test_webhook_http_error_is_logged_not_raised(caplog):
    class BadHook:
        def send(self, **kwargs):
            return type("R", (), {"status_code": 404})()

    SlackNotifier(webhook=BadHook()).post("x")
    assert "HTTP 404" in caplog.text


def test_notifier_webhook_and_disabled():
    class Hook:
        def __init__(self):
            self.sent = []

        def send(self, **kwargs):
            self.sent.append(kwargs)

    hook = Hook()
    slack = SlackNotifier(webhook=hook)
    slack.post("hi", [{"type": "divider"}])
    assert hook.sent == [{"text": "hi", "blocks": [{"type": "divider"}]}]
    assert slack.upload_file(Path("v.mp4"), "t") is False  # 웹훅만으로는 파일 업로드 불가

    disabled = SlackNotifier()
    assert not disabled.enabled
    disabled.post("로그만 남음")
