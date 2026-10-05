"""Gemini Vision으로 블로그 원고·해시태그 15개·틱톡 캡션 생성.

원고 양식은 네이버 청소업체 '현장 기록' 글의 공통 구조를 따른다:
인사 + 현장 소개 → 단계별 인용구 소제목 → 사진마다 1~3줄 설명(글·사진 교차)
→ 전후 비교 → 맺음말 + 상담 안내. 업체가 직접 쓰는 1인칭이며, 고객 후기처럼 쓰지 않는다.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .constants import CATEGORY_DESCRIPTIONS, SERVICE_AREA, SERVICE_AREA_LINE, STAGE_LABELS, STAGES
from .editorial import normalize_text
from .regions import AreaPick

log = logging.getLogger(__name__)

HASHTAG_COUNT = 15
MAX_HASHTAG_LEN = 30
MIN_CHARS_BASE = 600  # 본문 최소 분량 = 기본 + 사진당 가산 (공백 제외) — 사진 5장이면 1,100자
MIN_CHARS_PER_PHOTO = 100
MOBILE_LINE = 24  # 네이버 모바일 글처럼 한 줄 24자 안팎
MOBILE_SLACK = 6  # 문장이 30자 이하면 한 줄로 둔다
RETRY_WAIT_SECONDS = 15  # 모든 모델이 실패한 라운드 뒤 대기 (라운드마다 늘어남)
MIN_LAST_LINE = 8  # 마지막 줄이 이보다 짧으면('있습니다.' 만 남는 등) 앞줄에 붙인다
# 자연스럽게 줄을 끊을 수 있는 어절 끝 (쉼표·연결어미·부사격 조사)
NATURAL_BREAK = re.compile(r"(,|고|며|서|면|지만|는데|도록|으로|에서|처럼|까지|부터|하여|해서|되어|하게|위해|해|아|어|여)$")
# 억지로 끊어야 할 때 차선책: 조사로 끝나는 어절 뒤 ('바닥 자동 / 세정기' 처럼 명사 사이를 끊지 않도록)
PHRASE_END = re.compile(r"(을|를|은|는|이|가|에|의|도|와|과|로|라|나)$")
# '유지해 / 드리고' 처럼 보조동사 앞에서는 끊지 않는다
AUXILIARY = re.compile(r"^(드리|드립|드려|드렸|주|줍|줘|줬|보|봅|봤|있|놓|두|버리|버렸|냈|내|낸)")
SENTENCE_END = re.compile(r"([.!?…~)]|[.!?][\"'”’]|[다요죠])$")  # 줄 끝이 문장 끝인지
STANDALONE_LINE = re.compile(r"[:：]|\d{2,4}-\d{3,4}-\d{4}$")  # '문의: 010-…' 처럼 홀로 쓰는 줄
TIKTOK_CAPTION_MAX = 2000
GENERIC_TAGS = (
    "청소업체", "청소전문", "청소현장", "전후비교", "깨끗한공간",
    "청소대행", "상가청소", "상업시설관리", "청소서비스", "위생관리",
    "청소꿀팁", "공간관리", "전문청소", "청소견적", "청결",
)


class ContentGenerationError(RuntimeError):
    """AI 원고 생성 실패."""


@dataclass(frozen=True)
class Section:
    stage: str
    heading: str
    body: str
    captions: tuple[str, ...] = ()

    def caption_for(self, index: int) -> str:
        return self.captions[index] if index < len(self.captions) else ""


@dataclass(frozen=True)
class PostContent:
    title: str
    intro: str
    sections: tuple[Section, ...]
    outro: str
    hashtags: tuple[str, ...]
    tiktok_caption: str
    tips: str = ""
    keyword: str = ""  # 대표 검색어 (예: '안산 단원구 정기청소') — TIP 소제목 등에 사용

    def section_for(self, stage: str) -> Section | None:
        return next((s for s in self.sections if s.stage == stage), None)

    def plain_text(self) -> str:
        """네이버 수동 발행/슬랙 초안용 일반 텍스트 (사진 위치는 [사진 N] 으로 표시)."""
        parts = [self.title, "", self.intro, ""]
        for section in self.sections:
            parts.extend([f"■ {section.heading}", section.body, ""])
            for index, caption in enumerate(section.captions, start=1):
                parts.extend([f"[{STAGE_LABELS[section.stage]} 사진 {index}]", caption, ""])
        if self.tips:
            parts.extend([f"■ {self.keyword + ' ' if self.keyword else ''}관리 TIP", self.tips, ""])
        parts.extend([self.outro, "", " ".join(self.hashtags)])
        return "\n".join(parts).strip()

    def text_length(self) -> int:
        """본문 글자 수 (공백·해시태그 제외) — 분량 점검용."""
        texts = [self.intro, self.tips, self.outro]
        for section in self.sections:
            texts.extend([section.heading, section.body, *section.captions])
        return sum(len(re.sub(r"\s", "", t)) for t in texts)


def min_body_chars(photo_counts: Mapping[str, int]) -> int:
    """사진 수에 비례한 본문 최소 글자 수 (공백 제외)."""
    return MIN_CHARS_BASE + MIN_CHARS_PER_PHOTO * sum(photo_counts.values())


def area_rules(
    area: AreaPick | None, category: str, company: str, headline: str = "○○ 현장, ○○까지 깔끔하게"
) -> tuple[str, str]:
    """(제목 예시, 지역 규칙) — 실제 현장 위치와 '서비스 지역 키워드'를 구분해 거짓 위치를 쓰지 않게 한다."""
    service = f"outro 에 '{SERVICE_AREA_LINE}' 한 줄을 그대로 넣습니다."
    if area is None:
        return f"[{category}] {headline}", f"지역명은 쓰지 않습니다. {service}"
    if area.is_site:
        place = area.dong or area.region
        return (
            f"[{place} {category}] {headline}",
            f"이번 현장은 실제로 '{area.label}'에 있습니다. title·intro 에 '{place} {category}' 를 자연스럽게 넣되 "
            f"더 구체적인 주소·시설명은 쓰지 않습니다. {service}",
        )
    return (
        f"{headline} | {area.region} {category} {company}",
        f"서비스 지역 키워드는 '{area.region}'(대표 동: {area.dong}) 입니다. 이번 현장의 실제 위치는 알 수 없으므로 "
        f"현장이 {area.dong or area.region}에 있었다고 쓰지 마세요. title 은 위 예시처럼 끝에 "
        f"'| {area.region} {category} {company}' 를 붙이고, intro 에는 지역명을 쓰지 않으며, {service}",
    )


# '청담동 등 서울 강남구 전 지역 출장…' 처럼 출장 문구 앞에 붙은 지역 표현 (문장 첫 글자부터)
_SERVICE_PREFIX = re.compile(r"[^\s.!?][^\n.!?]*?전\s*지역\s*(?=출장)")


def with_service_area(outro: str) -> str:
    """출장 가능 범위를 항상 '수도권 전 지역'으로 맞춘다 — AI 가 지역 키워드로 좁혀 쓰거나 빠뜨려도."""
    fixed = _SERVICE_PREFIX.sub(f"{SERVICE_AREA} 전 지역 ", outro)
    if "출장" in fixed:
        return fixed
    return f"{fixed.rstrip()}\n{SERVICE_AREA_LINE}"


def normalize_hashtags(
    tags: Sequence[str],
    category: str,
    company: str,
    count: int = HASHTAG_COUNT,
    priority: Sequence[str] = (),
) -> tuple[str, ...]:
    """'#' 접두사 통일, 공백/특수문자 제거, 중복 제거 후 정확히 count개로 맞춘다 (priority 를 맨 앞에)."""
    seen: set[str] = set()
    result: list[str] = []
    fallback = (category, company.replace(" ", ""), *GENERIC_TAGS)
    for raw in (*priority, *tags, *fallback):
        cleaned = re.sub(r"[^0-9A-Za-z가-힣_]", "", normalize_text(str(raw)))[:MAX_HASHTAG_LEN]
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(f"#{cleaned}")
        if len(result) == count:
            break
    return tuple(result)


def _strip_code_fence(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    return match.group(1) if match else text


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentGenerationError(f"AI 응답의 '{field}' 필드가 비어 있습니다")
    return normalize_text(value.strip())


def _joined_len(words: Sequence[str]) -> int:
    return len(" ".join(words))


def _can_break(words: Sequence[str], i: int, pattern: re.Pattern) -> bool:
    """words[i-1] 뒤에서 끊어도 되는지 (끊을 만한 어절 끝이고, 다음 어절이 보조동사가 아님)."""
    after = words[i] if i < len(words) else ""
    return bool(pattern.search(words[i - 1])) and not AUXILIARY.match(after)


def _best_cut(words: Sequence[str], target: int, next_word: str = "") -> int:
    """줄이 넘칠 때 끊을 위치: 연결어미 뒤 → 조사 뒤 → (없으면) 넘치기 직전 어절 뒤."""
    padded = [*words, next_word]
    for pattern in (NATURAL_BREAK, PHRASE_END):
        for i in range(len(words), 0, -1):
            if _can_break(padded, i, pattern) and _joined_len(words[:i]) >= target * 0.5:
                return i
    return len(words)


def _balanced_wrap(sentence: str, width: int) -> list[str]:
    """긴 문장을 고른 길이의 짧은 줄로 나눈다.

    '바닥 / 타일', '할 수 / 있습니다.' 처럼 어색하게 끊기지 않도록 쉼표·연결어미('~하고, ~하며, ~해서')
    뒤를 우선 끊고, 마지막 줄에 한두 어절만 남으면 앞줄에 붙인다.
    """
    if len(sentence) <= width + MOBILE_SLACK:
        return [sentence]
    parts = -(-len(sentence) // width)  # 올림
    target = -(-len(sentence) // parts) + 2
    words = sentence.split()
    lines: list[list[str]] = []
    current: list[str] = []
    for index, word in enumerate(words):
        if current and _joined_len([*current, word]) > target:
            cut = _best_cut(current, target, word)
            lines.append(current[:cut])
            current = current[cut:]
        current = [*current, word]
        rest = _joined_len(words[index + 1:])
        if (_can_break(words, index + 1, NATURAL_BREAK) and _joined_len(current) >= target * 0.6
                and rest >= MIN_LAST_LINE):
            lines.append(current)
            current = []
    if current:
        lines.append(current)
    if len(lines) > 1 and _joined_len(lines[-1]) < MIN_LAST_LINE:
        last = lines.pop()
        lines[-1] = [*lines[-1], *last]
    return [" ".join(line) for line in lines]


def split_sentences(text: str) -> list[str]:
    """AI 가 문장 중간에서 끊은 줄은 다시 잇고, 문장 단위로 나눈다 (빈 줄·'문의:' 같은 줄은 경계)."""
    sentences: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            joined = " ".join(buffer)
            sentences.extend(s for s in re.split(r"(?<=[.!?])\s+", joined) if s)
            buffer.clear()

    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            flush()
            continue
        buffer.append(line)
        if SENTENCE_END.search(line) or STANDALONE_LINE.search(line):
            flush()
    flush()
    return sentences


def wrap_mobile(text: str, width: int = MOBILE_LINE) -> str:
    """문장마다 빈 줄로 띄우고(덩어리 방지), 긴 문장은 고른 길이의 짧은 줄로 끊는다."""
    return "\n\n".join("\n".join(_balanced_wrap(s, width)) for s in split_sentences(text))


def _clean_tips(value: object) -> str:
    """AI 가 TIP 본문 첫 줄에 소제목('○○ 관리 TIP')을 다시 쓰면 제거 (소제목은 따로 붙임)."""
    if not isinstance(value, str):
        return ""
    lines = value.strip().split("\n")
    if lines and "TIP" in lines[0].upper() and len(lines[0]) <= 30:
        lines = lines[1:]
    return wrap_mobile(normalize_text("\n".join(lines).strip()))


def _captions(value: object, count: int | None) -> tuple[str, ...]:
    """사진 설명 목록을 정리하고, 사진 수가 주어지면 개수를 정확히 맞춘다 (부족분은 빈 설명)."""
    items = [wrap_mobile(normalize_text(str(v).strip())) for v in value] if isinstance(value, list) else []
    if count is None:
        return tuple(items)
    return tuple((items + [""] * count)[:count])


def parse_content(
    raw: str,
    category: str,
    company: str,
    stages_present: Sequence[str] = STAGES,
    photo_counts: Mapping[str, int] | None = None,
    area: AreaPick | None = None,
) -> PostContent:
    try:
        data = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError as exc:
        raise ContentGenerationError(f"AI 응답이 JSON 형식이 아닙니다: {exc}") from exc
    if not isinstance(data, dict):
        raise ContentGenerationError("AI 응답 최상위가 객체가 아닙니다")

    raw_sections = data.get("sections") or []
    by_stage = {
        item.get("stage"): item for item in raw_sections if isinstance(item, dict)
    }
    sections = tuple(
        Section(
            stage=stage,
            heading=_text(by_stage[stage].get("heading"), f"sections.{stage}.heading"),
            body=wrap_mobile(_text(by_stage[stage].get("body"), f"sections.{stage}.body")),
            captions=_captions(
                by_stage[stage].get("photo_captions"),
                photo_counts.get(stage, 0) if photo_counts is not None else None,
            ),
        )
        for stage in STAGES
        if stage in stages_present and stage in by_stage
    )
    if not sections:
        raise ContentGenerationError("AI 응답에 사용 가능한 본문 섹션이 없습니다")

    raw_tags = data.get("hashtags") or []
    raw_tips = data.get("tips")
    caption = _text(data.get("tiktok_caption"), "tiktok_caption")[:TIKTOK_CAPTION_MAX]
    return PostContent(
        title=_text(data.get("title"), "title")[:120],
        intro=wrap_mobile(_text(data.get("intro"), "intro")),
        sections=sections,
        outro=wrap_mobile(with_service_area(_text(data.get("outro"), "outro"))),
        hashtags=normalize_hashtags(
            raw_tags if isinstance(raw_tags, list) else [], category, company,
            priority=area.hashtags(category) if area else (),
        ),
        tiktok_caption=caption,
        tips=_clean_tips(raw_tips),
        keyword=area_keyword(area, category),
    )


def area_keyword(area: AreaPick | None, category: str) -> str:
    if area is None:
        return ""
    place = (area.dong or area.region) if area.is_site else area.region
    return f"{place} {category}".strip()


@dataclass(frozen=True)
class _Framing:
    role: str
    headline: str
    intro: str
    closing: str


def _framing(company: str, category: str, reused: bool) -> _Framing:
    """새로 올린 사진이면 '현장 기록', 이전에 쓴 사진을 다시 조합했으면 '작업 사례' 글.

    다시 조합한 사진은 여러 현장 사진이 섞였을 수 있으므로, 새 현장을 다녀온 것처럼 쓰지 않는다 (허위 현장 방지).
    """
    if not reused:
        return _Framing(
            role=(f"업체가 직접 쓰는 '현장 기록' 글을 작성합니다.\n"
                  f"위 사진들은 '{category}' 현장에서 찍은 것이고, 각 사진 앞에 [단계 사진 번호] 표시가 있습니다."),
            headline="○○ 현장, ○○까지 깔끔하게",
            intro="오늘 현장이 어떤 곳이고 어떤 상태였는지",
            closing=f'"이상 {category} 현장이었습니다" 식의 맺음',
        )
    return _Framing(
        role=(f"업체가 직접 쓰는 '{category} 작업 사례' 글을 작성합니다.\n"
              f"위 사진들은 {company}가 그동안 작업한 여러 '{category}' 현장의 실제 사진이며(서로 다른 현장 사진이 "
              f"섞여 있을 수 있음), 각 사진 앞에 [단계 사진 번호] 표시가 있습니다.\n"
              f"이 글은 새 현장 방문기가 아닙니다. '이번에 다녀온 현장', '오늘 현장'처럼 한 곳을 새로 다녀온 것처럼 쓰지 말고, "
              f"사진끼리 같은 장소라고 단정하지 않습니다. 실제 작업 사진을 예로 들어 {category}를 어떤 순서·방법으로 하는지와 "
              f"관리 포인트를 소개합니다. 사진에 보이는 장면에 맞춰 매번 다른 주제(오염 유형·작업 방법 등)를 골라 씁니다."),
        headline="○○ 청소, 이렇게 진행합니다",
        intro=f"이번 글에서 소개할 {category} 작업 포인트(사진에 보이는 오염 유형과 작업 방법)",
        closing=f'"이상 {company}의 {category} 작업 사례였습니다" 식의 맺음',
    )


def build_prompt(
    company: str,
    phone: str,
    category: str,
    photo_counts: Mapping[str, int],
    area: AreaPick | None = None,
    reused: bool = False,
) -> str:
    present = [s for s in STAGES if photo_counts.get(s)]
    stage_plan = ", ".join(f"{s} 사진 {photo_counts[s]}장" for s in present)
    specialty = CATEGORY_DESCRIPTIONS.get(category, category)
    framing = _framing(company, category, reused)
    title_example, area_rule = area_rules(area, category, company, framing.headline)
    return f"""당신은 청소 전문업체 '{company}'의 블로그 담당자이며, {framing.role}

