"""서울 5대 권역별 공포탐욕지수 (v2 방식: 45개 지표, 속도별 3그룹 균등).

권역 값이 있는 지표는 권역 값으로 바꾸고(가격·거래·수급·전세·미분양·신고가 등),
없는 지표(금리·검색량·주가·청약·PIR 등)는 서울 공통 값을 쓴다. 점수는 권역마다 자기 과거 기준 백분위.
정답: 권역별 실거래 반복매매지수. 서울 전체 = 권역 점수의 최근 12개월 거래금액 가중평균.
결과: results_zone/zone_data.json
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

import backtest as bt
import timing
import molit_indicators as MI
from zone_fetch import ZONES

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "results_zone"
OUT.mkdir(exist_ok=True)
GU2ZONE = {g: z for z, gs in ZONES.items() for g in gs}
KB_SIDE = {"도심권": "강북14개구", "동북권": "강북14개구", "서북권": "강북14개구", "서남권": "강남11개구", "동남권": "강남11개구"}
NOT_REALTIME = ("공급_분양물량", "공급_향후입주역수")
P3 = [("2006-01-01", "2012-12-01"), ("2013-01-01", "2019-12-01"), ("2020-01-01", "2026-12-01")]
LAWD2GU = {"11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구", "11215": "광진구", "11230": "동대문구",
           "11260": "중랑구", "11290": "성북구", "11305": "강북구", "11320": "도봉구", "11350": "노원구", "11380": "은평구",
           "11410": "서대문구", "11440": "마포구", "11470": "양천구", "11500": "강서구", "11530": "구로구", "11545": "금천구",
           "11560": "영등포구", "11590": "동작구", "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구", "11740": "강동구"}


def kb_gu(name):
    d = json.loads((RAW / "kb" / f"{name}.json").read_text())
    dates = pd.to_datetime(pd.Series(d["날짜리스트"]), format="%Y%m")
    return pd.DataFrame({x["지역명"]: pd.Series(x["dataList"][: len(dates)], index=dates, dtype=float) for x in d["데이터리스트"]})


def kb_side(name, field, side):
    from build_indicators import kb_survey
    return kb_survey(name, field, region=side)


def reb_file(name, cls=None):
    d = pd.DataFrame(json.loads((RAW / "reb" / f"{name}.json").read_text()))
    d["date"] = pd.to_datetime(d["WRTTIME_IDTFR_ID"], format="%Y%m")
    if cls is None:
        return d.groupby("date")["DTA_VAL"].sum().astype(float)
    return d.pivot_table(index="date", columns="CLS_NM", values="DTA_VAL", aggfunc="sum").astype(float)


def zone_chain(panel, gus):
    """구별 지수 → 권역 지수 (구별 월간 로그변화의 평균을 누적)."""
    ch = np.log(panel[gus]).diff().mean(axis=1, skipna=True)
    return np.exp(ch.fillna(0).cumsum()).where(panel[gus].notna().any(axis=1))


KB_REPLACED = ["가격_3개월모멘텀", "가격_12개월이평괴리", "가격_상승구비율", "설문_매수우위", "설문_매수우위변화", "설문_거래활발",
               "설문_가격전망", "전세_수급", "전세_가격전망", "전세_매매선호", "전세_3개월모멘텀", "부담_전세가율역수"]


def zone_indicators(z, seoul_ind):
    gus = ZONES[z]
    side = KB_SIDE[z]
    ind = seoul_ind.copy()
    price_gu = kb_gu("아파트매매지수_월간_서울구")
    zp = zone_chain(price_gu, gus)
    ind["가격_3개월모멘텀"] = np.log(zp).diff(3)
    ind["가격_12개월이평괴리"] = zp / zp.rolling(12).mean() - 1
    up = (price_gu[gus].diff() > 0).where(price_gu[gus].diff().notna())
    ind["가격_상승구비율"] = up.mean(axis=1).rolling(3).mean()
    buy = kb_side("매수우위_월간", "매수우위지수", side)
    js = kb_side("전세수급_월간", "전세수급지수", side)
    ind["설문_매수우위"] = buy
    ind["설문_매수우위변화"] = buy.diff(3)
    ind["설문_거래활발"] = kb_side("매매거래활발_월간", "매매거래지수", side)
    ind["설문_가격전망"] = kb_side("매매가격전망_월간", "매매상승하락전망지수", side)
    ind["전세_수급"] = js
    ind["전세_가격전망"] = kb_side("전세가격전망_월간", "전세상승하락전망지수", side)
    ind["전세_매매선호"] = buy / js
    ind["전세_3개월모멘텀"] = np.log(zone_chain(kb_gu("아파트전세지수_월간_서울구"), gus)).diff(3)
    ind["부담_전세가율역수"] = -kb_gu("전세가율_아파트_서울구")[gus].mean(axis=1)
    ind["설문_부동산원매매수급"] = reb_file(f"zone_매매수급_{z}")
    ind["전세_부동산원전세수급"] = reb_file(f"zone_전세수급_{z}")
    vol = sum(reb_file(f"gu_거래량_{g}") for g in gus)
    ind["거래_거래량"] = np.log(vol.rolling(3).mean() / vol.rolling(60, min_periods=36).mean())
    ind["거래_거래량증가"] = np.log(vol.rolling(3).sum() / vol.rolling(3).sum().shift(12))
    res = sum(reb_file(f"gu_매입자거주지_{g}", cls=True) for g in gus)
    ind["거래_외지인비중"] = (res["관할시도외_기타"] / res["합계"]).rolling(3).mean()
    ind["거래_원정매수비중"] = (1 - res["관할시군구내"] / res["합계"]).rolling(3).mean()
    age = sum(reb_file(f"gu_매입자연령_{g}", cls=True) for g in gus)
    ind["거래_2030비중"] = ((age["20대이하"] + age["30대"]) / age["합계"]).rolling(3).mean()
    subj = sum(reb_file(f"gu_거래주체_{g}", cls=True) for g in gus)
    corp = subj[[c for c in subj.columns if c.endswith("→법인")]].sum(axis=1)
    ind["거래_법인매수비중"] = (corp / subj["합계"]).rolling(3).mean()
    ind["공급_미분양역수"] = -np.log1p(sum(reb_file(f"gu_미분양_{g}") for g in gus))
    replaced = ["거래_거래량", "거래_거래량증가", "거래_외지인비중", "거래_원정매수비중", "거래_2030비중", "거래_법인매수비중",
                "공급_미분양역수", "설문_부동산원매매수급", "전세_부동산원전세수급"]
    zone_cols = [c for c in ind.columns if c in replaced or c in KB_REPLACED]
    ind[zone_cols] = ind[zone_cols].ffill(limit=3)  # 서울(build_indicators)과 같은 규칙: 이어 쓰기 3개월 → 공개 시차
    return timing.apply(ind, cols=replaced)  # 서울 공통 지표는 indicators.csv에서 이미 처리됨


def main():
    """권역별 지표 원값·실거래 반복매매지수·거래 비중을 만든다. 지수 계산(v3)은 zone_v3.py."""
    meta = pd.read_csv(ROOT / "data" / "indicator_meta.csv", index_col=0).fillna("")
    meta = meta.loc[[c for c in meta.index if c not in NOT_REALTIME]]
    seoul = pd.read_csv(ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)
    seoul = seoul[seoul.index <= seoul["__price"].last_valid_index()]  # KB 최신월까지 (공급 일정은 미래까지 있음)
    idx = seoul.index
    seoul_ind = seoul[meta.index]

    trades = MI.load()
    trades["gu"] = trades["gu"].map(LAWD2GU)
    trades["zone"] = trades["gu"].map(GU2ZONE)
    value = trades.groupby(["zone", "date"])["price"].sum().unstack(0).reindex(idx).fillna(0)
    weight = value.rolling(12).sum().shift(2)  # 신고 시차 반영

    out = {}
    for z in ZONES:
        ind = zone_indicators(z, seoul_ind).reindex(idx)
        sub = trades[trades["zone"] == z]
        rs, _ = MI.repeat_sales(sub)
        hi, dr, _ = MI.high_low(sub)
        ind["거래_신고가비중"] = hi.rolling(3).mean().shift(2).reindex(idx)
        ind["거래_급락거래역수"] = (-dr.rolling(3).mean().shift(2)).reindex(idx)
        rs = rs.reindex(idx)
        rs.iloc[-2:] = np.nan
        y = np.log(rs).shift(-12) - np.log(rs)
        zone_specific = [c for c in meta.index if not ind[c].equals(seoul_ind[c].reindex(idx).ffill(limit=3))]
        out[z] = {"ind": ind, "rs": rs, "fwd12": y, "zone_specific": zone_specific}
        print(f"{z}: 권역 고유 지표 {len(zone_specific)}개, 실거래 지수 {rs.dropna().index[-1].date()}까지", flush=True)
    return out, weight


if __name__ == "__main__":
    out, weight = main()
    print("최근 거래금액 비중", (weight.iloc[-1] / weight.iloc[-1].sum()).round(3).to_dict())
    pd.to_pickle({"zones": out, "weight": weight}, OUT / "zone_calc.pkl")
