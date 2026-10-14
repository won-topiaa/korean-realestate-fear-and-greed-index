"""국토부 실거래(서울 아파트) → 반복매매 가격지수(정답용) + 신고가·급락 거래 비중(지표).

같은 단지(aptSeq)·같은 전용면적(㎡ 반올림)의 연속 거래 쌍으로 Bailey-Muth-Nourse 반복매매지수를 추정.
정답(반복매매지수)은 해제 신고 거래와 직거래를 뺀다(시장 가격). 신고가·급락 지표는 해제·직거래 표시가 2020~2021년에야
생겨서, 표시 전후로 정의가 달라지지 않게 모든 거래로 계산한다 (v3.3). 결과: data/repeat_sales.csv
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import lsqr

ROOT = Path(__file__).parent
SRC = ROOT / "data" / "raw" / "molit" / "apt"


def load(market_only=True):
    """압축 저장소(molit_store) 우선, 없으면 구·월 JSON 캐시에서 읽는다.
    market_only: 해제 신고(2020.2~ 표시)·직거래(2021.11~ 표시) 제외. 지표용은 False (표시가 없던 시기와 같은 정의)."""
    import molit_store
    if molit_store.exists():
        df = molit_store.load()
    else:
        frames = []
        for f in sorted(SRC.glob("*.json")):
            d = json.loads(f.read_text())
            if d:
                frames.append(pd.DataFrame(d))
        df = pd.concat(frames, ignore_index=True).fillna("")
    df["price"] = pd.to_numeric(df["dealAmount"].str.replace(",", ""), errors="coerce")
    df["area"] = pd.to_numeric(df["excluUseAr"], errors="coerce").round(0)
    df["date"] = pd.to_datetime(dict(year=df["dealYear"].astype(int), month=df["dealMonth"].astype(int), day=1))
    df["day"] = pd.to_numeric(df["dealDay"], errors="coerce").fillna(15)
    df["key"] = df["aptSeq"] + "|" + df["area"].astype(str)
    df["gu"] = df["aptSeq"].str.split("-").str[0]
    df = df[df["price"].gt(0) & df["area"].gt(0)]
    if market_only:
        df = df[(df["cdealType"].fillna("") == "") & (df["dealingGbn"].fillna("") != "직거래")]
    return df.sort_values(["key", "date", "day", "price"], kind="mergesort").reset_index(drop=True)  # 같은 날 거래도 순서 고정


def repeat_sales(df):
    months = pd.date_range(df["date"].min(), df["date"].max(), freq="MS")
    pos = {d: i for i, d in enumerate(months)}
    prev = df.groupby("key").shift(1)
    pair = df[prev["date"].notna()].copy()
    pair["t0"], pair["p0"] = prev.loc[pair.index, "date"], prev.loc[pair.index, "price"]
    pair = pair[pair["t0"] != pair["date"]]
    pair["dl"] = np.log(pair["price"] / pair["p0"])
    pair = pair[pair["dl"].abs() < 1.0]
    i0, i1 = pair["t0"].map(pos).to_numpy(), pair["date"].map(pos).to_numpy()
    n, T = len(pair), len(months)
    rows = np.r_[np.arange(n), np.arange(n)]
    cols = np.r_[i1, i0]
    vals = np.r_[np.ones(n), -np.ones(n)]
    keep = cols != 0  # 첫 달 = 기준 (0)
    X = csr_matrix((vals[keep], (rows[keep], cols[keep] - 1)), shape=(n, T - 1))
    gap = (i1 - i0) / 12.0
    w = 1 / np.sqrt(0.05 + 0.02 * gap)  # 보유기간이 길수록 잡음이 커지는 것을 반영한 가중
    b = lsqr(X.multiply(w[:, None]).tocsr(), pair["dl"].to_numpy() * w, atol=1e-10, btol=1e-10, iter_lim=20000)[0]
    idx = pd.Series(np.exp(np.r_[0, b]), index=months)
    npairs = pd.Series(i1).value_counts().reindex(range(T), fill_value=0).to_numpy()
    return idx / idx.iloc[-1] * 100, pd.Series(npairs, index=months)


def high_low(df, high_window_days=1095, drop_gap_months=24):
    """같은 단지·면적 기준 월별 비중.
    신고가: 최근 3년(1,095일) 안의 이전 거래 최고가보다 비싸게 팔린 거래 (3년 안에 이전 거래가 있을 때만).
    급락: 직전 거래보다 10% 넘게 싸게 팔린 거래 (직전 거래가 24개월 안일 때만 — 오래된 거래와의 비교 제외)."""
    d = df[["key", "date", "day", "price"]].copy()
    d["dt"] = d["date"] + pd.to_timedelta(d["day"].clip(1, 31) - 1, unit="D")
    d = d.sort_values(["key", "dt", "price"], kind="mergesort").reset_index()
    roll = (d.groupby("key").rolling(f"{high_window_days}D", on="dt", closed="left")["price"].max()
              .reset_index(level=0, drop=True))
    d["prior_max"] = roll.values
    # 직전 '다른 날' 거래가 (같은 날 거래끼리는 비교하지 않음, 그날 거래가 여럿이면 중앙값)
    day = d.groupby(["key", "dt"], sort=False)["price"].median().reset_index()
    gd = day.groupby("key")
    day["prev_dt"], day["prev_p"] = gd["dt"].shift(1), gd["price"].shift(1)
    d = d.merge(day[["key", "dt", "prev_dt", "prev_p"]], on=["key", "dt"], how="left")
    prev_dt, prev_p = d["prev_dt"], d["prev_p"]
    gap = (d["dt"].dt.year - prev_dt.dt.year) * 12 + (d["dt"].dt.month - prev_dt.dt.month)
    has_hi = d["prior_max"].notna()
    has_drop = prev_p.notna() & (gap <= drop_gap_months)
    hi = (d["price"] > d["prior_max"]).where(has_hi)
    dr = (d["price"] < 0.9 * prev_p).where(has_drop)
    m = pd.DataFrame({"date": d["date"], "hi": hi.astype(float), "dr": dr.astype(float)})
    out = m.groupby("date")[["hi", "dr"]].mean()
    return out["hi"], out["dr"], df.groupby("date").size()


if __name__ == "__main__":
    df = load()
    df_all = load(market_only=False)  # 지표용: 해제·직거래 표시 전후로 같은 정의
    print("거래", len(df), "| 기간", df["date"].min().date(), "~", df["date"].max().date(), "| aptSeq 빈 값", (df["aptSeq"] == "").mean().round(3))
    idx, npairs = repeat_sales(df)
    hi, dr, _ = high_low(df_all)
    cnt = df.groupby("date").size()
    out = pd.DataFrame({"index": idx, "pairs": npairs, "trades": cnt})
    # 지표는 신고 기한(최대 60일) 때문에 2개월 뒤에야 확정 → 2개월 늦춰서 사용
    out["거래_신고가비중"] = hi.rolling(3).mean().shift(2)
    out["거래_급락거래역수"] = -dr.rolling(3).mean().shift(2)
    # 같은 이유로 최근 2개월 지수는 표본이 덜 차서 제외
    out.loc[out.index[-2:], "index"] = np.nan
    out.to_csv(ROOT / "data" / "repeat_sales.csv")
    json.dump({"n_trades": int(len(df)), "base_month": str(out["index"].last_valid_index().date())[:7]},
              open(ROOT / "data" / "repeat_sales_meta.json", "w"))
    print(out.iloc[::12].round(3).to_string())
    print(out.tail(6).round(3).to_string())