[글 구성]
1. title: 검색 키워드가 들어간 제목. 예) "{title_example}" (50자 이내)
2. intro: "안녕하세요! {specialty} 전문 {company}입니다." 로 시작해, {framing.intro},
   이런 오염을 방치하면 어떤 문제가 생기는지까지 5~7문장으로 소개합니다.
3. sections: 단계마다
   - heading: 인용구로 들어갈 짧은 소제목. 궁금증을 주는 문장 (예: "작업 전, 이 정도였어요")
   - body: 이 단계를 여는 3~4문장 (이 단계에서 무엇을 왜, 어떤 순서로 하는지)
   - photo_captions: 그 단계 사진 수와 정확히 같은 개수. 사진마다 그 사진에 실제로 보이는 것을 3~4문장으로 설명합니다.
     (오염 상태, 작업 방법·장비, 그 공정을 하는 이유, 달라진 점). 설명끼리 표현이 겹치지 않게 씁니다.
     '첫 번째 사진은', '사진 1', '촬영한 사진으로' 같은 사진 번호·촬영 언급 없이 장면 자체를 바로 설명합니다.
4. tips: '{category} 관리 TIP' 문단 5~6문장. 이런 현장을 오래 깨끗하게 유지하는 일반적인 관리 요령과
   전문 청소 권장 주기를 알려줍니다. (이 현장에 대한 새로운 사실을 지어내지 말고 일반 상식 수준으로)
