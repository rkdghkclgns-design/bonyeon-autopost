"""구글 블로그(Blogger API v3) 발행 + 블로그용 HTML 생성."""
from __future__ import annotations

import html
import logging
import re
from typing import Mapping, Sequence

from .ai_helper import PostContent
from .constants import REVIEW_CAPTION, REVIEW_HEADING, STAGE_LABELS, STAGES
from .editorial import category_label, normalize_html, normalize_text
from .results import PublishResult

log = logging.getLogger(__name__)

PLATFORM = "구글 블로그"
MAX_LABELS = 6


# 문장마다 문단을 나누고 문단 사이를 빈 줄 한 줄만큼(≈30px) 띄워, 문장 안 줄바꿈과 문장 사이가 구분되게 한다
TEXT_STYLE = "text-align:center;line-height:1.9;margin:0 0 30px;"
CAPTION_STYLE = "text-align:center;line-height:1.8;margin:0 0 26px;color:#333;"
QUOTE_STYLE = (
    "text-align:center;margin:36px auto 18px;padding:14px 20px;max-width:560px;"
    "border-top:2px solid #146c94;border-bottom:2px solid #146c94;font-size:1.15em;"
)
COMPARISON_CAPTION = "작업 전(좌) · 작업 후(우)"


def tips_heading(content: PostContent) -> str:
    """관리 TIP 소제목 — 지역 검색어(없으면 제목의 [키워드]) 재사용, 둘 다 없으면 일반 문구."""
    if content.keyword:
        return f"{content.keyword} 관리 TIP"
    match = re.match(r"\[([^\]]+)\]", content.title)
    return f"{match.group(1)} 관리 TIP" if match else "관리 TIP"


def _paragraphs(text: str, style: str = TEXT_STYLE) -> str:
    """빈 줄로 문단을 나누고, 문단 안의 줄바꿈은 <br> 로 살린다 (모바일용 짧은 줄 유지)."""
    blocks = [block.strip() for block in text.replace("\r\n", "\n").split("\n\n") if block.strip()]
    return "".join(
        f'<p style="{style}">'
        + "<br/>".join(html.escape(line.strip()) for line in block.split("\n") if line.strip())
        + "</p>"
        for block in blocks
    )


def _img(url: str, alt: str) -> str:
    return (
        f'<div style="text-align:center;margin:28px 0 12px;">'
        f'<img src="{html.escape(url, quote=True)}" alt="{html.escape(alt, quote=True)}" '
        f'style="max-width:100%;height:auto;border-radius:8px;" loading="lazy"/></div>'
    )


def _section_html(stage: str, urls: Sequence[str], section) -> list[str]:
    heading = section.heading if section else STAGE_LABELS[stage]
    parts = [f'<h3 style="{QUOTE_STYLE}">“ {html.escape(heading)} ”</h3>']
    if section:
        parts.append(_paragraphs(section.body))
    for index, url in enumerate(urls):
        parts.append(_img(url, f"{STAGE_LABELS[stage]} 사진 {index + 1}"))
        caption = section.caption_for(index) if section else ""
        if caption:
            parts.append(_paragraphs(caption, CAPTION_STYLE))
    return parts


def build_blog_html(
    content: PostContent,
    image_urls_by_stage: Mapping[str, Sequence[str]],
    header_url: str | None = None,
    footer_url: str | None = None,
    comparison_url: str | None = None,
    review_urls: Sequence[str] = (),
) -> str:
    parts: list[str] = []
    if header_url:
        parts.append(_img(header_url, "업체 로고"))
    parts.append(_paragraphs(content.intro))

    for stage in STAGES:
        urls = image_urls_by_stage.get(stage, ())
        section = content.section_for(stage)
        if urls or section is not None:
            parts.extend(_section_html(stage, urls, section))
    if comparison_url:  # 작업 후 사진 다음 — 결과를 한 장으로 정리
        parts.append(_img(comparison_url, "작업 전후 비교"))
        parts.append(_paragraphs(COMPARISON_CAPTION, CAPTION_STYLE))

    if review_urls:
        parts.append(f'<h3 style="{QUOTE_STYLE}">“ {html.escape(REVIEW_HEADING)} ”</h3>')
        for url in review_urls:
            parts.append(_img(url, "고객 후기"))
        parts.append(_paragraphs(REVIEW_CAPTION, CAPTION_STYLE))
    if content.tips:
        parts.append(f'<h3 style="{QUOTE_STYLE}">“ {html.escape(tips_heading(content))} ”</h3>')
        parts.append(_paragraphs(content.tips))
    parts.append(_paragraphs(content.outro))
    if footer_url:
        parts.append(_img(footer_url, "상담 문의 안내"))
    parts.append(f'<p style="text-align:center;color:#1a73e8;">{html.escape(" ".join(content.hashtags))}</p>')
    return normalize_html("\n".join(parts))


def build_labels(category: str, hashtags: Sequence[str]) -> list[str]:
    labels = [category_label(category)]
    for tag in hashtags:
        label = category_label(normalize_text(tag.lstrip("#")))
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= MAX_LABELS:
            break
    return labels


class BloggerPublisher:
    def __init__(self, service, blog_id: str) -> None:
        self._service = service
        self._blog_id = blog_id

    def publish(self, title: str, html_body: str, labels: Sequence[str]) -> PublishResult:
        body = {
            "kind": "blogger#post", "title": normalize_text(title), "content": normalize_html(html_body),
            "labels": list(dict.fromkeys(category_label(normalize_text(label)) for label in labels)),
        }
        response = (
            self._service.posts()
            .insert(blogId=self._blog_id, body=body, isDraft=False)
            .execute(num_retries=3)
        )
        url = response.get("url", "")
        log.info("구글 블로그 발행 완료: %s", url)
        return PublishResult(platform=PLATFORM, ok=True, url=url, message="발행 완료")
