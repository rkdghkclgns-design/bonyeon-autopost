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
    assert "캡션 &lt;script&gt;" in page and "<script>" not in page
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
