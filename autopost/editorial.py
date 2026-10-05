"""블로그에 공통 적용하는 용어와 자료실 분류 규칙."""
from __future__ import annotations

import re

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
