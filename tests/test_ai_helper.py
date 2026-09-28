import pytest

from autopost.ai_helper import (
    HASHTAG_COUNT,
    MOBILE_LINE,
    min_body_chars,
    split_sentences,
    wrap_mobile,
    ContentGenerationError,
    ContentGenerator,
    build_prompt,
    normalize_hashtags,
    parse_content,
)
from autopost.regions import AreaPick
from fakes import FakeGeminiClient, ai_json, make_jpeg


def test_normalize_hashtags_prefix_dedupe_and_exact_count():
    tags = normalize_hashtags(["로프청소", "#로프청소", "외벽 청소", "!!", "LoveClean", "loveclean"], "로프청소", "본연 청소")
    assert len(tags) == HASHTAG_COUNT
    assert tags[:3] == ("#로프청소", "#외벽청소", "#LoveClean")
    assert "#본연청소" in tags
    assert len({t.lower() for t in tags}) == HASHTAG_COUNT
    assert all(t.startswith("#") and " " not in t for t in tags)


def test_normalize_hashtags_truncates_long_tags():
    tags = normalize_hashtags(["가" * 50], "정기청소", "본연")
    assert tags[0] == "#" + "가" * 30


def test_parse_content_full():
    content = parse_content(ai_json(), "로프청소", "본연")
    assert content.title == "상가 로프청소 현장 후기"
    assert [s.stage for s in content.sections] == ["작업전", "작업중", "작업후"]
    assert len(content.hashtags) == HASHTAG_COUNT
    assert content.section_for("작업중").heading == "작업중 모습"
    assert content.section_for("없는단계") is None


def test_parse_content_accepts_code_fence_and_filters_stages():
    raw = f"```json\n{ai_json()}\n```"
    content = parse_content(raw, "로프청소", "본연", stages_present=["작업후"])
    assert [s.stage for s in content.sections] == ["작업후"]


@pytest.mark.parametrize("raw", [
    "not json",
    "[1, 2]",
    ai_json(title=""),
    ai_json(tiktok_caption=None),
    ai_json(sections=[]),
])
def test_parse_content_rejects_bad_responses(raw):
    with pytest.raises(ContentGenerationError):
        parse_content(raw, "로프청소", "본연")


def test_plain_text_contains_all_parts():
    text = parse_content(ai_json(), "로프청소", "본연").plain_text()
    assert text.startswith("상가 로프청소 현장 후기")
    assert "■ 작업후 모습" in text
    assert "[작업 후 사진 2]\n작업후 둘째 사진 설명" in text
    assert "#로프청소" in text


def test_captions_are_fitted_to_photo_counts():
    counts = {"작업전": 3, "작업중": 1, "작업후": 0}
    content = parse_content(ai_json(), "로프청소", "본연", ["작업전", "작업중"], counts)
    before = content.section_for("작업전")
    assert before.captions == ("작업전 첫 사진 설명", "작업전 둘째 사진 설명", "")  # 부족분은 빈 설명
    assert content.section_for("작업중").captions == ("작업중 첫 사진 설명",)  # 초과분은 버림
    assert before.caption_for(5) == ""


def test_each_sentence_becomes_its_own_paragraph():
    text = "안녕하세요! 본연클린입니다. 오늘 현장을 소개할게요"
    assert wrap_mobile(text) == "안녕하세요!\n\n본연클린입니다.\n\n오늘 현장을 소개할게요"


def test_long_sentence_is_wrapped_inside_its_paragraph():
    long_line = "두껍게 자라있던 이끼와 찌든 침전물을 말끔히 제거하여 배선 주변과 바닥판이 하얗게 제 모습을 되찾았습니다. 조명도 밝아졌어요."
    wrapped = wrap_mobile(long_line)
    first, second = wrapped.split("\n\n")
    assert len(first.split("\n")) >= 2
    assert all(len(line) <= MOBILE_LINE + 4 for line in first.split("\n"))
    assert second == "조명도 밝아졌어요."
    assert "".join(wrapped.split()) == "".join(long_line.split())  # 글자 손실 없음


def test_ai_mid_sentence_breaks_are_rejoined():
    ai_text = "싱크대 상판 위로 커피잔,\n유리컵이 놓여 있습니다.\n세척을 시작했습니다"
    assert wrap_mobile(ai_text) == "싱크대 상판 위로 커피잔, 유리컵이 놓여 있습니다.\n\n세척을 시작했습니다"


