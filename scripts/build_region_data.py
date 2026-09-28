"""서울·경기·인천 행정동 목록 생성 → autopost/data/regions.json

출처: 공개 행정동 경계 데이터 (github.com/vuski/admdongkor, 통계청·행정안전부 행정동 기준)
행정구역이 개편되면 최신 버전으로 다시 실행하세요.

    python scripts/build_region_data.py            # 최신 버전 자동 탐색
    python scripts/build_region_data.py ver20260701
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import requests

REPO = "vuski/admdongkor"
SIDO = ("서울특별시", "경기도", "인천광역시")
OUT = Path(__file__).resolve().parents[1] / "autopost" / "data" / "regions.json"
HEADERS = {"User-Agent": "autopost-region-builder"}


def latest_version() -> str:
    items = requests.get(f"https://api.github.com/repos/{REPO}/contents", headers=HEADERS, timeout=30).json()
    return sorted(i["name"] for i in items if i["type"] == "dir" and i["name"].startswith("ver"))[-1]


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else latest_version()
    url = f"https://raw.githubusercontent.com/{REPO}/master/{version}/HangJeongDong_{version}.geojson"
    print(f"다운로드: {url}")
    data = requests.get(url, headers=HEADERS, timeout=300).json()

    regions: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for feature in data["features"]:
        props = feature["properties"]
        parts = props["adm_nm"].split()
        if parts[0] not in SIDO or len(parts) < 3:
            continue
        sido, dong = parts[0], parts[-1]
        sgg = " ".join(parts[1:-1])
        regions[sido][sgg].append(dong)

    result = {
        "source": f"{REPO} {version}",
        "regions": {
            sido: {sgg: sorted(set(dongs)) for sgg, dongs in sorted(sggs.items())}
            for sido, sggs in sorted(regions.items())
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for sido, sggs in result["regions"].items():
        print(f"{sido}: 시군구 {len(sggs)}개, 행정동 {sum(len(v) for v in sggs.values())}개")
    print(f"저장: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
