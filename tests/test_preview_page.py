import re

from autopost.ai_helper import parse_content
from autopost.preview_page import data_uri, render_preview, write_preview
from fakes import ai_json, make_jpeg


def test_preview_embeds_every_image_and_escapes_text(tmp_path):
    photos = {
        "작업전": [make_jpeg(tmp_path / "b.jpg", size=(2000, 1500))],
        "작업후": [make_jpeg(tmp_path / "a.jpg")],
    }
    header = make_jpeg(tmp_path / "h.jpg")
    comparison = make_jpeg(tmp_path / "c.jpg")
    content = parse_content(ai_json(title="<b>제목</b> & 현장", tiktok_caption="캡션 <script>"), "로프청소", "본연")
    page = render_preview(content, photos, header=header, comparison=comparison, note="검토용")

    srcs = re.findall(r'src="([^"]+)"', page)
    assert len(srcs) == 4 and all(s.startswith("data:image/jpeg;base64,") for s in srcs)  # 사진2+헤더+비교
    assert "<title>&lt;b&gt;제목&lt;/b&gt; &amp; 현장</title>" in page
    assert "캡션" not in page and "<script>" not in page  # 틱톡 캡션은 블로그 미리보기에 넣지 않음
    assert '<div class="note">검토용</div>' in page


def test_data_uri_shrinks_large_photos(tmp_path):
    big = make_jpeg(tmp_path / "big.jpg", size=(4000, 3000))
    small = make_jpeg(tmp_path / "small.jpg", size=(900, 675))
    assert len(data_uri(big)) < big.stat().st_size * 1.4  # 줄여서 넣음
    assert data_uri(small).startswith("data:image/jpeg;base64,")


def test_write_preview_creates_file_and_skips_missing_assets(tmp_path):
    content = parse_content(ai_json(stages=("작업후",)), "정기청소", "본연")
    out = write_preview(tmp_path / "out" / "p.html", content, {"작업후": [make_jpeg(tmp_path / "a.jpg")]},
                        header=tmp_path / "없는파일.png")
    text = out.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>") and text.count("data:image/jpeg") == 1


def test_naver_preview_follows_editor_blocks_line_by_line(tmp_path):
    from autopost.preview_page import render_naver_preview

    content = parse_content(ai_json(), "로프청소", "본연")
    photos = {"작업전": [make_jpeg(tmp_path / "b.jpg")], "작업후": [make_jpeg(tmp_path / "a.jpg")]}
    header, footer = make_jpeg(tmp_path / "h.jpg"), make_jpeg(tmp_path / "f.jpg")
    page = render_naver_preview(content, photos, header=header, footer=footer, blog="blog.naver.com/evbank")
    assert page.count("data:image/jpeg") == 4  # 헤더 + 사진 2 + 푸터
    assert page.index("data:image") < page.index("안녕하세요")  # 헤더가 맨 위
    assert '<p class="heading">“ 작업전 모습 ”</p>' in page  # 소제목 강조 (위아래 줄 + 굵게)
    assert page.count('<p class="rule">') == 2 * 4  # 작업전·중·후·관리TIP 소제목마다 위아래 줄
    assert '.body {{ text-align:center; }}'.replace("{{", "{").replace("}}", "}") in page  # 가운데 정렬
    assert "<p>&nbsp;</p>" in page  # 빈 줄 = 빈 문단
    assert "<span>#로프청소</span>" in page and "blog.naver.com/evbank" in page
