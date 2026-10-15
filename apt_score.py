"""단지 검색: 단지·평형별 '실거래 위치 점수' (스토캐스틱 %K) → results_apt/ (사이트 빌드 때 site/apt/data/로 복사, 저장소에는 안 올림).

점수 = (가장 최근 거래의 보정가 − 비교 거래 중 최저) / (최고 − 최저) × 100
  주식 스토캐스틱 %K와 같은 식이고, 봉 대신 거래를 쓴다. 100이면 비교 거래 중 가장 비싸게, 0이면 가장 싸게 거래된 것.
- 비교 거래: 같은 단지·같은 평형(전용 1㎡ 단위)의 최근 10건 (2년 안, 최근 거래 포함).
  같은 평형이 5건 미만이면 같은 단지 다른 평형 거래를 이 평형 가격으로 환산해 10건까지 채운다.
- 보정가: 그 사이 시장 변화(구 반복매매지수), 층(8~10층 기준), 평형 차이를 맞춘 가격. 기준은 '최근 거래가 있던 달·8~10층'.
- 해제·직거래 제외. 비교 거래가 5건 미만이면 점수를 내지 않는다.
고정값(층 효과·면적 탄력성·평형 비율 기간)은 apt_study.py 검증 결과 (2026-10, 2006~2026 실거래 141만 건).
"""
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

import molit_indicators as MI
import molit_store

ROOT = Path(__file__).parent
OUT = ROOT / "results_apt"
N, MIN_N, MIN_SAME, WINDOW_DAYS = 10, 5, 5, 730
B = 0.7953  # 같은 단지·같은 반기 안에서 전용면적 1% ↑ → 가격 0.80% ↑ (2006~2020)
FLOOR_BINS = [1, 2, 3, 4, 5, 7, 10, 14, 19, 29, 999]  # 1층 이하, 2, 3, 4, 5, 6~7, 8~10, 11~14, 15~19, 20~29, 30+
FLOOR_EFF = np.array([-0.0942, -0.0548, -0.0342, -0.0251, -0.0169, -0.0068, 0.0, 0.0031, 0.0027, 0.0075, 0.0307])  # log, 8~10층 = 0
RATIO_YEARS, RATIO_K = 3, 1  # 단지 안 평형 간 비율: 최근 3년 거래로, 거래가 적으면 면적 탄력성 쪽으로 (1건만큼 줄임)
MIN_PAIRS = 30  # 구 지수: 반복매매 쌍이 이보다 적은 달(주로 아직 신고 중인 최근 달)은 앞 달 값
LAWD2GU = {"11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구", "11215": "광진구", "11230": "동대문구",
           "11260": "중랑구", "11290": "성북구", "11305": "강북구", "11320": "도봉구", "11350": "노원구", "11380": "은평구",
           "11410": "서대문구", "11440": "마포구", "11470": "양천구", "11500": "강서구", "11530": "구로구", "11545": "금천구",
           "11560": "영등포구", "11590": "동작구", "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구",
           "11740": "강동구"}


def floor_eff(floor):
    f = np.asarray(floor, dtype=float)
    e = FLOOR_EFF[np.searchsorted(FLOOR_BINS, np.maximum(np.nan_to_num(f, nan=8), 1), side="left")]
    return np.where(np.isnan(f), 0.0, e)  # 층 정보가 없으면 보정하지 않음


def gu_market():
    """구별 실거래 반복매매지수 (log). 같은 정의(해제·직거래 제외)로 지수를 만든다."""
    t = MI.load()
    months = pd.date_range(t["date"].min(), t["date"].max(), freq="MS")
    out = {}
    for g, sub in t.groupby("gu"):
        rs, npairs = MI.repeat_sales(sub)
        lr = np.log(rs.reindex(months))
        lr[npairs.reindex(months).fillna(0) < MIN_PAIRS] = np.nan
        out[g] = lr.ffill().bfill()
    return pd.DataFrame(out)


