import json

import pytest

from autopost.ai_helper import build_prompt, parse_content
from autopost.blog_maintenance import infer_category, post_patch
from autopost.blog_publisher import build_labels
from autopost.constants import COMPANY_SPECIALTY
from autopost.editorial import (
    company_introduction, normalize_company_html, normalize_html, normalize_text,
    with_company_introduction,
)
from fakes import ai_json


def test_normalize_html_preserves_images_links_and_attributes():
    markup = '<p>건물 관리 #건물청소 &amp; 상담</p><img src="https://img/건물.jpg" alt="원본"/>'
    markup += '<a href="https://example/건물?q=1>0">건물 안내</a><!-- 건물 --><style>.건물{}</style>'
    result = normalize_html(markup)
    assert '<p>상업 시설 관리 #상업시설청소 &amp; 상담</p>' in result
    assert 'src="https://img/건물.jpg"' in result
    assert 'href="https://example/건물?q=1>0"' in result
    assert '>상업 시설 안내</a>' in result
    assert '<!-- 건물 --><style>.건물{}</style>' in result
    assert normalize_html(result) == result


def test_ai_uses_commercial_facility_terms_in_every_output_field():
    payload = json.loads(ai_json())
    for key in ("title", "intro", "outro", "tips", "tiktok_caption"):
        payload[key] = "건물 관리가 필요합니다."
    payload["hashtags"] = ["건물청소", "건물관리"]
    for section in payload["sections"]:
        section.update(heading="건물 관리", body="건물 청소입니다.", photo_captions=["건물 바닥입니다."])
    content = parse_content(json.dumps(payload), "정기청소", "본연클린")
    assert "건물" not in content.plain_text() + content.tiktok_caption
    assert "상업 시설" in content.intro
    assert "#상업시설청소" in content.hashtags
    prompt = build_prompt("본연클린", "000", "정기청소", {"작업전": 1})
    assert COMPANY_SPECIALTY in prompt


def test_disinfection_has_one_canonical_archive_label():
    labels = build_labels("방역소독", ["#방역소독", "#소독", "#방역"])
    assert labels == ["방역 소독", "소독", "방역"]


def test_existing_post_patch_keeps_metadata_and_other_labels():
    post = {"id": "1", "title": "건물 소독", "content": '<p>건물</p><img src="x"/>',
            "labels": ["방역소독", "지역"], "url": "https://blog/original", "published": "date"}
    patch = post_patch(post)
    assert patch == {"title": "상업 시설 소독", "content": '<p>상업 시설</p><img src="x"/>',
                     "labels": ["방역 소독", "지역"]}
    assert post_patch({**post, **patch}) == {}
    assert post["url"] == "https://blog/original" and post["published"] == "date"


def test_missing_category_can_use_title_but_ambiguous_category_stops():
    assert infer_category({"title": "정기청소 사례"}) == "정기청소"
    with pytest.raises(ValueError):
        infer_category({"labels": ["정기청소", "로프청소"]})
    with pytest.raises(ValueError):
        infer_category({"title": "소개"})


def test_blogger_label_sorting_does_not_trigger_another_update():
    assert post_patch({"title": "정기청소", "content": "상업 시설", "labels": ["지역", "정기청소"]}) == {}


def test_hashtag_replacement_keeps_search_terms_together():
    assert normalize_text("건물 #건물관리") == "상업 시설 #상업시설관리"


@pytest.mark.parametrize("category", ["정기청소", "로프청소", "방역소독"])
def test_generated_intro_has_fixed_specialty_and_preserves_site_description(category):
    raw = ai_json(intro="안녕하세요! 상업 시설·사무실 정기청소 전문 본연클린입니다.\n오늘은 화장실 바닥을 관리했습니다.")
    content = parse_content(raw, category, "본연클린")
    flat = " ".join(content.intro.split())
    assert company_introduction("본연클린") in flat
    assert flat.count("본연클린입니다.") == 1
    assert "상업 시설·사무실 정기청소 전문" not in flat
    assert "오늘은 화장실 바닥을 관리했습니다." in flat
    assert with_company_introduction(content.intro, "본연클린").count("본연클린입니다.") == 1
    prompt = build_prompt("본연클린", "010", category, {"작업후": 1})
    assert COMPANY_SPECIALTY in prompt
    assert "사진에 없는 ESD 케어" in prompt


@pytest.mark.parametrize("old", [
    "상업 시설·사무실 정기청소 전문 본연클린입니다.",
    "상가·사무실 정기 청소, 외벽 청소 전문<br/>본연클린입니다.",
    "안녕하세요!<br/><strong>로프 외벽·간판·유리창 청소 전문</strong> 본연클린입니다.",
    "방역·소독 전문 본연클린입니다.",
])
def test_company_html_changes_only_introduction(old):
    photo = '<img src="https://img/compare_50_50.jpg" alt="작업 전후 비교"/>'
    rest = '<h3>작업 후</h3><p>현장 설명입니다.</p><p>본연클린입니다.</p>'
    markup = f'{photo}<p style="text-align:center">{old}</p>{rest}'
    changed = normalize_company_html(markup, "본연클린")
    assert changed.startswith(photo)
    assert changed.endswith(rest)
    assert '<p style="text-align:center">' in changed
    assert company_introduction("본연클린") in changed.replace("<br/>", " ")
    assert normalize_company_html(changed, "본연클린") == changed


def test_company_intro_does_not_replace_other_companies_or_image_paragraphs():
    markup = '<p>청소 전문 다른회사입니다.</p><p>본연클린입니다.<img src="x"/></p>'
    assert normalize_company_html(markup, "본연클린") == markup
    intro = with_company_introduction("오늘은 계단을 청소했습니다.", "본연클린")
    assert company_introduction("본연클린") in intro
    assert intro.endswith("오늘은 계단을 청소했습니다.")


def test_existing_company_intro_patch_is_content_only_and_idempotent():
    post = {"title":"정기청소 사례", "labels":["정기청소"], "published":"date", "url":"original",
            "content":'<p>안녕하세요!</p><p>상업 시설·사무실 정기청소 전문 본연클린입니다.</p><img src="original.jpg"/>'}
    patch = post_patch(post, "본연클린")
    assert set(patch) == {"content"}
    assert 'src="original.jpg"' in patch["content"]
    assert post_patch({**post, **patch}, "본연클린") == {}
