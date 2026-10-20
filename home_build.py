"""첫 화면 (대한민국 지도) 데이터: 서울(results_zone/map_data.json)과 수도권·광역시(results_region/summary.json) → home/index.html

지수를 공개한 지역은 점수 색으로 칠하고 누르면 그 지역 페이지로 간다. 공개 기준에 못 미쳤거나 실거래를 아직 다 못 받은 지역은
빗금('검증 중')으로만 보인다. 지도는 data/korea_map.json (build_geo_kr.py).
"""
import json
from pathlib import Path

from regions import REGIONS

ROOT = Path(__file__).parent
RULE = ("서울 밖 지역은 결과를 보기 전에 정한 기준(2011년 이후 정확도 0.40 이상, 5년씩 나눈 구간의 중앙값 0.25 이상)을 넘은 곳만 공개해요. "
        "지역 엔진을 여러 후보 중에서 고른 뒤에는, 그 지역을 빼고 고른 엔진으로 잰 성적(교차검증)에 이 기준을 적용해요. 서울은 2011년 이후 0.59예요.")


def published():
    """공개한 서울 밖 지역 id (사이트에 페이지를 만드는 지역)."""
    p = ROOT / "results_region" / "summary.json"
    s = json.loads(p.read_text()) if p.exists() else {}
    return [r for r in REGIONS if s.get(r, {}).get("publish")]


def data():
    m = json.loads((ROOT / "results_zone" / "map_data.json").read_text())
    s = m["regions"]["서울"]["score"]
    t = max(i for i, v in enumerate(s) if v is not None)
    p = ROOT / "results_region" / "summary.json"
    summ = json.loads(p.read_text()) if p.exists() else {}
    regions = [{"id": "seoul", "name": "서울", "prov": "서울", "url": "seoul/", "status": "live", "score": s[t], "prev": s[t - 1],
                "acc": m["regions"]["서울"]["acc"], "sub": "5대 권역 · 25개 구"}]
    for rid, d in REGIONS.items():
        x = summ.get(rid)
        if x and x["publish"]:
            regions.append({"id": rid, "name": d["name"], "prov": d["name"], "url": f"{rid}/", "status": "live", "score": x["score"],
                            "prev": x["prev"], "acc": x["acc"], "sub": f"{x['n_sub']}개 {x['sub_word']}"})
        else:
            why = (f"{'교차검증 ' if x.get('cross_validated') else ''}정확도 {x['acc']:.2f} · 5년 구간 중앙값 {x['win_median']:.2f} (기준 0.40 · 0.25)" if x
                   else "실거래 자료를 받는 중이에요")
            regions.append({"id": rid, "name": d["name"], "prov": d["name"], "status": "wait", "why": why,
                            "sub": f"{len(d['lawd'])}개 {'시·구' if rid == 'gyeonggi' else '구·군'}"})
    return {"map": json.loads((ROOT / "data" / "korea_map.json").read_text()), "month": m["dates"][t], "regions": regions,
            "seoul_names": ["서울", *m["regions"]], "rule": RULE}


if __name__ == "__main__":
    d = data()
    html = (ROOT / "home" / "template.html").read_text().replace("__DATA__", json.dumps(d, ensure_ascii=False, separators=(",", ":")))
    (ROOT / "home" / "index.html").write_text(html)
    print("home:", d["month"], [(r["name"], r["status"]) for r in d["regions"]])