5. outro: 전후 차이를 한 줄로 정리 → {framing.closing} →
   "현장 사진을 보내주시면 상담·견적 도와드립니다" 안내 → 전화 {phone}

[문체]
- 시설 명칭은 항상 '상업 시설'로 씁니다. '건물'이라는 표현은 제목·본문·사진 설명·TIP·캡션에서 사용하지 않습니다.
- 해시태그에는 공백 없이 '상업시설'로 씁니다.
- 업체 1인칭의 친근하고 믿음직한 말투 (~입니다 / ~했어요 혼용). 느낌표·이모티콘(:) 등)은 글 전체에 3~5개만.
- 한 문장은 짧고 명확하게(40자 안팎) 쓰고, 문장이 끝날 때마다 줄을 바꿉니다 (줄바꿈은 \\n).
- 고객 후기처럼 쓰지 않고, 고객의 말이나 평가를 지어내지 않습니다.
- 분량: 본문 전체(공백 제외 모든 텍스트 합) 1,300~1,800자. 짧게 끝내지 말고 공정의 이유와 차이를 충분히 설명합니다.

[사실 규칙]
- 사진에서 확인되는 것만 씁니다. 가격·시간·약품명·면적 등은 사진에 명확히 보이지 않으면 쓰지 않습니다.
- '친환경·무독성·살균 99%' 처럼 사진으로 확인할 수 없는 성분·효능 표현은 쓰지 않습니다.
- {area_rule}
- 사진에 다른 업체의 상호·전화번호·간판 글자가 보여도 언급하지 않습니다. 연락처는 {phone} 만 씁니다.
- 최고·유일·100% 같은 과장 표현, 타 업체 비방은 금지합니다.

