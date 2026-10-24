"""공개 데이터 API (정적 JSON·CSV) → site/api/v1/ (사이트 빌드 때 만든다, 저장소에는 안 올림).

지도와 같은 results_zone/map_data.json에서 직접 계산한 점수만 꺼낸다 (KB 등 원자료 값은 넣지 않음).
GitHub Pages가 모든 주소에 CORS(Access-Control-Allow-Origin: *)를 열어 두어 다른 사이트의 브라우저에서도 바로 불러갈 수 있다.
매달 20일 자동 갱신의 site_build.py에서 함께 다시 만든다.

  /api/v1/index.json            안내 (주소 목록, 눈금, 갱신 주기, 필드 설명)
  /api/v1/regions.json          지역 목록 (서울·5대 권역·25개 구 + 공개한 수도권·광역시와 그 시군구)의 id·이름·상위 지역
  /api/v1/latest.json           최신 달 점수·구간·변화·속도별 그룹·주제별 점수 (구는 서울 안 상대 강도 순위까지)
  /api/v1/history.json          2006년 1월부터 월별 점수 (지역 전체)
  /api/v1/history.csv           같은 내용을 표로 (열 이름 = 지역 id)
  /api/v1/history/{id}.json     한 지역의 월별 점수
"""
import csv
import io
import json
from pathlib import Path

ROOT = Path(__file__).parent
SITE_URL = "https://aptfeargreed.com/"  # 2026-10-23부터 (옛 github.io 주소는 GitHub이 이 주소로 넘겨 줌)
BASE = SITE_URL + "api/v1/"
ZONE_ID = {"도심권": "dosim", "동북권": "dongbuk", "서북권": "seobuk", "서남권": "seonam", "동남권": "dongnam"}
# 구 이름 → 법정동 시군구 코드 5자리 (apt_score.LAWD2GU와 같은 표. 무거운 계산 모듈을 사이트 빌드에 끌어오지 않으려고 따로 둠)
GU_ID = {"종로구": "11110", "중구": "11140", "용산구": "11170", "성동구": "11200", "광진구": "11215", "동대문구": "11230",
         "중랑구": "11260", "성북구": "11290", "강북구": "11305", "도봉구": "11320", "노원구": "11350", "은평구": "11380",
         "서대문구": "11410", "마포구": "11440", "양천구": "11470", "강서구": "11500", "구로구": "11530", "금천구": "11545",
         "영등포구": "11560", "동작구": "11590", "관악구": "11620", "서초구": "11650", "강남구": "11680", "송파구": "11710", "강동구": "11740"}
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


def rid(name, ids=None):
    if ids and name in ids:
        return ids[name]
    return "seoul" if name == "서울" else ZONE_ID.get(name) or GU_ID[name]


