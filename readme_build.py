"""README.md의 자동 칸 두 곳을 결과 파일로 다시 쓴다 (월간 갱신·지역 엔진 확정 때 함께 커밋).

- <!-- 자동: 현재 현황 --> … <!-- /자동 -->: 서울·5대 권역·25개 구와 공개한 수도권·광역시의 최신 점수
- <!-- 자동: 지역 결과 --> … <!-- /자동 -->: 지역 엔진(임시·최종)과 지역별 교차검증 성적, 임시 엔진의 새 지역 시험 성적
읽는 파일: results_zone/map_data.json·update_summary.json, results_region/summary.json·engine_study.json, data/region_engine.json
"""
import json
import re
from pathlib import Path

from regions import REGIONS, josa

ROOT = Path(__file__).parent
f2 = lambda v: "–" if v is None else f"{v:.2f}".replace("-", "−")
f1 = lambda v: "–" if v is None else f"{v:.1f}"


def band(v):
    return "극단적 공포" if v < 25 else "공포" if v < 45 else "중립" if v < 55 else "탐욕" if v < 75 else "극단적 탐욕"


def load(rel):
    p = ROOT / rel
    return json.loads(p.read_text()) if p.exists() else None


def current():
    m = load("results_zone/map_data.json")
    R, run = m["regions"], load("results_zone/update_summary.json")["run"]
    t = max(i for i, v in enumerate(R["서울"]["score"]) if v is not None)
    ym = m["dates"][t]
    zones = ["도심권", "동북권", "서북권", "서남권", "동남권"]
    gus = {g: R[g]["score"][t] for g in m["gu_order"] if R[g]["score"][t] is not None}
    lo, hi = min(gus, key=gus.get), max(gus, key=gus.get)
    rk = sorted((R[g]["rel"]["rank"][t], g) for g in m["gu_order"] if R[g].get("rel") and R[g]["rel"]["rank"][t] is not None)
    lines = [f"## 현재 현황 ({run[:4]}년 {int(run[4:6])}월 {int(run[6:8])}일 기준)", "", f"### 지금 점수 ({ym[:4]}년 {int(ym[5:7])}월)",
             "| 지역 | 점수 | 구간 |", "|---|---|---|",
             f"| 서울 전체 | {f1(R['서울']['score'][t])} | {band(R['서울']['score'][t])} |",
             f"| 5대 권역 (도심·동북·서북·서남·동남) | {' · '.join(f1(R[z]['score'][t]) for z in zones)} | {' · '.join(band(R[z]['score'][t]) for z in zones)} |",
             f"| 25개 구 | {f1(gus[lo])}({lo}) ~ {f1(gus[hi])}({hi}) | |"]
    summ = load("results_region/summary.json") or {}
    live = sorted(((x["score"], r) for r, x in summ.items() if x["publish"]), reverse=True)
    lines += [f"| {REGIONS[r]['name']} ({summ[r]['n_sub']}개 {summ[r]['sub_word']}) | {f1(v)} | {band(v)} |" for v, r in live]
    wait = [REGIONS[r]["name"] for r in REGIONS if not summ.get(r, {}).get("publish")]
    lines += [""]
    if rk:
        lines += [f"- 서울 안 상대 강도(신고가 비중 순위)는 {'·'.join(g for _, g in rk[:3])}가 1~3위, {rk[-1][1]}가 {rk[-1][0]}위예요."]
    if wait:
        lines += [f"- {'·'.join(wait)}{josa(wait[-1], '은', '는')} 아직 검증 중이라 점수를 공개하지 않아요 (아래 '수도권·광역시 확장')."]
    lines += ["- 최신 점수는 매달 `results_zone/update_summary.json`(서울)과 `results_region/summary.json`(수도권·광역시)에 기록돼요."]
    return lines


