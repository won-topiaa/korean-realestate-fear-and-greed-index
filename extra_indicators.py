"""API 키로 받은 자료(한국부동산원 R-ONE, 청약홈, 국토부 실거래)로 만든 서울 월간 지표와 대체 정답 시계열.

결과: data/indicators_extra.csv (지표), data/targets_extra.csv (대체 정답: 부동산원 지수, 실거래 반복매매지수, 소비심리지수)
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"


def reb(name, cls=None):
    d = pd.DataFrame(json.loads((RAW / "reb" / f"{name}.json").read_text()))
    d["date"] = pd.to_datetime(d["WRTTIME_IDTFR_ID"], format="%Y%m")
    if cls is None:
        return d.groupby("date")["DTA_VAL"].sum().astype(float)
    return d.pivot_table(index="date", columns="CLS_NM", values="DTA_VAL", aggfunc="sum").astype(float)


def applyhome_monthly(area="서울"):
    a = pd.DataFrame(json.loads((RAW / "applyhome" / "APT_분양공고.json").read_text()))
    s = a[(a["SUBSCRPT_AREA_CODE_NM"] == area)].copy()
    s["date"] = pd.to_datetime(s["RCEPT_BGNDE"].fillna(s["RCRIT_PBLANC_DE"])).dt.to_period("M").dt.to_timestamp()
    c = pd.DataFrame(json.loads((RAW / "applyhome" / "APT_경쟁률.json").read_text()))
    c = c[c["HOUSE_MANAGE_NO"].isin(s["HOUSE_MANAGE_NO"]) & (c["SUBSCRPT_RANK_CODE"].astype(str) == "1")].copy()
    c["REQ_CNT"] = pd.to_numeric(c["REQ_CNT"], errors="coerce").fillna(0)
    c["SUPLY_HSHLDCO"] = pd.to_numeric(c["SUPLY_HSHLDCO"], errors="coerce").fillna(0)
    # 주택형별: 공급 세대는 거주구분 행마다 반복되므로 한 번만, 신청은 모든 거주구분 합
    ty = c.groupby(["HOUSE_MANAGE_NO", "MODEL_NO"]).agg(req=("REQ_CNT", "sum"), sup=("SUPLY_HSHLDCO", "max")).reset_index()
    ty = ty.merge(s[["HOUSE_MANAGE_NO", "date"]], on="HOUSE_MANAGE_NO")
    m = ty.groupby("date").agg(req=("req", "sum"), sup=("sup", "sum"),
                               short=("req", lambda r: 0), n=("req", "size"))
    m["short"] = ty.assign(sh=(ty["req"] < ty["sup"]).astype(int)).groupby("date")["sh"].sum()
    supply = s.groupby("date")["TOT_SUPLY_HSHLDCO"].sum()
    rr = pd.DataFrame(json.loads((RAW / "applyhome" / "무순위_경쟁률.json").read_text()))
    rp = pd.DataFrame(json.loads((RAW / "applyhome" / "무순위_분양공고.json").read_text()))
    rp = rp[rp["SUBSCRPT_AREA_CODE_NM"] == area].copy()
    rp["date"] = pd.to_datetime(rp["SUBSCRPT_RCEPT_BGNDE"].fillna(rp["RCRIT_PBLANC_DE"])).dt.to_period("M").dt.to_timestamp()
    rr = rr[rr["HOUSE_MANAGE_NO"].isin(rp["HOUSE_MANAGE_NO"])].copy()
    for k in ("REQ_CNT", "SUPLY_HSHLDCO"):
        rr[k] = pd.to_numeric(rr[k], errors="coerce").fillna(0)
    rr = rr.merge(rp[["HOUSE_MANAGE_NO", "date"]].drop_duplicates(), on="HOUSE_MANAGE_NO")
    rm = rr.groupby("date").agg(req=("REQ_CNT", "sum"), sup=("SUPLY_HSHLDCO", "sum"))
    idx = pd.date_range("2020-02-01", m.index.max(), freq="MS")
    m, supply, rm = m.reindex(idx, fill_value=0), supply.reindex(idx, fill_value=0), rm.reindex(idx, fill_value=0)
    roll = lambda x, k=6: x.rolling(k, min_periods=k).sum()
    out = pd.DataFrame(index=idx)
    out["청약_1순위경쟁률"] = np.log1p(roll(m["req"]) / roll(m["sup"]).replace(0, np.nan))
    out["청약_미달역수"] = -(roll(m["short"]) / roll(m["n"]).replace(0, np.nan))
    out["청약_무순위경쟁률"] = np.log1p(roll(rm["req"]) / roll(rm["sup"]).replace(0, np.nan))
    out["청약_실제공급"] = np.log1p(roll(supply, 12))
    return out


def build():
    ind = {}
    vol = reb("reb_거래량_서울")
    ind["거래_거래량"] = np.log(vol.rolling(3).mean() / vol.rolling(60, min_periods=36).mean())
    ind["거래_거래량증가"] = np.log(vol.rolling(3).sum() / vol.rolling(3).sum().shift(12))
    res = reb("reb_매입자거주지_서울", cls=True)
    ind["거래_외지인비중"] = (res["관할시도외_기타"] / res["합계"]).rolling(3).mean()
    ind["거래_원정매수비중"] = (1 - res["관할시군구내"] / res["합계"]).rolling(3).mean()
    age = reb("reb_매입자연령_서울", cls=True)
    ind["거래_2030비중"] = ((age["20대이하"] + age["30대"]) / age["합계"]).rolling(3).mean()
    subj = reb("reb_거래주체_서울", cls=True)
    corp = subj[[c for c in subj.columns if c.endswith("→법인")]].sum(axis=1)
    ind["거래_법인매수비중"] = (corp / subj["합계"]).rolling(3).mean()
    ind["공급_미분양역수"] = -np.log1p(reb("reb_미분양_서울"))
    ind["설문_부동산원매매수급"] = reb("reb_매매수급_서울")
    ind["전세_부동산원전세수급"] = reb("reb_전세수급_서울")
    ind["설문_국토연소비심리"] = reb("reb_주택심리_서울")
    df = pd.DataFrame(ind).join(applyhome_monthly(), how="outer")
    tg = pd.DataFrame({"부동산원지수": reb("reb_매매지수_서울"), "국토연심리": reb("reb_주택심리_서울")})
    rs = ROOT / "data" / "repeat_sales.csv"
    if rs.exists():
        r = pd.read_csv(rs, index_col=0, parse_dates=True)
        tg = tg.join(r[["index"]].rename(columns={"index": "실거래지수"}), how="outer")
        df = df.join(r[["거래_신고가비중", "거래_급락거래역수"]], how="outer")  # 부동산원·청약홈보다 최신 달이 있을 수 있음
    return df.sort_index(), tg.sort_index()


META_EXTRA = {
    # 지표: (설명, 주제, 속도, 출처성격, 행위자, 시장, CNN대응, 사용자원안)
    "거래_거래량": ("부동산원 아파트 매매 거래량 3개월 평균 / 5년 평균", "거래", "동행", "거래실측", "매수자", "매매", "변동성→거래량", ""),
    "거래_거래량증가": ("거래량 3개월 합 전년 대비", "거래", "선행", "거래실측", "매수자", "매매", "", ""),
    "거래_외지인비중": ("서울 아파트 매수 중 타 시도 거주자 비중", "거래", "동행", "거래실측", "매수자", "매매", "", ""),
    "거래_원정매수비중": ("자기 구 밖에서 사는 매수 비중 (갈아타기·투자)", "거래", "동행", "거래실측", "매수자", "매매", "", ""),
    "거래_2030비중": ("매수자 중 20·30대 비중 (영끌, 2019~)", "거래", "동행", "거래실측", "매수자", "매매", "", ""),
    "거래_법인매수비중": ("법인 매수 비중", "거래", "동행", "거래실측", "매수자", "매매", "", ""),
    "공급_미분양역수": ("서울 미분양 주택 (부호 반대)", "공급", "후행", "공급통계", "공급자", "분양", "", "공급량"),
    "설문_부동산원매매수급": ("부동산원 매매수급지수 (2012.7~)", "수급심리", "동행", "설문", "중개사", "매매", "", ""),
    "전세_부동산원전세수급": ("부동산원 전세수급지수 (2012.7~)", "전세", "선행", "설문", "중개사", "전세", "", ""),
    "설문_국토연소비심리": ("국토연 주택시장 소비심리지수 서울 (2011.7~)", "수급심리", "동행", "설문", "매수자", "매매", "", ""),
    "청약_1순위경쟁률": ("청약홈 서울 1순위 경쟁률 6개월 (2020.2~)", "청약", "선행", "거래실측", "매수자", "분양", "", ""),
    "청약_미달역수": ("청약홈 서울 1순위 미달 주택형 비율 (부호 반대)", "청약", "선행", "거래실측", "매수자", "분양", "", ""),
    "청약_무순위경쟁률": ("청약홈 서울 무순위(줍줍) 경쟁률 6개월", "청약", "선행", "거래실측", "매수자", "분양", "", ""),
    "청약_실제공급": ("청약홈 서울 실제 공급 세대 12개월 (KB 분양물량 대체)", "공급", "후행", "공급통계", "공급자", "분양", "", "공급량"),
    "거래_신고가비중": ("실거래 중 같은 단지·면적 역대 최고가 비중 (국토부)", "가격", "동행", "거래실측", "매수자", "매매", "강도", ""),
    "거래_급락거래역수": ("직전 거래보다 10% 넘게 싸게 팔린 비중 (부호 반대)", "가격", "동행", "거래실측", "매도자", "매매", "", ""),
}

if __name__ == "__main__":
    df, tg = build()
    df.to_csv(ROOT / "data" / "indicators_extra.csv")
    tg.to_csv(ROOT / "data" / "targets_extra.csv")
    cov = pd.DataFrame({"start": df.apply(lambda s: s.first_valid_index()), "end": df.apply(lambda s: s.last_valid_index()),
                        "now": df.ffill().iloc[-1].round(3)})
    print(cov.to_string())
    print(tg.dropna(how="all").tail(3).to_string())