def trades(mk):
    df = molit_store.load()
    df = df[(df["cdealType"] == "") & (df["dealingGbn"] != "직거래")].copy()
    df["price"] = pd.to_numeric(df["dealAmount"].str.replace(",", ""), errors="coerce")
    df["area"] = pd.to_numeric(df["excluUseAr"], errors="coerce")
    df["floor"] = pd.to_numeric(df["floor"], errors="coerce")
    df = df[(df["price"] > 0) & (df["area"] > 0)].copy()
    df["month"] = pd.to_datetime(dict(year=df["dealYear"].astype(int), month=df["dealMonth"].astype(int), day=1))
    df["date"] = df["month"] + pd.to_timedelta(pd.to_numeric(df["dealDay"], errors="coerce").fillna(15) - 1, unit="D")
    df["type"] = df["area"].round(0).astype(int)
    df["half"] = df["month"].dt.year.astype(str) + np.where(df["month"].dt.month <= 6, "a", "b")
    df["mk"] = mk.stack().reindex(pd.MultiIndex.from_arrays([df["month"], df["lawd"]])).to_numpy()
    df = df[df["mk"].notna()].copy()
    df["ff"] = floor_eff(df["floor"])
    df["la"] = np.log(df["area"])
    df["yf"] = np.log(df["price"]) - df["mk"] - df["ff"]  # 시장·층을 맞춘 가격 (log)
    return df.sort_values(["aptSeq", "date", "price"], kind="mergesort").reset_index(drop=True)


def type_dev(df):
    """같은 단지 평형 간 가격 차 중 면적만으로 설명되지 않는 부분 (log). 최근 3년, 거래가 적으면 0 쪽으로."""
    sub = df[df["month"] > df["month"].max() - pd.DateOffset(years=RATIO_YEARS)]
    e = sub["yf"] - B * sub["la"]
    e = e - e.groupby([sub["aptSeq"], sub["half"]]).transform("mean")
    s = e.groupby([sub["aptSeq"], sub["type"]]).agg(["sum", "count"])
    return s["sum"] / (s["count"] + RATIO_K)


def pool_for(i, a, t, typ):
    """i(이 평형의 가장 최근 거래)까지 2년 안 같은 평형 최근 10건. 5건 미만이면 다른 평형 최근 거래로 10건까지."""
    lo = a + np.searchsorted(t, t[i - a] - np.timedelta64(WINDOW_DAYS, "D"), side="left")
    idx = np.arange(lo, i + 1)
    same_m = typ[idx] == typ[i]
    same = idx[same_m][-N:]
    if len(same) >= MIN_SAME:
        return same
    oth = idx[~same_m][-(N - len(same)):]
    return np.sort(np.r_[same, oth])


def won(v):
    return int(round(float(v)))