def on_dates(r, src, dst):
    """지역 결과의 달을 서울 달(dst)에 맞춘다. 지역 단계가 실패해 지난 결과가 남은 달에는 그 지역의 새 달이 null."""
    pos = {m: i for i, m in enumerate(src)}
    f = lambda s: [s[pos[m]] if m in pos else None for m in dst]
    return {**r, "score": f(r["score"]), "speed": {k: f(v) for k, v in r["speed"].items()},
            "themes": {k: f(v) for k, v in r["themes"].items()}}


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def build(out):
    d = json.loads((ROOT / "results_zone" / "map_data.json").read_text())
    summ = json.loads((ROOT / "results_zone" / "update_summary.json").read_text())
    run = summ.get("run", "")
    updated = f"{run[:4]}-{run[4:6]}-{run[6:8]}" if len(run) >= 8 else None
    dates, R = d["dates"], d["regions"]
    names = ["서울", *ZONE_ID, *d["gu_order"]]
    ids, extra = {}, []  # 공개한 수도권·광역시 (home_build.published): 시도 id는 영문(busan), 시군구는 5자리 코드
    import home_build
    from regions import REGIONS
    for rg in home_build.published():
        x = json.loads((ROOT / "results_region" / f"{rg}.json").read_text())
        if x["dates"] != dates:
            print(f"  {rg}: 기간이 서울과 달라({x['dates'][-1]} · 서울 {dates[-1]}) 서울 달에 맞춤", flush=True)
        code = {v: k for k, v in REGIONS[rg]["lawd"].items()}
        R[x["top"]] = {**on_dates(x["regions"][x["top"]], x["dates"], dates), "level": "region", "gus": x["gu_order"]}
        ids[x["top"]] = rg
        extra.append(x["top"])
        for sub in x["gu_order"]:
            key = f"{x['top']} {sub}"
            R[key] = {**on_dates(x["regions"][sub], x["dates"], dates), "level": "sigungu", "zone": x["top"]}
            ids[key] = code[sub]
            extra.append(key)
    names += extra
    rid_ = lambda n: rid(n, ids)
    t = max(i for i, v in enumerate(R["서울"]["score"]) if v is not None)  # 최신 달 (서울 점수가 있는 마지막 달)
    month = dates[t]

    def parent(n):
        r = R[n]
        return None if r["level"] in ("seoul", "region") else "seoul" if r["level"] == "zone" else rid_(r["zone"])

    regions = [{"id": rid_(n), "name": n, "level": R[n]["level"], "parent": parent(n),
                **({"children": [rid_(g) for g in R[n]["gus"]]} if R[n]["level"] == "zone" else {}),
                **({"children": list(ZONE_ID.values())} if n == "서울" else {}),
                **({"children": [rid_(f"{n} {g}") for g in R[n]["gus"]]} if R[n]["level"] == "region" else {})} for n in names]

    def at(s, i):
        return s[i] if 0 <= i < len(s) else None

    def chg(s, back):
        a, b = at(s, t), at(s, t - back)
        return None if a is None or b is None else round(a - b, 1)

    latest = []
    for n in names:
        r, s = R[n], R[n]["score"]
        row = {"id": rid_(n), "name": n, "level": r["level"], "score": at(s, t), "band": band(at(s, t)),
               "change": {"1m": chg(s, 1), "3m": chg(s, 3), "12m": chg(s, 12)},
               "groups": {GROUP[k]: at(v, t) for k, v in r["speed"].items()},
               "themes": {THEME[k]: at(r["themes"][k], t) for k in d["theme_order"] if k in r["themes"]}}
        if r.get("rel"):
            row["relative_strength_rank"] = at(r["rel"]["rank"], t)  # 25개 구 중 신고가 비중 순위 (1 = 가장 강함), 공포탐욕 점수와 별개
        latest.append(row)

    meta = {"month": month, "updated": updated, "engine": d["version"]}
    dump(out / "latest.json", {**meta, "regions": latest})
    dump(out / "regions.json", {"regions": regions})
    hist = {rid_(n): R[n]["score"] for n in names}
    dump(out / "history.json", {**meta, "dates": dates, "series": hist})
    for n in names:
        dump(out / "history" / f"{rid_(n)}.json", {**meta, "id": rid_(n), "name": n, "dates": dates, "scores": R[n]["score"]})
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["month", *hist])
    for i, m in enumerate(dates):
        w.writerow([m, *("" if hist[k][i] is None else hist[k][i] for k in hist)])
    (out / "history.csv").write_text(buf.getvalue(), encoding="utf-8")

    dump(out / "index.json", {
        "name": "아파트 공포탐욕지수 API",
        "description": "아파트 시장 심리를 0~100으로 나타낸 월별 지수 (0 극단적 공포, 50 중립, 100 극단적 탐욕). 서울 전체·5대 권역·25개 구와, 공개 기준을 넘은 수도권·광역시와 그 시군구.",
        **meta,
        "update_schedule": "매달 20일 09:10 (한국 시간) 전후 갱신 (자료가 덜 들어오면 22일까지 다시 받음). month = 최신 점수의 기준 달, updated = 계산한 날",
        "coverage": {"from": dates[0], "to": month, "regions": len(names), "official_from": d["official_start"]},
        "scale": [{"from": lo, "to": hi, "key": key, "label": ko} for lo, hi, key, ko in BANDS],
        "endpoints": {"index": BASE + "index.json", "regions": BASE + "regions.json", "latest": BASE + "latest.json",
                      "history": BASE + "history.json", "history_csv": BASE + "history.csv", "history_region": BASE + "history/{id}.json"},
        "ids": "seoul = 서울 전체, dosim·dongbuk·seobuk·seonam·dongnam = 도심권·동북권·서북권·서남권·동남권, 5자리 숫자 = 구·시군 (지금의 법정동 시군구 코드, 예: 11680 강남구), 영문 = 수도권·광역시 (gyeonggi·incheon·busan·daegu·gwangju·daejeon·ulsan 중 공개한 곳만, regions.json 참고)",
        "fields": {
            "score": "공포탐욕 점수 0~100 (소수 한 자리). 자료가 없는 달은 null",
            "band": "점수 구간 (scale 참고)",
            "change": "1·3·12개월 전보다 점수가 얼마나 변했는지 (점)",
            "level": "seoul 서울 전체 · zone 서울 5대 권역 · gu 서울 25개 구 · region 수도권·광역시 · sigungu 그 시군구 (상위 지역은 regions.json의 parent)",
            "groups": "속도별 3그룹 점수: leading 선행(기대·금리 변화·검색·주가), coincident 동행(가격·거래·수급), lagging 후행(가격부담·금리 수준·미분양). 서울·권역·구는 최종 점수가 세 그룹의 평균을 눈금에 맞춘 값. 수도권·광역시는 표마다 비중을 따로 줘서 최종 점수가 세 그룹 평균과 다를 수 있음 (참고용)",
            "themes": "주제별 점수: price 가격, sentiment 수급심리(중개사 설문), jeonse 전세, funding 자금(금리·대출), price_burden 가격부담(PIR·구매력·전세가율), attention 관심(검색량), markets 금융시장(건설주·KOSPI), transactions 거래, supply 공급(미분양)",
            "direction": "score·groups·themes 모두 높을수록 탐욕(과열), 낮을수록 공포(위축) 쪽. 예: price_burden이 높으면 가격 부담이 커서 과열 쪽, funding이 낮으면 금리·대출 여건이 빡빡해 위축 쪽",
            "relative_strength_rank": "서울의 구만: 같은 달 25개 구 중 신고가 비중 순위 (1 = 가장 강함). 공포탐욕 점수와 별개 지표",
        },
        "method": SITE_URL + "report/",
        "site": SITE_URL,
        "contact": "wontopiaaa@gmail.com",
        "source": "원토피아 (공포탐욕 점수는 원토피아가 원자료를 가공해 만든 자료)",
        "raw_sources": ["KB부동산", "한국부동산원 R-ONE", "국토교통부 실거래가", "청약홈", "한국은행 ECOS", "네이버 금융", "구글 트렌드"],
        "attribution": "가져다 쓰실 때는 '자료: 원토피아 아파트 공포탐욕지수'로 표기해 주세요",
        "register": SITE_URL + "api/#register",  # 키는 없고, 쓰기 전에 사용 목적·회사를 등록받는다 (register/worker.js)
        "notice": "시장 분위기를 재는 지표이며 사고팔 시점을 알려주는 신호가 아닙니다. 계산 방법과 자료가 바뀌면 과거 값도 다시 계산될 수 있습니다 (engine 참고). 서비스에 넣어 쓰시려면 위 연락처로 알려 주세요.",
    })
    return month, len(names)


if __name__ == "__main__":
    out = ROOT / "site" / "api" / "v1"
    m, n = build(out)
    print(f"api: {m} · 지역 {n}곳 · {sum(p.stat().st_size for p in out.rglob('*')) / 1e3:.0f} KB")
