"""GitHub Actions 실행 요약 페이지(Job Summary) 작성 — Actions 화면에서 결과를 한눈에 보도록."""
from __future__ import annotations

import logging
import os
from typing import Mapping, Sequence

from .ai_helper import PostContent
from .results import PublishResult

log = logging.getLogger(__name__)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def build_step_summary(
    category: str,
    area,
    content: PostContent,
    results: Sequence[PublishResult],
    outcome,
    dry_run: bool,
) -> str:
    head = "🧪 테스트 실행 (발행 안 함)" if dry_run else "🧹 포스팅 결과"
    lines = [
        f"## {head} — {category}",
        "",
        f"- **제목**: {_cell(content.title)}",
        f"- **지역**: {area.label + (' (실제 현장)' if area.is_site else ' (서비스 지역)') if area else '없음'}",
        f"- **본문**: {content.text_length():,}자 · 해시태그 {len(content.hashtags)}개",
        "",
        "| 플랫폼 | 결과 | 링크 | 메모 |",
        "|---|---|---|---|",
    ]
    for r in results:
        status = "⏭️ 건너뜀" if r.skipped else ("✅ 성공" if r.ok else "❌ 실패")
        link = f"[열기]({r.url})" if r.url else ""
        lines.append(f"| {r.platform} | {status} | {link} | {_cell(r.message)[:120]} |")
    if getattr(outcome, "url", ""):
        lines += ["", f"사용한 사진 {outcome.moved}장 → [보관 폴더]({outcome.url})"]
    lines += ["", "영상·원고·사진은 아래 **Artifacts** 와 슬랙 진행 스레드에서 확인할 수 있습니다."]
    return "\n".join(lines) + "\n"


def build_failure_summary(category: str, step_label: str, error: Exception | str) -> str:
    """도중에 멈춘 실행도 Actions 요약 페이지에서 어느 단계가 왜 실패했는지 보이도록."""
    detail = str(error).replace("```", "'''")[:1500]
    return (
        f"## ❌ 포스팅 실패 — {category}\n\n"
        f"- **실패 단계**: {step_label}\n"
        f"- 사진은 옮기지 않았으므로 다음 실행에 다시 사용됩니다.\n\n"
        f"```\n{detail}\n```\n"
    )


def write_step_summary(markdown: str, env: Mapping[str, str] | None = None) -> bool:
    path = (os.environ if env is None else env).get("GITHUB_STEP_SUMMARY", "")
    if not path:
        return False
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
        return True
    except OSError as exc:
        log.warning("실행 요약 작성 실패: %s", exc)
        return False
