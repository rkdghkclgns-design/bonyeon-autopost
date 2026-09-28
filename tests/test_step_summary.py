from autopost.ai_helper import parse_content
from autopost.pipeline import ArchiveOutcome
from autopost.regions import AreaPick
from autopost.results import PublishResult
from autopost.step_summary import build_failure_summary, build_step_summary, write_step_summary
from fakes import ai_json


def _content():
    return parse_content(ai_json(title="제목 | 파이프"), "로프청소", "본연")


def test_summary_table_escapes_pipes_and_lists_results():
    results = [
        PublishResult("구글 블로그", True, url="https://b/1"),
        PublishResult("네이버 블로그", False, message="세션\n만료 | 재로그인"),
        PublishResult.skip("틱톡", "미설정"),
    ]
    area = AreaPick("안산", "단원구", "고잔동", is_site=True)
    text = build_step_summary("로프청소", area, _content(), results, ArchiveOutcome("https://drive/x", 5), False)
    assert text.startswith("## 🧹 포스팅 결과 — 로프청소")
    assert "- **제목**: 제목 \\| 파이프" in text
    assert "(실제 현장)" in text
    assert "| 구글 블로그 | ✅ 성공 | [열기](https://b/1) |  |" in text
    assert "| 네이버 블로그 | ❌ 실패 |  | 세션 만료 \\| 재로그인 |" in text
    assert "| 틱톡 | ⏭️ 건너뜀 |" in text
    assert "사용한 사진 5장 → [보관 폴더](https://drive/x)" in text


def test_dry_run_summary_without_area_or_archive():
    text = build_step_summary("정기청소", None, _content(), [], ArchiveOutcome(), True)
    assert "🧪 테스트 실행" in text
    assert "- **지역**: 없음" in text
    assert "보관 폴더" not in text


def test_failure_summary_names_step_and_keeps_code_fence_closed():
    text = build_failure_summary("정기청소", "AI 원고 작성", RuntimeError("boom ``` injected"))
    assert text.startswith("## ❌ 포스팅 실패 — 정기청소")
    assert "- **실패 단계**: AI 원고 작성" in text
    assert text.count("```") == 2 and "boom ''' injected" in text


def test_write_summary_appends_only_when_env_set(tmp_path):
    target = tmp_path / "summary.md"
    assert write_step_summary("a", {"GITHUB_STEP_SUMMARY": str(target)}) is True
    assert write_step_summary("b", {"GITHUB_STEP_SUMMARY": str(target)}) is True
    assert target.read_text(encoding="utf-8") == "a\nb\n"
    assert write_step_summary("c", {}) is False
    assert write_step_summary("d", {"GITHUB_STEP_SUMMARY": str(tmp_path / "no" / "dir.md")}) is False