def test_standalone_lines_and_blank_lines_are_boundaries():
    assert wrap_mobile("상담 도와드립니다\n문의: 010-2740-1734") == "상담 도와드립니다\n\n문의: 010-2740-1734"
    assert wrap_mobile("짧은 줄\n\n둘째 문단") == "짧은 줄\n\n둘째 문단"
    assert split_sentences("") == []


def test_balanced_wrap_of_long_sentence():
    lengths = [len(line) for line in wrap_mobile(("가나다라 " * 14).strip()).split("\n")]
    assert max(lengths) - min(lengths) <= 6  # 고르게 나뉨


def test_tips_heading_line_is_removed():
    raw = ai_json(tips="정기청소 관리 TIP\n컵은 바로 헹구세요.\n주 1회 전문 청소를 권장합니다.")
    content = parse_content(raw, "정기청소", "본연", area=AreaPick("안산", "상록구", "본오동"))
    assert content.tips == "컵은 바로 헹구세요.\n\n주 1회 전문 청소를 권장합니다."
    assert "■ 안산 상록구 정기청소 관리 TIP" in content.plain_text()


def test_parse_content_wraps_captions_and_paragraphs():
    raw = ai_json(intro="가" * 10 + " " + "나" * 10 + " " + "다" * 10 + " " + "라" * 10)
    content = parse_content(raw, "로프청소", "본연")
    assert "\n" in content.intro


def test_missing_captions_are_tolerated():
    raw = ai_json(sections=[{"stage": "작업후", "heading": "h", "body": "b", "photo_captions": "not-a-list"}])
    content = parse_content(raw, "로프청소", "본연", ["작업후"], {"작업후": 2})
    assert content.section_for("작업후").captions == ("", "")


def test_build_prompt_contains_format_rules_and_plan():
    prompt = build_prompt("본연클린", "010-1111-2222", "방역소독", {"작업전": 2, "작업중": 0, "작업후": 3})
    assert "010-1111-2222" in prompt
    assert "작업전 사진 2장, 작업후 사진 3장" in prompt
    assert "작업중" not in prompt.split("sections 는 이 순서와 사진 수로만 작성하세요:")[1]
    assert "안녕하세요! 방역·소독 전문 본연클린입니다." in prompt
    assert "고객 후기처럼 쓰지 않고" in prompt
    assert "친환경·무독성" in prompt
    assert "사진 번호·촬영 언급 없이" in prompt
    assert "지역명은 쓰지 않습니다" in prompt
    assert "[방역소독]" in prompt


COVERAGE = AreaPick("안산", "단원구", "고잔동")
SITE = AreaPick("안산", "단원구", "고잔동", is_site=True)


def test_prompt_coverage_area_never_claims_site_location():
    prompt = build_prompt("본연클린", "010", "로프청소", {"작업후": 1}, area=COVERAGE)
    assert "| 안산 단원구 로프청소 본연클린" in prompt
    assert "현장이 고잔동에 있었다고 쓰지 마세요" in prompt
    assert "고잔동 등 안산 단원구 전 지역 출장·상담 가능" in prompt
    assert "1,400~2,600자" in prompt and '"tips"' in prompt


def test_prompt_site_area_uses_actual_location():
    prompt = build_prompt("본연클린", "010", "정기청소", {"작업후": 1}, area=SITE)
    assert "[고잔동 정기청소]" in prompt
    assert "실제로 '안산 단원구 고잔동'에 있습니다" in prompt
    assert "안산 단원구 전 지역 출장·상담 가능" in prompt


def test_area_hashtags_and_keyword():
    content = parse_content(ai_json(), "로프청소", "본연", area=COVERAGE)
    assert content.hashtags[:3] == ("#고잔동로프청소", "#고잔동청소", "#단원구청소업체")
    assert len(content.hashtags) == HASHTAG_COUNT
    assert content.keyword == "안산 단원구 로프청소"
    assert parse_content(ai_json(), "로프청소", "본연", area=SITE).keyword == "고잔동 로프청소"
    plain = parse_content(ai_json(), "로프청소", "본연")
    assert plain.hashtags[0] == "#로프청소" and plain.keyword == ""


def test_tips_and_text_length():
    content = parse_content(ai_json(), "로프청소", "본연")
    assert content.tips == "간판은 6개월마다 점검하면 좋아요."
    assert "■ 관리 TIP" in content.plain_text()
    assert content.text_length() > len("간판은6개월마다점검하면좋아요.")
    assert parse_content(ai_json(tips=None), "로프청소", "본연").tips == ""