def regional():
    eng, summ, st = load("data/region_engine.json"), load("results_region/summary.json") or {}, load("results_region/engine_study.json")
    seoul_acc = load("results_zone/map_data.json")["regions"]["서울"]["acc"]
    if not eng:
        return ["**지역 엔진**: 아직 고정 전이라 서울과 같은 엔진을 써요."]
    kind = "임시" if eng.get("provisional") else "최종"
    lines = [f"**지역 엔진 ({kind})**: '{eng['name']}' — {eng['chosen']}에 {len(eng['regions'])}개 지역"
             f"({'·'.join(REGIONS[r]['name'] for r in eng['regions'])})으로 골라 고정했어요."]
    if eng.get("provisional"):
        lines[0] += (" 실거래가 다 들어오지 않은 지역이 있어 먼저 쓰는 임시 엔진이에요. 7개 지역이 다 모이면 임시 엔진을 고를 때 안 본 지역에 "
                     "그대로 써 본 성적을 남기고, 7개 지역으로 다시 골라 최종으로 고정해요(공개된 점수도 그때 한 번 더 바뀌어요).")
    prev = eng.get("previous")
    if prev and prev.get("holdout"):
        lines += ["", f"임시 엔진('{prev['name']}', {prev['chosen']}, {len(prev['regions'])}개 지역으로 고름)을 고를 때 안 본 지역에 그대로 쓴 성적:"]
        lines += [f"- {REGIONS[h]['name']}: 정확도 {f2(r['acc'])}, 5년 구간 중앙값 {f2(r['win_median'])}, 2019년 이후 {f2(r['recent'])}"
                  for h, r in prev["holdout"].items()]
    base = (st or {}).get("loro", {})
    lines += ["", f"**지금 결과** (정확도는 그 지역을 빼고 고른 엔진으로 잰 교차검증 성적, 공개 기준 0.40·5년 구간 중앙값 0.25)",
              "| 지역 | 지금 점수 | 교차검증 정확도 | 5년 구간 중앙값 | 2019년 이후 | 서울과 같은 엔진이면 | 서울 지수를 그대로 쓰면 | 상태 |",
              "|---|---|---|---|---|---|---|---|"]
    loro = eng.get("loro") or {}
    rows = sorted(loro.items(), key=lambda kv: -(kv[1].get("acc") if kv[1].get("acc") is not None else -9))
    for r, lo in rows:
        x, b = summ.get(r, {}), base.get(r, {}).get("base", {})
        score = x.get("score") if x.get("publish") else None  # 공개 기준을 못 넘은 지역은 점수를 쓰지 않는다
        lines.append(f"| {REGIONS[r]['name']} | {f1(score)} | {f2(lo.get('acc'))} | {f2(lo.get('win_median'))} | {f2(lo.get('recent'))} | "
                     f"{f2(b.get('acc'))} / {f2(b.get('win_median'))} | {f2(x.get('acc_seoul'))} | {'공개' if x.get('publish') else '검증 중'} |")
    for why, rest in (("엔진 확정 대기", [REGIONS[r]["name"] for r in REGIONS if r not in loro and r in summ]),
                      ("실거래 받는 중", [REGIONS[r]["name"] for r in REGIONS if r not in loro and r not in summ])):
        if rest:
            lines.append(f"| {'·'.join(rest)} | | {why} | | | | | 검증 중 |")
    sc = eng.get("seoul_check") or {}
    lines += ["", f"지역 엔진을 학습에 안 쓴 서울에 써 보면 {f2(sc.get('acc'))}이라(서울 엔진 {f2(seoul_acc)}) 서울은 서울 엔진을 그대로 써요."]
    if eng.get("weights"):
        lines[-1] += " 비중이 큰 표는 KB 매수우위·전세수급·거래활발 같은 중개사 설문이라 KB 자료 의존이 커져요."
    return lines


def put(text, tag, lines):
    pat = re.compile(rf"(<!-- 자동: {tag}[^>]*-->\n).*?(\n<!-- /자동 -->)", re.S)
    assert pat.search(text), f"README에 '{tag}' 칸이 없음"
    return pat.sub(lambda mt: mt.group(1) + "\n".join(lines) + mt.group(2), text)


if __name__ == "__main__":
    p = ROOT / "README.md"
    s = put(p.read_text(), "현재 현황", current())
    s = put(s, "지역 결과", regional())
    p.write_text(s)
    print("README 자동 칸 갱신")
