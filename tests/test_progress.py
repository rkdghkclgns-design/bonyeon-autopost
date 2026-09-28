from autopost.progress import STEPS, ProgressReporter, build_progress_blocks
from autopost.slack_helper import SlackNotifier
from fakes import FakeWebClient


def _lines(blocks):
    return blocks[2]["text"]["text"].splitlines()


def test_blocks_render_every_step_with_status_and_escaped_detail():
    states = {"select": ("done", "5장"), "prepare": ("run", ""), "draft": ("fail", "<!channel> 오류")}
    blocks = build_progress_blocks("🧹 헤드라인", ["카테고리 *정기청소*", "수동 실행"], states)
    lines = _lines(blocks)
    assert len(lines) == len(STEPS)
    assert lines[0] == "✅ 사진 선택 — 5장"
    assert lines[1] == "⏳ *사진 정리·전후 비교* 진행 중…"
    assert lines[2] == "❌ AI 원고 작성 — &lt;!channel&gt; 오류"
    assert lines[3] == "⬜ 틱톡 영상 제작"
    assert blocks[0]["text"]["text"] == "🧹 헤드라인"
    assert blocks[1]["elements"][0]["text"] == "카테고리 *정기청소* · 수동 실행"
    assert "실행 로그" not in blocks[-1]["elements"][0]["text"]


def test_blocks_link_run_url_and_cap_header_length():
    blocks = build_progress_blocks("가" * 200, [], {}, run_url="https://gh/run/1")
    assert len(blocks[0]["text"]["text"]) == 150
    assert "<https://gh/run/1|실행 로그 보기>" in blocks[-1]["elements"][0]["text"]
    assert blocks[1]["elements"][0]["text"] == " "  # 빈 메타도 슬랙이 거부하지 않도록


def test_reporter_updates_one_message_and_threads_outputs(tmp_path):
    client = FakeWebClient()
    reporter = ProgressReporter(SlackNotifier(channel_id="C1", client=client), "🧹 진행 중", ["meta"])
    reporter.start()
    reporter.step("select", "done", "3장")
    reporter.step("prepare", "run")
    image = tmp_path / "a.jpg"
    image.write_bytes(b"x")
    reporter.file(image, "사진", "코멘트")
    reporter.file(None, "없음")  # 없는 결과물은 조용히 건너뜀
    reporter.file(tmp_path / "missing.jpg", "없음")
    reporter.note("스레드 메모")
    reporter.finish("✅ 완료")

    ts = reporter.thread_ts
    assert ts == "1700000000.000001"
    assert [m for m in client.messages if m.get("thread_ts") is None] == [client.messages[0]]
    assert len(client.updates) == 3  # 단계 2번 + 완료 1번
    assert client.last_text(ts) == "✅ 완료"
    assert [u["title"] for u in client.thread_uploads(ts)] == ["사진"]
    assert client.thread(ts)[0]["text"] == "스레드 메모"


def test_fail_current_marks_running_step_and_posts_error():
    client = FakeWebClient()
    reporter = ProgressReporter(SlackNotifier(channel_id="C1", client=client), "🧹 정기청소 포스팅 진행 중", [])
    reporter.start()
    reporter.step("select", "done")
    reporter.step("prepare", "done")
    reporter.step("draft", "run")
    reporter.fail_current(RuntimeError("boom ```"))

    ts = reporter.thread_ts
    assert client.last_text(ts) == "❌ 정기청소 포스팅 실패"
    lines = _lines(client.last_blocks(ts))
    assert lines[2] == "❌ AI 원고 작성 — boom '''"
    error_note = client.thread(ts)[-1]["text"]
    assert "'AI 원고 작성' 단계 오류" in error_note and error_note.count("```") == 2


def test_fail_current_between_steps_blames_next_pending_step():
    client = FakeWebClient()
    reporter = ProgressReporter(SlackNotifier(channel_id="C1", client=client), "🧹 진행 중", [])
    reporter.start()
    reporter.step("select", "done")
    reporter.fail_current("drive 500")
    assert _lines(client.last_blocks(reporter.thread_ts))[1].startswith("❌ 사진 정리·전후 비교")


def test_fail_current_after_all_steps_uses_last_step():
    client = FakeWebClient()
    reporter = ProgressReporter(SlackNotifier(channel_id="C1", client=client), "🧹 진행 중", [])
    reporter.start()
    for key, _ in STEPS:
        reporter.step(key, "done")
    reporter.fail_current("late")
    assert _lines(client.last_blocks(reporter.thread_ts))[-1] == "❌ 사용 사진 보관 — late"


def test_webhook_only_reporter_posts_finished_steps_only():
    class Hook:
        def __init__(self):
            self.sent = []

        def send(self, **kwargs):
            self.sent.append(kwargs["text"])

    hook = Hook()
    reporter = ProgressReporter(SlackNotifier(webhook=hook), "🧹 진행 중", [])
    reporter.start()
    reporter.step("select", "run")
    reporter.step("select", "done", "3장")
    reporter.step("draft", "skip")
    reporter.step("video", "fail", "ffmpeg")
    reporter.finish("✅ 완료")  # 웹훅은 수정 불가 → 아무것도 보내지 않음
    assert hook.sent == ["🧹 진행 중", "✅ 사진 선택 — 3장", "❌ 틱톡 영상 제작 — ffmpeg"]
    assert reporter.thread_ts is None


def test_first_post_failure_switches_to_line_mode_instead_of_reposting_checklist():
    class FlakyClient(FakeWebClient):
        def chat_postMessage(self, **kwargs):
            if not self.messages and not getattr(self, "failed_once", False):
                self.failed_once = True
                raise RuntimeError("network blip")
            return super().chat_postMessage(**kwargs)

    client = FlakyClient()
    reporter = ProgressReporter(SlackNotifier(channel_id="C1", client=client), "🧹 진행 중", [])
    reporter.start()
    reporter.step("select", "run")
    reporter.step("select", "done", "3장")
    reporter.finish("✅ 완료")
    assert reporter.thread_ts is None
    assert client.texts() == ["✅ 사진 선택 — 3장"]  # 체크리스트를 매번 새로 올리지 않음
    assert client.updates == []
    assert reporter.fail_current("x") == "사진 정리·전후 비교"


def test_slack_update_failure_does_not_break_reporting():
    client = FakeWebClient(fail_update=True)
    reporter = ProgressReporter(SlackNotifier(channel_id="C1", client=client), "🧹 진행 중", [])
    reporter.start()
    reporter.step("select", "done")  # chat_update 가 실패해도 예외 없이 계속
    reporter.note("메모")
    assert client.thread(reporter.thread_ts)[0]["text"] == "메모"
