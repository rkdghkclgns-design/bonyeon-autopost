import pytest

from autopost.regions import AreaPick, area_group, pick_area, search_name, site_area, split_sgg


@pytest.mark.parametrize("raw,expected", [
    ("선부1동", "선부동"), ("상계3·4동", "상계동"), ("종로1·2·3·4가동", "종로동"),
    ("화수1·화평동", "화수동"), ("신길제1동", "신길동"), ("봉담읍", "봉담읍"), ("고잔동", "고잔동"), ("이동", "이동"),
])
def test_search_name(raw, expected):
    assert search_name(raw) == expected


@pytest.mark.parametrize("sgg,expected", [
    ("안산시단원구", ("안산", "단원구")), ("수원시 영통구", ("수원", "영통구")),
    ("화성시", ("화성", "")), ("가평군", ("가평", "")), ("강남구", ("", "강남구")),
])
def test_split_sgg(sgg, expected):
    assert split_sgg(sgg) == expected


def test_groups_cover_focus_regions():
    seoul, gyeonggi, incheon, ansan = (area_group(n) for n in ("서울", "경기", "인천", "안산"))
    assert len(seoul) > 200 and len(gyeonggi) > 400 and len(incheon) > 60
    assert all(p.city == "서울" and p.district.endswith("구") for p in seoul)
    assert {p.district for p in ansan} == {"단원구", "상록구"}
    assert AreaPick("안산", "단원구", "고잔동") in ansan
    assert any(p.district == "강화군" and p.city == "인천" for p in incheon)
    assert len(set(seoul)) == len(seoul)  # 선부1·2·3동 같은 중복 제거


def test_group_interleaves_districts():
    seoul = area_group("서울")
    assert seoul[0].district != seoul[1].district


def test_unknown_area_is_kept_as_text():
    assert area_group("부산") == (AreaPick(city="부산"),)


def test_pick_area_rotates_groups_then_dongs():
    areas = ["서울", "안산"]
    picks = [pick_area(areas, i) for i in range(6)]
    assert [p.city for p in picks] == ["서울", "안산"] * 3
    assert picks[1] != picks[3]  # 같은 그룹 안에서는 다음 동으로
    assert pick_area([], 3) is None


def test_site_area_resolution():
    assert site_area("고잔동") == AreaPick("안산", "단원구", "고잔동", is_site=True)
    assert site_area("강남구 역삼동") == AreaPick("서울", "강남구", "역삼동", is_site=True)
    assert site_area("안산 중앙동").district == "단원구"
    assert site_area("중앙동") == AreaPick("", "", "중앙동", is_site=True)  # 동명이 여러 곳 → 추측 안 함
    assert site_area("여의도") == AreaPick("여의도", is_site=True)
    assert site_area("  ") is None


def test_hashtags_and_labels():
    pick = AreaPick("안산", "단원구", "고잔동")
    assert pick.label == "안산 단원구 고잔동"
    assert pick.hashtags("정기청소") == ("고잔동정기청소", "고잔동청소", "단원구청소업체", "안산정기청소", "안산청소업체")
    assert AreaPick("화성", "", "봉담읍").region == "화성"
