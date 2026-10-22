"""수도권·광역시 공포탐욕지수 지표: 시도와 시군구.

서울 엔진(v3)과 같은 25표를 쓰고, 지역 값이 있는 지표는 그 지역 값으로 바꾼다.
- KB 시도: 매매·전세지수 변화, 12개월 이동평균 괴리, 설문(매수우위·거래활발·전세수급·가격 전망), 전세가율
- KB 시군구 매매지수: 오른 시군구 비율 (구로 나뉜 시는 구만 센다)
- 부동산원: 거래량, 매입자 거주지(타 시도 = 서울 + 기타)·연령·거래주체, 수급지수, 미분양
- 국토부 실거래(지역 저장소): 신고가·급락 비중, 정답(반복매매지수)
- KB 주택구매력: 경기는 경기, 인천은 수도권, 광역시는 6개광역시 값. PIR은 KB에 서울·전국만 있어 전국 값. 청약(보조)은 그 지역.
나머지(금리·가계신용·검색량·주가·선도아파트50·주택가격전망 CSI)는 전국 공통 값이라 서울 지표 파일의 같은 열을 쓴다.
지역 자료가 서울보다 늦게 시작해도 서울 값으로 채우지 않는다 (시장이 달라서). 그 기간은 그 표 없이 계산된다.
시군구: KB 시군구 매매·전세지수·전세가율, 부동산원 시군구 거래 통계, 실거래는 그 시군구 값이고, 설문·수급·미분양·오른 비율은
시도 값. 시군구 자료가 시작되기 전까지는 시도 값 (서울 구와 같은 규칙).
결과: results_region/region_calc.pkl
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

import build_indicators as B
import extra_indicators as E
import molit_indicators as MI
import region_store
import region_supply as RS
import timing
from regions import REGIONS
from zone_index import reb_file

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "results_region"
OUT.mkdir(exist_ok=True)
NOT_REALTIME = ("공급_분양물량", "공급_향후입주역수")
OFFICIAL = pd.Timestamp("2011-02-01")  # 서울 공식 기록 시작 (시군구 자기 값 판단에 씀)
COMMON_PREFIX = ("자금_", "관심_", "시장_")
COMMON = ["가격_선도50모멘텀", "설문_주택가격전망CSI"]
HAI_REGION = {"gyeonggi": "경기", "incheon": "수도권"}  # 나머지(광역시)는 6개광역시
REB_COLS = ["거래_거래량", "거래_거래량증가", "거래_외지인비중", "거래_원정매수비중", "거래_2030비중", "거래_법인매수비중",
            "공급_미분양역수", "설문_부동산원매매수급", "전세_부동산원전세수급"]
APPLY_COLS = ["청약_1순위경쟁률", "청약_미달역수", "청약_무순위경쟁률", "청약_실제공급"]
KB_COLS = ["가격_3개월모멘텀", "가격_12개월이평괴리", "가격_상승구비율", "설문_매수우위", "설문_매수우위변화", "설문_거래활발",
           "설문_가격전망", "전세_수급", "전세_가격전망", "전세_매매선호", "전세_3개월모멘텀", "부담_전세가율역수"]
# 수준이 시군구마다 다른 지표: 자기 자료가 늦게 시작한 시군구(부천·화성의 구, 인천 새 구 등)는 그 전의 시도 값을 시작 무렵의 차이만큼 옮겨 잇는다
LEVEL = ["부담_전세가율역수", "거래_외지인비중", "거래_원정매수비중", "거래_2030비중", "거래_법인매수비중"]
SUB_OWN = ["가격_3개월모멘텀", "가격_12개월이평괴리", "전세_3개월모멘텀", "부담_전세가율역수",
           "거래_거래량", "거래_거래량증가", "거래_외지인비중", "거래_원정매수비중", "거래_2030비중", "거래_법인매수비중"]


def kb_panel(name, rid):
    """KB 시군구 패널 (region_src_fetch.py가 받은 data/raw/kb/{통계}_{지역id}.json)."""
    d = json.loads((RAW / "kb" / f"{name}_{rid}.json").read_text())
    dates = pd.to_datetime(pd.Series(d["날짜리스트"]), format="%Y%m")
    return pd.DataFrame({x["지역명"]: pd.Series(x["dataList"][: len(dates)], index=dates, dtype=float) for x in d["데이터리스트"]})


def up_share(panel):
    """전월보다 오른 시군구 비율. 구로 나뉜 시(수원시 등)는 구가 있는 달에는 시를 빼고 구를 센다. 절반 넘게 비면 빈 값."""
    diff = panel.diff()
    up = (diff > 0).where(diff.notna())
    for p in panel.columns:
        kids = [c for c in panel.columns if c.startswith(p + " ")]
        if kids:
            up.loc[up[kids].notna().any(axis=1), p] = np.nan
    n = up.notna().sum(axis=1)
    return up.mean(axis=1).where(n >= max(3, 0.5 * n.max()))


def reb(name, cls=None):
    """부동산원 파일. name이 목록이면 있는 파일들의 합 (시군구 합으로 만드는 시도 값)."""
    if isinstance(name, list):
        parts = [x for x in (reb(n, cls) for n in name) if x is not None]
        return sum(p if cls is None else p.fillna(0) for p in parts) if parts else None
    return reb_file(name, cls) if (RAW / "reb" / f"{name}.json").exists() else None


def trade_cols(ind, prefix):
    """부동산원 거래 통계 → 거래 지표 (서울 extra_indicators·zone_index와 같은 정의). 파일이 없으면 그대로 둔다.
    prefix가 목록이면 그 시군구들의 합으로."""
    f = (lambda s: [f"{p}_{s}" for p in prefix]) if isinstance(prefix, list) else (lambda s: f"{prefix}_{s}")
    vol = reb(f("거래량"))
    if vol is not None:
        ind["거래_거래량"] = np.log(vol.rolling(3).mean() / vol.rolling(60, min_periods=36).mean())
        ind["거래_거래량증가"] = np.log(vol.rolling(3).sum() / vol.rolling(3).sum().shift(12))
    res = reb(f("매입자거주지"), True)
    if res is not None:
        out = res.get("관할시도외_서울", 0) + res["관할시도외_기타"]
        ind["거래_외지인비중"] = (out / res["합계"]).rolling(3).mean()
        ind["거래_원정매수비중"] = (1 - res["관할시군구내"] / res["합계"]).rolling(3).mean()
    age = reb(f("매입자연령"), True)
    if age is not None:
        ind["거래_2030비중"] = ((age["20대이하"] + age["30대"]) / age["합계"]).rolling(3).mean()
    subj = reb(f("거래주체"), True)
    if subj is not None:
        corp = subj[[c for c in subj.columns if c.endswith("→법인")]].sum(axis=1)
        ind["거래_법인매수비중"] = (corp / subj["합계"]).rolling(3).mean()
    for k in ("거래_거래량", "거래_거래량증가", "거래_외지인비중", "거래_원정매수비중", "거래_2030비중", "거래_법인매수비중"):
        if k in ind:  # 거래가 0건인 달(섬 지역 등)의 log(0)·0으로 나누기 → 빈 값 (무한대가 백분위 끝에 박히지 않게)
            ind[k] = ind[k].replace([np.inf, -np.inf], np.nan)


def cut_outsider(df, rid):
    """시도가 합쳐져 매입자 거주지의 '관할시도외'가 넓은 시도 기준이 된 달부터 외지인 비중을 비운다 (광주: 2026-07 전남광주 통합)."""
    brk = REGIONS[rid].get("outsider_break")
    if brk and "거래_외지인비중" in df.columns:
        df.loc[df.index >= brk, "거래_외지인비중"] = np.nan  # 발표 지연으로 늦춘 뒤라 통합 뒤 자료가 섞인 달은 모두 이 뒤
    return df


def region_indicators(rid, common, cols):
    d = REGIONS[rid]
    nm, idx = d["kb"], common.index
    ind = {}
    p = B.kb_aligned("아파트매매지수_월간", nm)
    ind["가격_3개월모멘텀"] = np.log(p).diff(3)
    ind["가격_12개월이평괴리"] = p / p.rolling(12).mean() - 1
    panel = kb_panel("아파트매매지수_월간", rid)
    if d.get("kb_sub_lawd_only"):  # 광주: KB 지역코드가 통합 전남광주라 옛 광주 다섯 구만
        panel = panel[[c for c in panel.columns if c in d["lawd"].values()]]
    ind["가격_상승구비율"] = up_share(panel).rolling(3).mean()
    buy = B.kb_survey("매수우위_월간", "매수우위지수", nm)
    js = B.kb_survey("전세수급_월간", "전세수급지수", nm)
    ind["설문_매수우위"] = buy
    ind["설문_매수우위변화"] = buy.diff(3)
    ind["설문_거래활발"] = B.kb_survey("매매거래활발_월간", "매매거래지수", nm)
    ind["설문_가격전망"] = B.kb_survey("매매가격전망_월간", "매매상승하락전망지수", nm)
    ind["전세_수급"] = js
    ind["전세_가격전망"] = B.kb_survey("전세가격전망_월간", "전세상승하락전망지수", nm)
    ind["전세_매매선호"] = buy / js
    ind["전세_3개월모멘텀"] = np.log(B.kb_aligned("아파트전세지수_월간", nm)).diff(3)
    ind["부담_전세가율역수"] = -B.kb_aligned("전세가율_아파트", nm)
    ind["부담_PIR"] = timing.quarterly_release(B.kb_pir(region="전국"))  # 분기마다 공개된 달부터 (서울과 같게)
    ind["부담_구매력역수"] = timing.quarterly_release(-B.kb_hai(HAI_REGION.get(rid, "6개광역시"))[1])
    subs = [f"r_{lawd}" for lawd in d["lawd"]] if d.get("reb_sum_subs") else None
    trade_cols(ind, subs or f"r_{rid}")
    unsold = reb([f"{p}_미분양" for p in subs] if subs else f"r_{rid}_미분양")
    ind["공급_미분양역수"] = -np.log1p(unsold) if unsold is not None else np.nan
    for k, f in [("설문_부동산원매매수급", "매매수급"), ("전세_부동산원전세수급", "전세수급")]:
        s = reb(f"r_{rid}_{f}")
        ind[k] = s if s is not None else np.nan
    ah = E.applyhome_monthly(d["name"])
    for c in APPLY_COLS:
        ind[c] = ah[c]
    df = pd.DataFrame({k: (v.reindex(idx) if isinstance(v, pd.Series) else pd.Series(v, index=idx)) for k, v in ind.items()})
    df = df.ffill(limit=3)  # 서울과 같은 규칙: 발표가 늦은 달은 최근 값으로 3개월까지
    df = cut_outsider(timing.apply(df, cols=REB_COLS + APPLY_COLS), rid)
    for c in cols:
        if c.startswith(COMMON_PREFIX) or c in COMMON:
            df[c] = common[c]
    df["설문_국토연소비심리"] = np.nan  # 서울 값만 받음 (보조 지표)
    df = df.reindex(columns=cols)
    if rid in RS.EXTRA:  # 공급 보정 지역: 착공 물량 표 (시군구도 이 시도 값을 그대로 씀)
        df[RS.COL] = RS.indicator(rid, idx)
    return df


def sub_indicators(rid, lawd, reg):
    """시군구: 자기 값이 있는 지표만 바꾸고, 자료가 시작되기 전까지는 시도 값."""
    name, idx = REGIONS[rid]["lawd"][lawd], reg.index
    own = {}
    for col, kbn, fn in [("가격_3개월모멘텀", "아파트매매지수_월간", lambda p: np.log(p).diff(3)),
                         ("가격_12개월이평괴리", "아파트매매지수_월간", lambda p: p / p.rolling(12).mean() - 1),
                         ("전세_3개월모멘텀", "아파트전세지수_월간", lambda p: np.log(p).diff(3)),
                         ("부담_전세가율역수", "전세가율_아파트", lambda p: -p)]:
        panel = kb_panel(kbn, rid)
        if name in panel.columns:
            own[col] = fn(panel[name])
    trade_cols(own, f"r_{lawd}")
    o = pd.DataFrame({k: v.reindex(idx) for k, v in own.items()}, index=idx).ffill(limit=3)
    o = cut_outsider(timing.apply(o, cols=REB_COLS), rid)
    ind = reg.copy()
    for c in o.columns:
        first = o[c].first_valid_index()
        if first is None:
            continue
        after = ind.index >= first
        if c in LEVEL:  # 그 전의 시도 값은 시작 6개월의 평균 차이만큼 옮긴다 (그대로 이으면 백분위가 한쪽 끝에 몰림)
            w = after & (ind.index < first + pd.DateOffset(months=6))
            gap = (o.loc[w, c] - ind.loc[w, c]).mean()
            if pd.notna(gap):
                ind.loc[~after, c] += gap
        ind.loc[after, c] = o.loc[after, c]
    # 자기 값으로 치는 표: 공식 기록 시작(2011년 2월) 뒤 절반 넘는 달에 그 시군구 값이 있을 때만 (최근 몇 달만 있으면 시도 값과 같음)
    return ind, [c for c in o.columns if o.loc[o.index >= OFFICIAL, c].notna().mean() > 0.5]


def build_target(ind, sub, sub_all, idx):
    """실거래 → 신고가·급락 지표(신고 기한만큼 늦춤: 1개월, 2020년 2월 전 2개월)와 정답(반복매매지수, 최근 2개월 제외)."""
    rs, pairs = MI.repeat_sales(sub)
    hi, dr, _ = MI.high_low(sub_all)
    ind["거래_신고가비중"] = timing.trade_lag(hi.rolling(3).mean()).reindex(idx)  # 신고 기한만큼 (2020년 2월 전 2개월, 뒤 1개월)
    ind["거래_급락거래역수"] = timing.trade_lag(-dr.rolling(3).mean()).reindex(idx)
    rs.iloc[-2:] = np.nan
    rs = rs.reindex(idx)
    y = timing.fwd(rs)  # 발표한 달부터 12개월
    s = sub.sort_values(["key", "date"])
    n_pairs = s[s.duplicated("key", keep="first")].groupby("date").size().reindex(idx).fillna(0)
    return rs, y, n_pairs


def main(rids=None):
    meta = pd.read_csv(ROOT / "data" / "indicator_meta.csv", index_col=0).fillna("")
    cols = [c for c in meta.index if c not in NOT_REALTIME]
    seoul = pd.read_csv(ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)
    common = seoul[seoul.index <= seoul["__price"].last_valid_index()]  # KB 최신월까지
    idx = common.index
    have = region_store.regions_in_store()
    out, subs = {}, {}
    for rid in rids or have:
        d = REGIONS[rid]
        raw = region_store.load(rid)
        trades = MI.load(df=raw)
        tall = MI.load(market_only=False, df=raw)
        reg = region_indicators(rid, common, cols)
        rs, y, npairs = build_target(reg, trades, tall, idx)
        value = trades.groupby(["lawd", "date"])["price"].sum().unstack(0).reindex(idx).fillna(0)
        out[rid] = {"ind": reg, "rs": rs, "fwd12": y, "pairs": npairs, "n_trades": len(trades)}
        w = value.rolling(12).sum().shift(2)
        for lawd in d["lawd"]:
            si, own = sub_indicators(rid, lawd, reg)
            st, sa = trades[trades["lawd"] == lawd], tall[tall["lawd"] == lawd]
            thin = len(st) < 50  # 거래가 거의 없는 곳 (섬 지역 등)
            if not thin:
                full = si.copy()
                srs, sy, sp = build_target(full, st, sa, idx)
                # 반복매매 쌍이 없는 달이 많으면 그 달 가격지수가 기준값으로 튄다 (군위군: 2011년 이후 44%) → 정답·신고가 없이
                thin = (sp[sp.index >= "2011-01-01"] == 0).mean() > 0.2
            first = st["date"].min() if len(st) else None  # 첫 거래 달 (행정구역이 바뀐 곳의 옛 거래가 지금 코드로 왔는지 확인용)
            if thin:
                subs[lawd] = {"region": rid, "ind": si, "rs": None, "fwd12": None, "pairs": None, "own": own, "n_trades": len(st), "first": first}
                continue
            si = full
            own += ["거래_신고가비중", "거래_급락거래역수"]
            subs[lawd] = {"region": rid, "ind": si, "rs": srs, "fwd12": sy, "pairs": sp, "own": own, "n_trades": len(st), "first": first}
        out[rid]["sub_weight"] = w
        print(f"{d['name']}: 거래 {len(trades):,}건 · 반복매매 쌍 월 중앙값(2011~) {int(npairs[npairs.index >= '2011-01-01'].median())} · "
              f"실거래 지수 {rs.dropna().index[-1].date()}까지 · 시군구 {len(d['lawd'])}곳", flush=True)
    return out, subs


if __name__ == "__main__":
    out, subs = main()
    pd.to_pickle({"regions": out, "subs": subs}, OUT / "region_calc.pkl")
