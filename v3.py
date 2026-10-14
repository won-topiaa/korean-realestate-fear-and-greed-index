"""v3 엔진: 고정 구성(2009년까지 시작한 지표) + 검색량 부족 구간 제외 + 속도별 3그룹 동일가중 + 완만한 펴기.

펴기: 점수 = 50 + 1.5 × (원점수 − 50), 0~100으로 자름. 그때그때 평균·표준편차로 펴면 시기마다 눈금이 달라져
정확도가 떨어져서(0.40 → 0.31) 고정 배율을 쓴다.
"""
import numpy as np
import pandas as pd

import backtest as bt
import timing

NOT_REALTIME = ("공급_분양물량", "공급_향후입주역수")
AUX = ["설문_가격전망", "설문_부동산원매매수급", "설문_국토연소비심리", "전세_가격전망", "전세_부동산원전세수급",
       "거래_2030비중", "청약_1순위경쟁률", "청약_미달역수", "청약_무순위경쟁률", "청약_실제공급", "설문_주택가격전망CSI"]  # 이력이 짧아 보조 지표로
SPEED = ["선행", "동행", "후행"]
TREND_KW = {"관심_아파트": ["아파트"], "관심_부동산": ["부동산"], "관심_집값": ["집값"], "관심_청약": ["청약"],
            "관심_갭투자": ["갭투자"], "관심_공포어역수": ["급매", "미분양"]}
MIN_SEARCH = 5


def load_meta():
    meta = pd.read_csv(bt.ROOT / "data" / "indicator_meta.csv", index_col=0).fillna("")
    meta = meta.loc[[c for c in meta.index if c not in NOT_REALTIME]]
    return meta.loc[[c for c in meta.index if c not in AUX]], meta.loc[[c for c in AUX if c in meta.index]]


def search_ok(index):
    m = pd.DataFrame(True, index=index, columns=list(TREND_KW))
    for c, kws in TREND_KW.items():
        vol = sum(pd.read_csv(bt.ROOT / "data" / "raw" / "trends" / f"{k}.csv", index_col=0, parse_dates=True).iloc[:, 0] for k in kws)
        ok = vol.rolling(24).mean() >= MIN_SEARCH
        if c in timing.LAG1:
            ok = ok.shift(1)  # 지표를 1개월 늦췄으므로 판정도 같은 시점으로
        m[c] = ok.reindex(index).fillna(False).astype(bool)
    return m


K = 1.5  # 펴기 배율 (2026-10-13 확정, 바꾸지 않음)


def spread(x):
    """고정 배율 펴기: 50을 중심으로 눈금만 1.5배. 시점마다 같은 변환이라 순서(정확도)가 그대로다."""
    return (50 + K * (x - 50)).clip(0, 100)


def scores(raw):
    raw = raw.copy()
    kw = [c for c in TREND_KW if c in raw.columns]
    raw[kw] = raw[kw].where(search_ok(raw.index)[kw])
    return raw.apply(bt.pct_score)


VERSION = "v3.3"  # 2026-10-14: 신고가·급락은 해제·직거래 표시 전후로 같은 정의(모든 거래), 급락은 직전 다른 날과 비교, 미분양 2개월 늦춤, 권역·구 표 구성 통일.
#   v3.2: 자금 지표를 한국은행 원자료로. v3.1: 공개 시차, 신고가·급락 정의, 같은 출처 한 표. (점수화 기간 10년은 7·15년·누적과 비교해 유지)
OFFICIAL_START = "2011-02-01"  # 이 달부터 표의 90% 이상이 갖춰짐 (이전은 구성 불완전 · 참고용)
# 같은 원자료에서 나온 지표는 한 표 (같은 속도 그룹 안). 결과를 보기 전에 정한 기준으로 고름 (eval_structure.py)
MERGE = {"가격_상승구비율": "가격_3개월모멘텀",        # KB 매매가격지수 (서울·구)
         "거래_원정매수비중": "거래_외지인비중",        # 부동산원 매입자 거주지별 통계
         "거래_급락거래역수": "거래_신고가비중",        # 국토부 실거래
         "시장_건설주상대강도": "시장_건설주모멘텀"}     # 건설주 바스켓
