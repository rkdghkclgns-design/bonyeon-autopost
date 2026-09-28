"""슬랙 진행 상황 보고 — 메시지 1개의 체크리스트를 단계마다 갱신하고, 결과물은 그 스레드에 올린다.

    🧹 정기청소 포스팅 진행 중
    카테고리·지역·트리거·요청자
    ✅ 사진 선택 — 5장 (작업전 3 · 작업중 1 · 작업후 1)
    ⏳ AI 원고 작성
    ⬜ 틱톡 영상 제작 …
    실행 로그 보기 (GitHub Actions)
      └ 스레드: 선택된 사진 / 전후 비교 / 원고 / 영상 / 발행 결과

봇 토큰이 없거나(웹훅만) 첫 메시지 전송이 실패하면 수정할 메시지가 없으므로 완료·실패 단계만 새 메시지로 보낸다.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Mapping, Sequence

from .slack_helper import SlackNotifier, escape_mrkdwn

log = logging.getLogger(__name__)

STEPS: tuple[tuple[str, str], ...] = (
    ("select", "사진 선택"),
    ("prepare", "사진 정리·전후 비교"),
    ("draft", "AI 원고 작성"),
    ("video", "틱톡 영상 제작"),
    ("publish", "블로그·틱톡 발행"),
    ("usage", "사진 사용 기록"),
)
STEP_LABELS = dict(STEPS)
ICONS = {"wait": "⬜", "run": "⏳", "done": "✅", "fail": "❌", "skip": "⏭️"}


def build_progress_blocks(
    headline: str,
    meta: Sequence[str],
    states: Mapping[str, tuple[str, str]],
    run_url: str = "",
) -> list[dict]:
    lines = []
    for key, label in STEPS:
        status, detail = states.get(key, ("wait", ""))
        line = f"{ICONS[status]} {label}" if status != "run" else f"{ICONS[status]} *{label}* 진행 중…"
        if detail:
            line += f" — {escape_mrkdwn(detail)}"
        lines.append(line)
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": headline[:150]}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": " · ".join(meta) or " "}]},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
    ]
    footer = "결과물(사진·원고·영상·발행 링크)은 이 메시지의 스레드에 올라갑니다"
    if run_url:
        footer += f"  |  <{run_url}|실행 로그 보기>"
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": footer}]})
    return blocks


STAGE_OUTPUT_LABELS = {
    "prepare": "📸 사진·전후 비교",
    "draft": "📝 원고",
    "video": "🎬 틱톡 영상",
    "publish": "📊 발행 결과",
}


class ProgressReporter:
    """진행 메시지(체크리스트)는 알림 채널에, 단계 결과물은 단계별 채널(없으면 진행 메시지 스레드)에 올린다."""

    def __init__(
        self,
        slack: SlackNotifier,
        headline: str,
        meta: Sequence[str],
        run_url: str = "",
        stage_channels: Mapping[str, str] | None = None,
        run_label: str = "",
    ) -> None:
        self._slack = slack
        self._headline = headline
        self._meta = tuple(meta)
        self._run_url = run_url
        self._stage_channels = dict(stage_channels or {})
        self._run_label = run_label
        self._pointed: set[str] = set()
        self._states: dict[str, tuple[str, str]] = {key: ("wait", "") for key, _ in STEPS}
        self._ts: str | None = None

    @property
    def thread_ts(self) -> str | None:
        return self._ts

    def _failing_step(self) -> str:
        """오류가 난 단계 = 진행 중인 단계, 없으면 아직 시작 안 한 첫 단계."""
        for wanted in ("run", "wait"):
            for key, _ in STEPS:
                if self._states[key][0] == wanted:
                    return key
        return STEPS[-1][0]

    def _blocks(self) -> list[dict]:
        return build_progress_blocks(self._headline, self._meta, self._states, self._run_url)

    def start(self) -> None:
        # 봇 전송이 실패(웹훅 대체 포함)하면 ts 가 없으므로 이후에는 새 메시지로 한 줄씩만 보낸다
        # — ts 없이 매번 체크리스트 전체를 새로 올려 채널에 여러 개가 쌓이는 것을 막는다.
        self._ts = self._slack.post(self._headline, self._blocks())

    def step(self, key: str, status: str, detail: str = "") -> None:
        self._states = {**self._states, key: (status, detail)}
        if self._ts:
            self._slack.update(self._ts, self._headline, self._blocks())
        elif status in ("done", "fail"):  # 수정할 메시지가 없으면(웹훅만 등) 끝난 단계만 한 줄씩
            self._slack.post(f"{ICONS[status]} {STEP_LABELS[key]}" + (f" — {detail}" if detail else ""))

    def fail_current(self, error: Exception | str) -> str:
        """진행 중이던 단계를 실패로 표시하고 오류 내용을 스레드에 남긴다. 실패한 단계 이름을 돌려준다."""
        key = self._failing_step()
        self.step(key, "fail", str(error)[:120])
        self.finish(f"❌ {self._headline.split(' ', 1)[-1].replace('진행 중', '실패')}")
        self.note(f"🚨 '{STEP_LABELS[key]}' 단계 오류\n```{escape_mrkdwn(str(error)[:1500])}```")
        return STEP_LABELS[key]

    def finish(self, headline: str) -> None:
        self._headline = headline
        if self._ts:
            self._slack.update(self._ts, self._headline, self._blocks())

    def _stage_channel(self, stage: str | None) -> str | None:
        """단계별 채널 — 봇 토큰이 있을 때만 (웹훅은 채널을 바꿀 수 없음)."""
        return self._stage_channels.get(stage or "") if self._slack.can_thread else None

    def _tagged(self, text: str) -> str:
        """단계별 채널에서 어느 실행의 결과물인지 알 수 있게 실행 표시를 붙인다."""
        return f"[{self._run_label}] {text}" if self._run_label else text

    def _point(self, stage: str, channel: str) -> None:
        """진행 메시지 스레드에 '결과물은 #채널 에' 안내 (단계마다 한 번)."""
        if stage in self._pointed:
            return
        self._pointed.add(stage)
        self._slack.post(f"{STAGE_OUTPUT_LABELS.get(stage, stage)} → <#{channel}>", thread_ts=self._ts)

    def note(self, text: str, blocks: list[dict] | None = None, stage: str | None = None) -> None:
        channel = self._stage_channel(stage)
        if channel is None:
            self._slack.post(text, blocks, thread_ts=self._ts)
            return
        if blocks and self._run_label:  # 블록 메시지는 맨 위에 실행 표시 줄을 넣는다
            blocks = [{"type": "context", "elements": [{"type": "mrkdwn", "text": f"🧹 {self._run_label}"}]},
                      *blocks]
        self._slack.post(self._tagged(text), blocks, channel=channel)
        self._point(stage, channel)

    def file(self, path: Path | None, title: str, comment: str = "", stage: str | None = None) -> None:
        if path is None or not path.is_file():
            return
        channel = self._stage_channel(stage)
        if channel is None:
            self._slack.upload_file(path, title, comment, thread_ts=self._ts)
            return
        self._slack.upload_file(path, title, self._tagged(comment), channel=channel)
        self._point(stage, channel)
