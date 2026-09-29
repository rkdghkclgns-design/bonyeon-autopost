"""구글 블로그(Blogger)에 올라간 글 HTML → 네이버 입력 블록 (같은 글을 네이버에 똑같이 올리기).

build_blog_html 이 만든 구조를 그대로 읽는다:
  <div><img alt=…></div>  → 사진 블록 (주소에서 내려받음)
  <h3>“ 소제목 ”</h3>       → 강조 소제목 블록
  <p>문장<br/>문장</p>       → 글 블록 (문단 사이는 빈 줄)
  마지막 해시태그 문단       → 네이버 태그 (본문에는 넣지 않음)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

from .naver_publisher import NaverBlock

HASHTAG_LINE = re.compile(r"^(#[^\s#]+\s*)+$")


@dataclass
class _Node:
    kind: str  # "text" | "heading" | "image"
    text: str = ""
    src: str = ""


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.nodes: list[_Node] = []
        self._buffer: list[str] = []
        self._open = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("p", "h3"):
            self._open, self._buffer = tag, []
        elif tag == "br" and self._open:
            self._buffer.append("\n")
        elif tag == "img" and attrs.get("src"):
            self.nodes.append(_Node("image", src=unescape(attrs["src"])))

    def handle_endtag(self, tag):
        if tag == self._open:
            text = "".join(self._buffer).strip()
            if text:
                self.nodes.append(_Node("heading" if tag == "h3" else "text", text=text))
            self._open, self._buffer = "", []

    def handle_data(self, data):
        if self._open:
            self._buffer.append(data)


def parse_blog_html(html: str) -> tuple[list[_Node], tuple[str, ...]]:
    parser = _Parser()
    parser.feed(html)
    parser.close()
    nodes = list(parser.nodes)
    hashtags: tuple[str, ...] = ()
    if nodes and nodes[-1].kind == "text" and HASHTAG_LINE.match(nodes[-1].text.replace("\n", " ")):
        hashtags = tuple(nodes.pop().text.split())
    return nodes, hashtags


def to_blocks(
    html: str, download_dir: Path, download: Callable[[str, Path], Path]
) -> tuple[list[NaverBlock], tuple[str, ...]]:
    """연속된 문단은 한 글 블록으로 묶는다 (문단 사이 빈 줄 = 구글의 문단 간격)."""
    nodes, hashtags = parse_blog_html(html)
    blocks: list[NaverBlock] = []
    paragraphs: list[str] = []

    def flush() -> None:
        if paragraphs:
            blocks.append(NaverBlock("text", text="\n\n".join(paragraphs)))
            paragraphs.clear()

    for index, node in enumerate(nodes):
        if node.kind == "text":
            paragraphs.append(node.text)
            continue
        flush()
        if node.kind == "heading":
            blocks.append(NaverBlock("heading", text=node.text))
        else:
            blocks.append(NaverBlock("image", image=download(node.src, download_dir / f"{index:02d}.jpg")))
    flush()
    return blocks, hashtags