DROP = ["전세_매매선호"]                              # 매수우위 ÷ 전세수급 — 이미 둘 다 들어 있음
GOOGLE = "관심_구글"                                   # 구글 트렌드 검색어 6개 → 한 표


def votes(sc, meta):
    """지표 점수 → 표(vote) 점수와 표의 메타."""
    cols = [c for c in meta.index if c in sc.columns and c not in DROP]
    groups = {}
    for c in cols:
        head = GOOGLE if c.startswith("관심_") else MERGE.get(c, c)
        groups.setdefault(head, []).append(c)
    V = pd.DataFrame({h: sc[cs].mean(axis=1, skipna=True) for h, cs in groups.items()})
    M = pd.DataFrame({h: meta.loc[cs[0]] for h, cs in groups.items()}).T
    M["구성"] = [", ".join(groups[h]) for h in M.index]
    return V, M


def compute(raw, meta, aux_meta=None):
    """raw: 지표 원값(열=지표). 반환: 펴기 전·후 지수, 그룹·주제(펴기 후), 보조 지표 점수, 표 구성."""
    sc = scores(raw[[c for c in meta.index if c in raw.columns]])
    V, M = votes(sc, meta)
    groups = {v: V[M.index[M["속도"] == v]].mean(axis=1, skipna=True) for v in SPEED}
    core = pd.concat(groups.values(), axis=1).mean(axis=1)
    themes = {t: V[M.index[M["주제"] == t]].mean(axis=1, skipna=True) for t in M["주제"].unique()}
    aux = raw[[c for c in (aux_meta.index if aux_meta is not None else []) if c in raw.columns]].apply(bt.pct_score) if aux_meta is not None else None
    return {"core": core, "final": spread(core), "groups": {k: spread(v) for k, v in groups.items()},
            "themes": {k: spread(v) for k, v in themes.items()}, "aux": aux, "votes": V, "vote_meta": M,
            "n_votes_available": V.notna().sum(axis=1)}


if __name__ == "__main__":
    P3 = [("2006-01-01", "2012-12-01"), ("2013-01-01", "2019-12-01"), ("2020-01-01", "2026-12-01")]
    raw = pd.read_csv(bt.ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)
    raw = raw[raw.index <= raw["__price"].last_valid_index()]
    meta, aux_meta = load_meta()
    r = compute(raw, meta, aux_meta)
    tg = pd.read_csv(bt.ROOT / "data" / "targets_extra.csv", index_col=0, parse_dates=True)
    rs = tg["실거래지수"].reindex(raw.index)
    y = np.log(rs).shift(-12) - np.log(rs)
    for nm in ["core", "final"]:
        s = r[nm].reindex(raw.index)
        ics = [bt.spearman(s[bt.window_mask(s.index, w)].to_numpy(), y[bt.window_mask(s.index, w)].to_numpy()) for w in P3]
        print(nm, "지표", len(meta), "| 3구간", np.round(ics, 2), "| 현재", round(s.dropna().iloc[-1], 1))
    f = r["final"]; f = f[f.index >= "2006-01-01"]
    print("구간 분포(%):", [round(((f >= a) & (f < b)).mean() * 100) for a, b in [(0, 25), (25, 45), (45, 55), (55, 75), (75, 101)]])
    yy = y.reindex(f.index)
    for a, b, lab in [(0, 25, "극단적 공포"), (25, 45, "공포"), (45, 55, "중립"), (55, 75, "탐욕"), (75, 101, "극단적 탐욕")]:
        sel = (f >= a) & (f < b) & yy.notna()
        print(f"  {lab}: 이후 12개월 {np.expm1(yy[sel].mean())*100:+.1f}% · 상승 {((yy[sel] > 0).mean())*100:.0f}% · {sel.sum()}개월")
    for d in ["2008-12", "2012-12", "2018-09", "2020-07", "2021-09", "2022-11", "2024-05", "2026-09"]:
        print(d, round(r["core"].get(pd.Timestamp(d + "-01")), 1), "→", round(f.get(pd.Timestamp(d + "-01")), 1))
    pd.to_pickle(r, bt.ROOT / "results_v2" / "v3_seoul.pkl")