def main():
    OUT.mkdir(exist_ok=True)
    mk = gu_market()
    df = trades(mk)
    dev = type_dev(df).reindex(pd.MultiIndex.from_arrays([df["aptSeq"], df["type"]])).fillna(0).to_numpy()
    base = df["yf"].to_numpy() - B * df["la"].to_numpy() - dev  # 단지 안에서 평형을 맞춘 가격 (log)
    end = df["date"].max()
    since = end - pd.Timedelta(days=WINDOW_DAYS)
    seq, dates, typ = df["aptSeq"].to_numpy(), df["date"].to_numpy(), df["type"].to_numpy()
    price, floor, area, la = df["price"].to_numpy(), df["floor"].to_numpy(), df["area"].to_numpy(), df["la"].to_numpy()
    yf, mkv = df["yf"].to_numpy(), df["mk"].to_numpy()
    ds = df["date"].dt.strftime("%Y-%m-%d").to_numpy()
    bounds = np.flatnonzero(np.r_[True, seq[1:] != seq[:-1], True])

    cx = molit_store.load_complexes().set_index("aptSeq")
    bfile = ROOT / "data" / "molit" / "buildings.csv"
    bld = pd.read_csv(bfile, dtype=str, keep_default_na=False).set_index("aptSeq") if bfile.exists() else pd.DataFrame()
    detail = {g: {} for g in LAWD2GU}
    scored = mixed = types_out = 0
    for a, b in zip(bounds[:-1], bounds[1:]):
        s = seq[a]
        t = dates[a:b]
        types = []
        for T in sorted(set(typ[a:b][t > since.to_datetime64()])):
            i = a + np.flatnonzero(typ[a:b] == T)[-1]
            pool = pool_for(i, a, t, typ)
            # 보정가: 이 평형·8~10층·최근 거래 달 시세로 환산 (만원)
            adj = np.exp(base[pool] + B * la[i] + dev[i] + mkv[i])
            adj[pool == i] = np.exp(yf[i] + mkv[i])  # 최근 거래 자신은 층만 맞춤 (평형 환산 없음)
            x = float(np.exp(yf[i] + mkv[i]))
            lo, hi = float(adj.min()), float(adj.max())
            k = None
            if len(pool) >= MIN_N:
                k = 50.0 if hi - lo < 1e-6 * hi else (x - lo) / (hi - lo) * 100
                scored += 1
            n_same = int((typ[pool] == T).sum())
            mixed += n_same < len(pool) and k is not None
            win = (t > (dates[i] - np.timedelta64(WINDOW_DAYS, "D"))) & (t <= dates[i])
            types.append({
                "a": int(T), "k": None if k is None else round(k, 1), "same": n_same, "conv": int(len(pool) - n_same),
                "n2y": int(((typ[a:b] == T) & win).sum()),
                "last": [ds[i], None if np.isnan(floor[i]) else int(floor[i]), won(price[i]), round(float(area[i]), 2)],
                "x": won(x), "lo": won(lo), "hi": won(hi),
                "pool": [[ds[j], None if np.isnan(floor[j]) else int(floor[j]), round(float(area[j]), 2), won(price[j]), won(v), int(typ[j] == T)]
                         for j, v in zip(pool, adj)],
            })
        types_out += len(types)
        row = cx.loc[s] if s in cx.index else None
        info = None
        if len(bld) and s in bld.index and bld.loc[s, "status"] == "ok":
            r = bld.loc[s]
            info = {k: r[k] for k in bld.columns if r[k] != "" and k not in ("fetched", "status")}
        detail.setdefault(s[:5], {})[s] = {
            "maxfl": None if np.isnan(floor[a:b]).all() else int(np.nanmax(floor[a:b])),
            "n2y": int((t > since.to_datetime64()).sum()),
            "lastAll": ds[b - 1],
            "types": sorted(types, key=lambda d: d["a"]),
            "info": info,
            "jibun": "" if row is None else row["jibun"],
        }

    # 구 공포탐욕 점수 (지도와 같은 값)
    gu_fg = {}
    mp = ROOT / "results_zone" / "map_data.json"
    if mp.exists():
        m = json.loads(mp.read_text())
        for code, name in LAWD2GU.items():
            r = m["regions"].get(name)
            if r:
                gu_fg[code] = {"name": name, "zone": r.get("zone"), "score": r["score"][-1], "month": m["dates"][-1][:7]}
    for code, name in LAWD2GU.items():
        gu_fg.setdefault(code, {"name": name})

    items = []
    for s, r in cx.iterrows():
        d = detail.get(s[:5], {}).get(s)
        items.append([s, r["aptNm"], r["umdNm"], r["buildYear"], r["last"], 1 if d and any(x["k"] is not None for x in d["types"]) else 0,
                      "|".join(n for n in r["names"].split("|") if n != r["aptNm"])])
    gdir = OUT / "gu"
    if gdir.exists():
        shutil.rmtree(gdir)
    gdir.mkdir()
    for g, d in detail.items():
        (gdir / f"{g}.json").write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
    meta = {"asof": end.strftime("%Y-%m-%d"), "gu": gu_fg, "n_complex": len(items), "n_scored": scored, "n_mixed": mixed,
            "floor": dict(zip(["1층 이하", "2층", "3층", "4층", "5층", "6~7층", "8~10층", "11~14층", "15~19층", "20~29층", "30층 이상"],
                              [round(float(np.expm1(v)) * 100, 1) for v in FLOOR_EFF])),
            "has_info": bool(len(bld))}
    (OUT / "index.json").write_text(json.dumps({"meta": meta, "items": items}, ensure_ascii=False, separators=(",", ":")))
    size = sum(f.stat().st_size for f in OUT.rglob("*.json")) / 1e6
    print(f"기준일 {meta['asof']} · 단지 {len(items):,} · 최근 2년 거래 평형 {types_out:,} 중 점수 {scored:,} (다른 평형 섞임 {mixed:,}) · {size:.1f} MB")


if __name__ == "__main__":
    main()