def test_min_body_chars_scales_with_photos():
    assert min_body_chars({"작업전": 3, "작업후": 5}) == 400 + 60 * 8


def _long_json(stage="작업후", times=40):
    return ai_json(stages=(stage,), tips="깨끗하게 관리하는 방법입니다. " * times)


def test_short_answer_triggers_one_expansion_request(tmp_path):
    image = make_jpeg(tmp_path / "a.jpg")
    client = FakeGeminiClient([ai_json(stages=("작업후",)), _long_json()])
    content = ContentGenerator("key", "m", "본연", "010", client=client).generate("정기청소", {"작업후": [image]})
    assert content.text_length() >= min_body_chars({"작업후": 1})
    second_prompt = client.models.calls[1]["contents"][-1]
    assert "너무 짧았습니다" in second_prompt


def test_still_short_after_expansion_returns_longer_version(tmp_path):
    image = make_jpeg(tmp_path / "a.jpg")
    short, slightly_longer = ai_json(stages=("작업후",)), _long_json(times=2)
    client = FakeGeminiClient([short, slightly_longer])
    content = ContentGenerator("key", "m", "본연", "010", client=client).generate("정기청소", {"작업후": [image]})
    assert "깨끗하게 관리하는 방법입니다" in content.tips
    assert len(client.models.calls) == 2  # 늘려 달라는 재요청은 1회만


def test_generator_passes_area_to_prompt_and_tags(tmp_path):
    image = make_jpeg(tmp_path / "a.jpg")
    client = FakeGeminiClient([_long_json()])
    generator = ContentGenerator("key", "m", "본연", "010", client=client)
    content = generator.generate("정기청소", {"작업후": [image]}, area=AreaPick("서울", "강남구", "역삼동"))
    assert "| 서울 강남구 정기청소 본연" in client.models.calls[0]["contents"][-1]
    assert content.hashtags[0] == "#역삼동정기청소"


def test_generator_retries_then_succeeds(tmp_path):
    image = make_jpeg(tmp_path / "a.jpg")
    client = FakeGeminiClient([RuntimeError("quota"), "not json", ai_json(stages=("작업전",))])
    sleeps = []
    generator = ContentGenerator("key", "gemini-test", "본연", "010", client=client, sleep=sleeps.append)

    content = generator.generate("로프청소", {"작업전": [image]})

    assert [s.stage for s in content.sections] == ["작업전"]
    assert sleeps == [2, 4]
    call = client.models.calls[-1]
    assert call["model"] == "gemini-test"
    assert call["contents"][0] == "[작업 전 사진 1]"
    assert call["config"].response_mime_type == "application/json"


def test_generator_falls_back_to_next_model_without_waiting(tmp_path):
    image = make_jpeg(tmp_path / "a.jpg")
    client = FakeGeminiClient([RuntimeError("503 UNAVAILABLE"), _long_json("작업전")])
    sleeps = []
    generator = ContentGenerator(
        "key", "gemini-flash-latest", "본연", "010", client=client, sleep=sleeps.append,
        fallback_models=["gemini-3.8-flash", "gemini-flash-latest"],  # 중복은 제거됨
    )
    content = generator.generate("로프청소", {"작업전": [image]})
    assert content.title
    assert [c["model"] for c in client.models.calls] == ["gemini-flash-latest", "gemini-3.8-flash"]
    assert sleeps == []


def test_generator_counts_all_model_attempts(tmp_path):
    image = make_jpeg(tmp_path / "a.jpg")
    client = FakeGeminiClient([RuntimeError("503")] * 6)
    generator = ContentGenerator("key", "a", "본연", "010", client=client, sleep=lambda _: None,
                                 fallback_models=["b"])
    with pytest.raises(ContentGenerationError, match="6회"):
        generator.generate("로프청소", {"작업후": [image]})
    assert [c["model"] for c in client.models.calls] == ["a", "b"] * 3


def test_generator_gives_up_after_max_attempts(tmp_path):
    image = make_jpeg(tmp_path / "a.jpg")
    client = FakeGeminiClient([RuntimeError("x")] * 3)
    generator = ContentGenerator("key", "m", "본연", "010", client=client, sleep=lambda _: None)
    with pytest.raises(ContentGenerationError, match="3회"):
        generator.generate("로프청소", {"작업후": [image]})
