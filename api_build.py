"""공개 데이터 API (정적 JSON·CSV) → site/api/v1/ (사이트 빌드 때 만든다, 저장소에는 안 올림).

지도와 같은 results_zone/map_data.json에서 직접 계산한 점수만 꺼낸다 (KB 등 원자료 값은 넣지 않음).
GitHub Pages가 모든 주소에 CORS(Access-Control-Allow-Origin: *)를 열어 두어 다른 사이트의 브라우저에서도 바로 불러갈 수 있다.
매달 20일 자동 갱신의 site_build.py에서 함께 다시 만든다.

  /api/v1/index.json            안내 (주소 목록, 눈금, 갱신 주기, 필드 설명)
  /api/v1/regions.json          지역 31곳 (서울·5대 권역·25개 구)의 id·이름·상위 지역
  /api/v1/latest.json           최신 달 점수·구간·변화·속도별 그룹·주제별 점수 (구는 서울 안 상대 강도 순위까지)
  /api/v1/history.json          2006년 1월부터 월별 점수 (지역 전체)
  /api/v1/history.csv           같은 내용을 표로 (열 이름 = 지역 id)
  /api/v1/history/{id}.json     한 지역의 월별 점수
"""
import csv
import io
import json
from pathlib import Path

from apt_score import LAWD2GU

ROOT = Path(__file__).parent
SITE_URL = "https://won-topiaa.github.io/korean-realestate-fear-and-greed-index/"
BASE = SITE_URL + "api/v1/"
ZONE_ID = {"도심권": "dosim", "동북권": "dongbuk", "서북권": "seobuk", "서남권": "seonam", "동남권": "dongnam"}
GU_ID = {v: k for k, v in LAWD2GU.items()}  # 구 이름 → 법정동 시군구 코드 5자리 (예: 강남구 → 11680)
GROUP = {"선행": "leading", "동행": "coincident", "후행": "lagging"}
THEME = {"가격": "price", "수급심리": "sentiment", "전세": "jeonse", "자금": "funding", "가격부담": "price_burden",
         "관심": "attention", "금융시장": "markets", "거래": "transactions", "공급": "supply"}
BANDS = [(0, 25, "extreme_fear", "극단적 공포"), (25, 45, "fear", "공포"), (45, 55, "neutral", "중립"),
         (55, 75, "greed", "탐욕"), (75, 100, "extreme_greed", "극단적 탐욕")]


def band(v):
    if v is None:
        return None
    for lo, hi, key, ko in BANDS:
        if v < hi or hi == 100:
            return {"key": key, "label": ko}


def rid(name):
    return "seoul" if name == "서울" else ZONE_ID.get(name) or GU_ID[name]


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))


