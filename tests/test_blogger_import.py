from pathlib import Path

from autopost.ai_helper import parse_content
from autopost.blog_publisher import build_blog_html
from autopost.blogger_import import parse_blog_html, to_blocks
from fakes import ai_json


def _html():
    content = parse_content(ai_json(title="[수원 로프청소] 현장"), "로프청소", "본연")
    html = build_blog_html(
        content, {"작업전": ["https://img/b1"], "작업후": ["https://img/a1"]},
        header_url="https://img/h", footer_url="https://img/f", comparison_url="https://img/cmp",
    )
    return content, html


def test_blog_html_becomes_same_order_naver_blocks(tmp_path):
    content, html = _html()
    downloaded = []

    def fake_download(url: str, dest: Path) -> Path:
        downloaded.append(url)
        dest.write_bytes(b"jpg")
        return dest

    blocks, hashtags = to_blocks(html, tmp_path, fake_download)

    assert downloaded == ["https://img/h", "https://img/b1", "https://img/a1", "https://img/cmp", "https://img/f"]
    kinds = [b.kind for b in blocks]
    assert kinds[0] == "image" and kinds[-1] == "image"  # 헤더 … 푸터
    headings = [b.text for b in blocks if b.kind == "heading"]
    assert headings[0] == "“ 작업전 모습 ”" and headings[-1] == "“ 수원 로프청소 관리 TIP ”"
    texts = "\n".join(b.text for b in blocks if b.kind == "text")
    assert "작업후 첫 사진 설명" in texts and "상담은 000-0000-0000" in texts
    assert "#" not in texts  # 해시태그는 본문이 아니라 태그로
    assert hashtags == content.hashtags


def test_paragraphs_keep_line_breaks_and_blank_line_between():
    nodes, _ = parse_blog_html('<p style="x">첫 줄<br/>둘째 줄</p><p>다음 문단 &amp; 끝</p>')
    assert [n.text for n in nodes] == ["첫 줄\n둘째 줄", "다음 문단 & 끝"]