[출력] 아래 JSON 객체 하나만 출력하세요 (설명·코드블록 금지).
{{
  "title": "...",
  "intro": "...",
  "sections": [
    {{"stage": "작업전|작업중|작업후", "heading": "...", "body": "...", "photo_captions": ["사진1 설명", "..."]}}
  ],
  "tips": "...",
  "outro": "...",
  "hashtags": ["해시태그 15개, # 없이, 띄어쓰기 없이. '{category}' 관련 검색어 위주"],
  "tiktok_caption": "틱톡 캡션 (150자 이내, 이모지 1~3개, 해시태그 5개 포함)"
}}
sections 는 이 순서와 사진 수로만 작성하세요: {stage_plan}
"""


class ContentGenerator:
    def __init__(
        self,
        api_key: str,
        model: str,
        company: str,
        phone: str,
        client=None,
        max_attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        fallback_models: Sequence[str] = (),
    ) -> None:
        if client is None:
            from google import genai

            client = genai.Client(api_key=api_key)
        self._client = client
        self._models = tuple(dict.fromkeys((model, *fallback_models)))  # 순서 유지 중복 제거
        self._company = company
        self._phone = phone
        self._max_attempts = max_attempts
        self._sleep = sleep

    def _build_contents(
        self, category: str, images_by_stage: Mapping[str, Sequence[Path]], area: AreaPick | None,
        reused: bool = False,
    ) -> list:
        from google.genai import types

        contents: list = []
        for stage in STAGES:
            for index, path in enumerate(images_by_stage.get(stage, ()), start=1):
                contents.append(f"[{STAGE_LABELS[stage]} 사진 {index}]")
                contents.append(types.Part.from_bytes(data=path.read_bytes(), mime_type="image/jpeg"))
        counts = {s: len(images_by_stage.get(s, ())) for s in STAGES}
        contents.append(build_prompt(self._company, self._phone, category, counts, area, reused))
        return contents

    def generate(
        self,
        category: str,
        images_by_stage: Mapping[str, Sequence[Path]],
        area: AreaPick | None = None,
        reused: bool = False,
    ) -> PostContent:
        from google.genai import types

        counts = {s: len(images_by_stage.get(s, ())) for s in STAGES}
        present = [s for s in STAGES if counts[s]]
        contents = self._build_contents(category, images_by_stage, area, reused)
        config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.8)
        min_chars = min_body_chars(counts)

        # 한 라운드에 모든 모델을 순서대로 시도 → 전부 실패하면 대기 후 다음 라운드.
        # 분량이 최소치에 못 미치면 1회만 '더 자세히' 재요청하고, 그래도 짧으면 가장 긴 결과를 쓴다.
        last_error: Exception | None = None
        shortest_ok: PostContent | None = None
        total = self._max_attempts * len(self._models)
        for attempt in range(1, self._max_attempts + 1):
            for model in self._models:
                try:
                    response = self._client.models.generate_content(
                        model=model, contents=contents, config=config
                    )
                    content = parse_content(response.text or "", category, self._company, present, counts, area)
                except Exception as exc:  # 과부하/모델중단/네트워크/파싱 오류 모두 다음 후보로
                    last_error = exc
                    log.warning("AI 원고 생성 실패 [%s] (라운드 %d/%d): %s", model, attempt, self._max_attempts, exc)
                    continue
                length = content.text_length()
                if length >= min_chars:
                    return content
                if shortest_ok is not None:  # 이미 한 번 늘려 달라고 했음
                    return content if length > shortest_ok.text_length() else shortest_ok
                log.warning("AI 원고가 짧아 재요청합니다 (%d자 < 최소 %d자)", length, min_chars)
                shortest_ok = content
                contents = [*contents[:-1], contents[-1] + (
                    f"\n※ 직전 답변의 본문이 공백 제외 {length}자로 너무 짧았습니다. "
                    f"공백 제외 {min_chars}자 이상이 되도록 사진 설명, 공정 이유, 관리 TIP 을 더 자세히 쓰세요."
                )]
            if attempt < self._max_attempts:
                self._sleep(RETRY_WAIT_SECONDS * attempt)  # 과부하(503)가 풀리도록 15·30·45초 대기
        if shortest_ok is not None:
            return shortest_ok
        raise ContentGenerationError(f"AI 원고 생성에 {total}회 실패했습니다: {last_error}")