def build(out):
    d = json.loads((ROOT / "results_zone" / "map_data.json").read_text())
    summ = json.loads((ROOT / "results_zone" / "update_summary.json").read_text())
    run = summ.get("run", "")
    updated = f"{run[:4]}-{run[4:6]}-{run[6:8]}" if len(run) >= 8 else None
    dates, R = d["dates"], d["regions"]
    names = ["서울", *ZONE_ID, *d["gu_order"]]
    t = max(i for i, v in enumerate(R["서울"]["score"]) if v is not None)  # 최신 달 (서울 점수가 있는 마지막 달)
    month = dates[t]

    def parent(n):
        r = R[n]
        return None if r["level"] == "seoul" else "seoul" if r["level"] == "zone" else rid(r["zone"])

    regions = [{"id": rid(n), "name": n, "level": R[n]["level"], "parent": parent(n),
                **({"children": [rid(g) for g in R[n]["gus"]]} if R[n]["level"] == "zone" else {}),
                **({"children": list(ZONE_ID.values())} if n == "서울" else {})} for n in names]

    def at(s, i):
        return s[i] if 0 <= i < len(s) else None

    def chg(s, back):
        a, b = at(s, t), at(s, t - back)
        return None if a is None or b is None else round(a - b, 1)

    latest = []
    for n in names:
        r, s = R[n], R[n]["score"]
        row = {"id": rid(n), "name": n, "level": r["level"], "score": at(s, t), "band": band(at(s, t)),
               "change": {"1m": chg(s, 1), "3m": chg(s, 3), "12m": chg(s, 12)},
               "groups": {GROUP[k]: at(v, t) for k, v in r["speed"].items()},
               "themes": {THEME[k]: at(r["themes"][k], t) for k in d["theme_order"] if k in r["themes"]}}
        if r.get("rel"):
            row["relative_strength_rank"] = at(r["rel"]["rank"], t)  # 25개 구 중 신고가 비중 순위 (1 = 가장 강함), 공포탐욕 점수와 별개
        latest.append(row)

    meta = {"month": month, "updated": updated, "engine": d["version"]}
    dump(out / "latest.json", {**meta, "regions": latest})
    dump(out / "regions.json", {"regions": regions})
    hist = {rid(n): R[n]["score"] for n in names}
    dump(out / "history.json", {**meta, "dates": dates, "series": hist})
    for n in names:
        dump(out / "history" / f"{rid(n)}.json", {**meta, "id": rid(n), "name": n, "dates": dates, "scores": R[n]["score"]})
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["month", *hist])
    for i, m in enumerate(dates):
        w.writerow([m, *("" if hist[k][i] is None else hist[k][i] for k in hist)])
    (out / "history.csv").write_text(buf.getvalue())

    dump(out / "index.json", {
        "name": "서울 아파트 공포탐욕지수 API",
        "description": "서울 아파트 시장 심리를 0~100으로 나타낸 월별 지수 (0 극단적 공포, 50 중립, 100 극단적 탐욕). 서울 전체·5대 권역·25개 구.",
        **meta,
        "update_schedule": "매달 20일 09:17 (한국 시간) 전후 갱신. month = 최신 점수의 기준 달, updated = 계산한 날",
        "coverage": {"from": dates[0], "to": month, "regions": len(names), "official_from": d["official_start"]},
        "scale": [{"from": lo, "to": hi, "key": key, "label": ko} for lo, hi, key, ko in BANDS],
        "endpoints": {"index": BASE + "index.json", "regions": BASE + "regions.json", "latest": BASE + "latest.json",
                      "history": BASE + "history.json", "history_csv": BASE + "history.csv", "history_region": BASE + "history/{id}.json"},
        "ids": "seoul = 서울 전체, dosim·dongbuk·seobuk·seonam·dongnam = 도심권·동북권·서북권·서남권·동남권, 5자리 숫자 = 구 (법정동 시군구 코드, 예: 11680 강남구)",
        "fields": {
            "score": "공포탐욕 점수 0~100 (소수 한 자리). 자료가 없는 달은 null",
            "band": "점수 구간 (scale 참고)",
            "change": "1·3·12개월 전보다 점수가 얼마나 변했는지 (점)",
            "groups": "속도별 3그룹 점수: leading 선행(기대·금리 변화·검색·주가), coincident 동행(가격·거래·수급), lagging 후행(가격부담·금리 수준·미분양). 최종 점수는 세 그룹의 평균을 눈금에 맞춘 값",
            "themes": "주제별 점수: price 가격, sentiment 수급심리(중개사 설문), jeonse 전세, funding 자금(금리·대출), price_burden 가격부담(PIR·구매력·전세가율), attention 관심(검색량), markets 금융시장(건설주·KOSPI), transactions 거래, supply 공급(미분양)",
            "direction": "score·groups·themes 모두 높을수록 탐욕(과열), 낮을수록 공포(위축) 쪽. 예: price_burden이 높으면 가격 부담이 커서 과열 쪽, funding이 낮으면 금리·대출 여건이 빡빡해 위축 쪽",
            "relative_strength_rank": "구만: 같은 달 25개 구 중 신고가 비중 순위 (1 = 가장 강함). 공포탐욕 점수와 별개 지표",
        },
        "method": SITE_URL + "report/",
        "site": SITE_URL,
        "contact": "wontopiaaa@gmail.com",
        "notice": "시장 분위기를 재는 지표이며 사고팔 시점을 알려주는 신호가 아닙니다. 계산 방법과 자료가 바뀌면 과거 값도 다시 계산될 수 있습니다 (engine 참고). 서비스에 넣어 쓰시려면 위 연락처로 알려 주세요.",
    })
    return month, len(names)


if __name__ == "__main__":
    out = ROOT / "site" / "api" / "v1"
    m, n = build(out)
    print(f"api: {m} · 지역 {n}곳 · {sum(p.stat().st_size for p in out.rglob('*')) / 1e3:.0f} KB")
