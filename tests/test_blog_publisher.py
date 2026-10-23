from autopost.ai_helper import parse_content
from autopost.blog_publisher import BloggerPublisher, build_blog_html, build_labels
from fakes import ai_json


def _content(**overrides):
    return parse_content(ai_json(**overrides), "로프청소", "본연")


def test_html_escapes_ai_text_and_orders_sections():
    content = _content(intro="<script>alert(1)</script>")
    html = build_blog_html(
        content,
        {"작업전": ["https://img/1"], "작업후": ["https://img/2", "https://img/3"]},
        header_url="https://img/header",
        footer_url="https://img/footer",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert html.index("img/header") < html.index("img/1") < html.index("img/2") < html.index("img/footer")
    assert html.count("<h3 ") == 3 + 1  # 단계 3개(작업중은 사진이 없어도 AI 섹션이 있으면 출력) + 관리 TIP
    assert "#로프청소" in html


def test_photos_alternate_with_their_captions():
    html = build_blog_html(_content(), {"작업후": ["https://img/a1", "https://img/a2"]})
    order = [html.index(s) for s in ("작업후 모습", "작업후 설명입니다", "img/a1", "작업후 첫 사진 설명",
                                      "img/a2", "작업후 둘째 사진 설명")]
    assert order == sorted(order)  # 소제목 → 도입 → 사진1 → 설명1 → 사진2 → 설명2


def test_each_sentence_is_a_separate_paragraph():
    long_sentence = "두껍게 자라있던 이끼와 찌든 침전물을 말끔히 제거하여 배선 주변이 하얗게 되살아났습니다."
    html = build_blog_html(_content(intro=f"첫 문장입니다. 둘째 문장이에요! {long_sentence}"), {})
    assert ">첫 문장입니다.</p>" in html
    assert ">둘째 문장이에요!</p>" in html
    assert "<br/>" in html  # 긴 문장은 문단 안에서 짧은 줄로



def test_comparison_image_follows_after_photos():
    html = build_blog_html(_content(), {"작업전": ["https://img/b"], "작업후": ["https://img/a"]},
                           header_url="https://img/h", comparison_url="https://img/cmp")
    # 헤더 → 인사말 → 작업 전 → 작업 후 → 전후 비교(+설명) → 맺음말
    order = [html.index(s) for s in ("img/h", "안녕하세요", "img/b", "img/a", "img/cmp",
                                      "작업 전(좌) · 작업 후(우)", "상담은")]
    assert order == sorted(order)
    assert html.count("img/cmp") == 1


def test_reviews_and_tips_sections_order():
    content = _content(title="[수원 로프청소] 간판 청소 현장")
    html = build_blog_html(
        content, {"작업후": ["https://img/a"]}, comparison_url="https://img/cmp", review_urls=["https://img/rv"]
    )
    order = [html.index(s) for s in ("img/cmp", "고객님이 남겨주신 후기", "img/rv", "게시 동의를 받았습니다",
                                      "수원 로프청소 관리 TIP", "6개월마다", "상담은")]
    assert order == sorted(order)


def test_no_review_or_tips_blocks_when_absent():
    html = build_blog_html(_content(tips=None), {"작업후": ["https://img/a"]})
    assert "고객님이 남겨주신 후기" not in html
    assert "관리 TIP" not in html


def test_html_without_header_footer_and_stage_without_section():
    content = _content(sections=[{"stage": "작업전", "heading": "전", "body": "본문"}])
    html = build_blog_html(content, {"작업후": ["https://img/after"]})
    assert "업체 로고" not in html
    assert "“ 작업 후 ”</h3>" in html  # AI 섹션이 없으면 기본 라벨
    assert "전후 비교" not in html


def test_image_url_attribute_is_escaped():
    html = build_blog_html(_content(), {"작업전": ['https://img/"onerror="x']})
    assert '"onerror="' not in html


def test_video_is_embedded_after_outro_before_footer():
    html = build_blog_html(_content(), {"작업후": ["https://img/a"]}, footer_url="https://img/footer",
                           video_url="https://drive.google.com/file/d/vid/preview")
    # 맺음말 → 영상(소제목 + 플레이어) → 상담 문의 배너
    order = [html.index(s) for s in ("상담은", "영상으로 보는 작업 과정", "file/d/vid/preview", "img/footer")]
    assert order == sorted(order)
    assert html.count("<iframe") == 1


def test_no_video_block_without_video():
    html = build_blog_html(_content(), {"작업후": ["https://img/a"]})
    assert "<iframe" not in html
    assert "영상으로 보는 작업 과정" not in html


def test_video_url_attribute_is_escaped():
    html = build_blog_html(_content(), {}, video_url='https://x/"onload="y')
    assert '"onload="' not in html


def test_build_labels_limits_and_dedupes():
    labels = build_labels("로프청소", ["#로프청소", "#외벽", "#외벽", "#a", "#b", "#c", "#d"])
    assert labels == ["로프청소", "외벽", "a", "b", "c", "d"]


class _FakePosts:
    def __init__(self):
        self.calls = []

    def insert(self, blogId, body, isDraft):
        self.calls.append((blogId, body, isDraft))
        return self

    def execute(self, num_retries=0):
        return {"url": "https://myblog.blogspot.com/2026/09/post.html"}


class _FakeBlogger:
    def __init__(self):
        self.posts_api = _FakePosts()

    def posts(self):
        return self.posts_api


def test_blogger_publish_sends_post():
    service = _FakeBlogger()
    result = BloggerPublisher(service, "999").publish("제목", "<p>본문</p>", ["로프청소"])
    assert result.ok and result.url.endswith("post.html")
    blog_id, body, is_draft = service.posts_api.calls[0]
    assert blog_id == "999" and is_draft is False
    assert body["title"] == "제목" and body["labels"] == ["로프청소"]
