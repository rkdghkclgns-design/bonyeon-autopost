"""기존 Blogger 글을 신규 원고와 동일한 용어·자료실 분류로 맞춘다."""
from __future__ import annotations

from typing import Mapping

from .editorial import CATEGORY_LABELS, category_label, normalize_company_html, normalize_html, normalize_text


def infer_category(post: Mapping) -> str:
    labels = post.get("labels") or []
    known = {category_label(label) for label in labels if label in CATEGORY_LABELS}
    if not known:
        title = str(post.get("title", "")).replace(" ", "")
        known = {display for name, display in CATEGORY_LABELS.items() if name.replace(" ", "") in title}
    if len(known) != 1:
        raise ValueError(f"글 {post.get('id', '')}의 자료실 분류를 확정할 수 없습니다")
    return next(iter(known))


def post_patch(post: Mapping, company: str = "") -> dict:
    """바뀐 필드만 반환. 사진 URL·기존 글 주소·발행일은 수정하지 않는다."""
    category = infer_category(post)
    labels = list(dict.fromkeys((category, *(
        category_label(normalize_text(label)) for label in post.get("labels", [])
    ))))
    content = normalize_html(str(post.get("content", "")))
    if company:
        content = normalize_company_html(content, company)
    values = {
        "title": normalize_text(str(post.get("title", ""))),
        "content": content,
        "labels": labels,
    }
    return {
        key: value for key, value in values.items()
        if (set(value) != set(post.get(key) or []) if key == "labels" else value != post.get(key))
    }
