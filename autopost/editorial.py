"""블로그에 공통 적용하는 용어와 자료실 분류 규칙."""
from __future__ import annotations

import html
import re

from .constants import COMPANY_SPECIALTY

CATEGORY_LABELS = {
    "정기청소": "정기청소",
    "로프청소": "로프청소",
    "방역소독": "방역 소독",
    "방역 소독": "방역 소독",
}

_HASHTAG = re.compile(r"#[0-9A-Za-z가-힣_]+")
# 태그의 속성(URL 포함), 주석, 스크립트와 스타일은 그대로 보존한다.
_HTML_MARKUP = re.compile(
    r"<!--.*?-->|<(?:script|style)\b[^>]*>.*?</(?:script|style)\s*>|"
    r"<(?:[^>\"']|\"[^\"]*\"|'[^']*')*>",
    re.DOTALL | re.IGNORECASE,
)
_PARAGRAPH = re.compile(
    r"(<p\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>)(.*?)(</p\s*>)",
    re.DOTALL | re.IGNORECASE,
)


def company_introduction(company: str) -> str:
    return f"{COMPANY_SPECIALTY} {company}입니다."


def with_company_introduction(intro: str, company: str) -> str:
    """첫 회사 인사말을 고정하고 현장 소개 문장은 유지한다."""
    identity = re.compile(
        rf"\A(?:안녕하세요[!.,]?\s*)?[^.!?]{{0,220}}?{re.escape(company)}입니다[.!]?\s*",
        re.DOTALL,
    )
    rest, matched = identity.subn("", intro.strip(), count=1)
    if not matched:
        rest = re.sub(r"\A안녕하세요[!.,]?\s*", "", rest, count=1)
    greeting = f"안녕하세요!\n\n{company_introduction(company)}"
    return f"{greeting}\n\n{rest}".rstrip()


def normalize_company_html(body: str, company: str) -> str:
    """회사 소개 문단만 교체한다. 현장 본문·사진·링크·문단 속성을 보존한다."""
    identity = re.compile(rf"[^.!?]*{re.escape(company)}입니다[.!]?")
    expected = company_introduction(company)
    specialty = html.escape(COMPANY_SPECIALTY).replace(", ", ",<br/>")
    replacement = f"{specialty}<br/>{html.escape(company)}입니다."

    def update(match: re.Match) -> str:
        opening, inner, closing = match.groups()
        if re.search(r"<(?:img|script|style)\b", inner, re.IGNORECASE):
            return match.group()
        flat = re.sub(r"\s+", " ", html.unescape(_HTML_MARKUP.sub(" ", inner))).strip()
        text, greeting = re.subn(r"\A안녕하세요[!.,]?\s*", "", flat, count=1)
        if not identity.fullmatch(text) or text == expected:
            return match.group()
        prefix = "안녕하세요!<br/>" if greeting else ""
        return f"{opening}{prefix}{replacement}{closing}"

    section = re.search(r"<h[2-6]\b", body, re.IGNORECASE)
    boundary = section.start() if section else len(body)
    return _PARAGRAPH.sub(update, body[:boundary]) + body[boundary:]


def normalize_text(text: str) -> str:
    """시설 명칭 통일. 해시태그 안에서는 검색어가 끊어지지 않게 공백을 생략한다."""
    text = _HASHTAG.sub(lambda m: m.group().replace("건물", "상업시설"), text)
    return text.replace("건물", "상업 시설")


def normalize_html(body: str) -> str:
    """HTML의 글 부분에만 용어 규칙을 적용해 사진·링크·서식을 유지한다."""
    parts: list[str] = []
    offset = 0
    for match in _HTML_MARKUP.finditer(body):
        parts.extend((normalize_text(body[offset:match.start()]), match.group()))
        offset = match.end()
    parts.append(normalize_text(body[offset:]))
    return "".join(parts)


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)
