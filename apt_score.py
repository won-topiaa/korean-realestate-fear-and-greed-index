"""단지 검색: 단지·평형별 '실거래 위치 점수' (스토캐스틱 %K) → results_apt/ (사이트 빌드 때 site/apt/data/로 복사, 저장소에는 안 올림).

점수 = (가장 최근 거래의 보정가 − 비교 거래 중 최저) / (최고 − 최저) × 100
  주식 스토캐스틱 %K와 같은 식이고, 봉 대신 거래를 쓴다. 100이면 비교 거래 중 가장 비싸게, 0이면 가장 싸게 거래된 것.
- 비교 거래: 같은 단지·같은 평형(전용 1㎡ 단위)의 최근 10건 (2년 안, 최근 거래 포함).
  같은 평형이 5건 미만이면 같은 단지 다른 평형 거래를 이 평형 가격으로 환산해 10건까지 채운다.
- 보정가: 그 사이 시장 변화(구 반복매매지수), 층(8~10층 기준), 평형 차이를 맞춘 가격. 기준은 '최근 거래가 있던 달·8~10층'.
- 해제·직거래 제외. 비교 거래가 5건 미만이면 점수를 내지 않는다.
고정값(층 효과·면적 탄력성·평형 비율 기간)은 apt_study.py 검증 결과 (2026-10, 2006~2026 실거래 141만 건).

수도권·광역시: 지역 저장소(data/molit_kr)에 들어온 지역마다 같은 방식으로 results_apt/{지역id}/에 만든다. 층 효과·면적 탄력성은
apt_region_study.py가 지역마다 고른 값(data/apt_params.json), 시장 변화는 그 지역 시군구 반복매매지수 (반복매매 쌍이 적은 달은
지역 전체 지수의 그 달 변화로 잇는다). 단지 이름은 지역 단지 표(data/molit_kr/complexes.csv).

사용: python apt_score.py [seoul|지역id ...]   (없으면 서울과 저장소에 있는 모든 지역)
"""
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import molit_indicators as MI
import molit_store
import region_store
from regions import REGIONS, sub_word

ROOT = Path(__file__).parent
OUT = ROOT / "results_apt"
PARAMS = ROOT / "data" / "apt_params.json"  # 지역별 층 효과·면적 탄력성과 검증 (apt_region_study.py)
NAMED = 0.98  # 최근 2년 거래 단지 중 이름이 있는 비율이 이보다 낮으면 그 지역은 아직 만들지 않는다 (이름 채우는 중)
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


def params(rid=None):
    """(면적 탄력성 B, 층 효과표, 검증 결과). 서울은 위 고정값, 지역은 apt_region_study.py가 고른 값 (없으면 서울 값)."""
    p = json.loads(PARAMS.read_text()) if PARAMS.exists() else {}
    r = p.get(rid or "seoul") or {}
    return r.get("B", B), np.array(r.get("floor", FLOOR_EFF)), r.get("check")


def floor_eff(floor, table=FLOOR_EFF):
    f = np.asarray(floor, dtype=float)
    e = np.asarray(table)[np.searchsorted(FLOOR_BINS, np.maximum(np.nan_to_num(f, nan=8), 1), side="left")]
    return np.where(np.isnan(f), 0.0, e)  # 층 정보가 없으면 보정하지 않음


def store(rid=None):
    return molit_store.load() if rid is None else region_store.load(rid)


def chain(lr, whole):
    """반복매매 쌍이 적어 비운 달을 지역 전체 지수의 그 달 변화로 잇는다 (첫 값 앞은 거꾸로)."""
    v, d = lr.to_numpy().copy(), np.diff(whole.to_numpy(), prepend=np.nan)
    ok = ~np.isnan(v)
    if not ok.any():
        return whole.copy()
    i0 = int(np.argmax(ok))
    for i in range(i0 + 1, len(v)):
        if np.isnan(v[i]):
            v[i] = v[i - 1] + d[i]
    for i in range(i0 - 1, -1, -1):
        v[i] = v[i + 1] - d[i + 1]
    return pd.Series(v, index=lr.index)


def gu_market(rid=None):
    """구별 실거래 반복매매지수 (log). 같은 정의(해제·직거래 제외)로 지수를 만든다.
    지역(rid)은 시군구(지금 지역 코드)별로, 쌍이 적은 달은 지역 전체 지수 변화로 잇는다 (거래가 적은 군·새로 생긴 구)."""
    t = MI.load(df=None if rid is None else store(rid))
    months = pd.date_range(t["date"].min(), t["date"].max(), freq="MS")

    def one(sub):
        rs, npairs = MI.repeat_sales(sub)
        lr = np.log(rs.reindex(months))
        lr[npairs.reindex(months).fillna(0) < MIN_PAIRS] = np.nan
        return lr
    if rid is None:
        return pd.DataFrame({g: one(sub).ffill().bfill() for g, sub in t.groupby("gu")})
    whole = one(t).ffill().bfill()
    out = {}
    for g in REGIONS[rid]["lawd"]:
        sub = t[t["lawd"] == g]
        try:
            lr = one(sub) if len(sub) > 1 else pd.Series(np.nan, index=months)
        except Exception:  # noqa: BLE001  (반복매매 쌍이 하나도 없는 곳: 지역 전체 지수로)
            lr = pd.Series(np.nan, index=months)
        out[g] = chain(lr, whole)
    return pd.DataFrame(out)


def trades(mk, rid=None):
    df = store(rid)
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
    df["ff"] = floor_eff(df["floor"], params(rid)[1])
    df["la"] = np.log(df["area"])
    df["yf"] = np.log(df["price"]) - df["mk"] - df["ff"]  # 시장·층을 맞춘 가격 (log)
    return df.sort_values(["aptSeq", "date", "price"], kind="mergesort").reset_index(drop=True)


def type_dev(df, b=B):
    """같은 단지 평형 간 가격 차 중 면적만으로 설명되지 않는 부분 (log). 최근 3년, 거래가 적으면 0 쪽으로."""
    sub = df[df["month"] > df["month"].max() - pd.DateOffset(years=RATIO_YEARS)]
    e = sub["yf"] - b * sub["la"]
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


QUICK_SEOUL = ["11680-218", "11710-8865", "11710-6346", "11650-5126", "11470-23"]  # 예시 단지 (은마·잠실엘스 등)


def complexes(rid=None):
    return molit_store.load_complexes() if rid is None else region_store.load_complexes()


def home(rid):
    """지역 단지의 화면용 지역 코드: 그 단지 거래가 가장 많이 들어온 지금 지역 코드 (단지 번호 앞자리는 옛 코드일 수 있음)."""
    st = store(rid)
    return st.groupby("aptSeq")["lawd"].agg(lambda x: x.value_counts().index[0])


def named_share(rid):
    """최근 2년 거래 단지 중 단지 표에 이름이 있는 비율 (지역 단지 이름을 아직 채우는 중인지)."""
    st = store(rid)
    y = pd.to_numeric(st["dealYear"], errors="coerce") * 12 + pd.to_numeric(st["dealMonth"], errors="coerce")
    seqs = set(st.loc[y >= y.max() - 24, "aptSeq"])
    return len(seqs & set(complexes(rid)["aptSeq"])) / max(1, len(seqs))


def fg_scores(rid=None):
    """구·시군구 코드 → 이름·공포탐욕 최신 점수 (지도와 같은 값). 지역은 지수를 공개한 곳만 점수를 싣는다.
    반환: (코드별 정보, 지도 주소, 상위 지역 이름)."""
    if rid is None:
        gu = {}
        mp = ROOT / "results_zone" / "map_data.json"
        if mp.exists():
            m = json.loads(mp.read_text())
            for code, name in LAWD2GU.items():
                r = m["regions"].get(name)
                if r:
                    gu[code] = {"name": name, "zone": r.get("zone"), "score": r["score"][-1], "month": m["dates"][-1][:7]}
        for code, name in LAWD2GU.items():
            gu.setdefault(code, {"name": name})
        return gu, "seoul/", "서울"
    import home_build
    names = REGIONS[rid]["lawd"]
    gu = {code: {"name": name} for code, name in names.items()}
    if rid not in home_build.published():
        return gu, None, REGIONS[rid]["name"]
    x = json.loads((ROOT / "results_region" / f"{rid}.json").read_text())
    for code, name in names.items():
        r = x["regions"].get(name)
        sc = r["score"] if r else []
        t = max((i for i, v in enumerate(sc) if v is not None), default=None)
        if t is not None:
            gu[code].update(score=sc[t], month=x["dates"][t][:7])
    return gu, f"{rid}/", REGIONS[rid]["name"]


def main(rid=None):
    out = OUT if rid is None else OUT / rid
    out.mkdir(parents=True, exist_ok=True)
    b_, ftab, check = params(rid)
    mk = gu_market(rid)
    df = trades(mk, rid)
    dev = type_dev(df, b_).reindex(pd.MultiIndex.from_arrays([df["aptSeq"], df["type"]])).fillna(0).to_numpy()
    base = df["yf"].to_numpy() - b_ * df["la"].to_numpy() - dev  # 단지 안에서 평형을 맞춘 가격 (log)
    end = df["date"].max()
    since = end - pd.Timedelta(days=WINDOW_DAYS)
    seq, dates, typ = df["aptSeq"].to_numpy(), df["date"].to_numpy(), df["type"].to_numpy()
    price, floor, area, la = df["price"].to_numpy(), df["floor"].to_numpy(), df["area"].to_numpy(), df["la"].to_numpy()
    yf, mkv = df["yf"].to_numpy(), df["mk"].to_numpy()
    ds = df["date"].dt.strftime("%Y-%m-%d").to_numpy()
    bounds = np.flatnonzero(np.r_[True, seq[1:] != seq[:-1], True])

    cx = complexes(rid).set_index("aptSeq")
    code = None if rid is None else home(rid)  # 단지 → 화면용 지역 코드 (서울은 단지 번호 앞 5자리)
    if code is not None:
        cx = cx[cx.index.isin(code.index)]  # 이 지역 저장소에 거래가 있는 단지만
    key = (lambda s: s[:5]) if code is None else code.get
    bfile = ROOT / "data" / ("molit" if rid is None else "molit_kr") / "buildings.csv"
    bld = pd.read_csv(bfile, dtype=str, keep_default_na=False).set_index("aptSeq") if bfile.exists() else pd.DataFrame()
    # 실거래에선 여러 단지로 나뉘었지만 건축물대장은 한 장부인 경우 (예: 마포래미안푸르지오 1·2·3단지)
    shared = bld[bld["status"] == "ok"].groupby("lot").size() if len(bld) else pd.Series(dtype=int)
    detail = {g: {} for g in (LAWD2GU if rid is None else REGIONS[rid]["lawd"])}
    scored = mixed = types_out = 0
    for a, b in zip(bounds[:-1], bounds[1:]):
        s = seq[a]
        t = dates[a:b]
        types = []
        for T in sorted(set(typ[a:b][t > since.to_datetime64()])):
            i = a + np.flatnonzero(typ[a:b] == T)[-1]
            pool = pool_for(i, a, t, typ)
            # 보정가: 이 평형·8~10층·최근 거래 달 시세로 환산 (만원)
            adj = np.exp(base[pool] + b_ * la[i] + dev[i] + mkv[i])
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
            info = {k: r[k][:-2] if r[k].endswith(".0") else r[k] for k in bld.columns if r[k] != "" and k not in ("fetched", "status", "lot")}
            if shared.get(r["lot"], 1) > 1:
                info["shared"] = int(shared[r["lot"]])
        detail.setdefault(key(s), {})[s] = {
            "maxfl": None if np.isnan(floor[a:b]).all() else int(np.nanmax(floor[a:b])),
            "n2y": int((t > since.to_datetime64()).sum()),
            "lastAll": ds[b - 1],
            "types": sorted(types, key=lambda d: d["a"]),
            "info": info,
            "jibun": "" if row is None else row["jibun"],
        }

    gu_fg, fg_page, top = fg_scores(rid)  # 구 공포탐욕 점수 (지도와 같은 값)
    items = []
    for s, r in cx.iterrows():
        d = detail.get(key(s), {}).get(s)
        items.append([s, r["aptNm"], r["umdNm"], r["buildYear"], r["last"], 1 if d and any(x["k"] is not None for x in d["types"]) else 0,
                      "|".join(n for n in r["names"].split("|") if n != r["aptNm"]), key(s)])
    gdir = out / "gu"
    if gdir.exists():
        shutil.rmtree(gdir)
    gdir.mkdir()
    for g, d in detail.items():
        (gdir / f"{g}.json").write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
    if rid is None:
        quick = QUICK_SEOUL
    else:  # 예시: 최근 2년 거래가 가장 많은 단지 (점수가 나오는 곳)
        busy = sorted(((d["n2y"], s) for g in detail.values() for s, d in g.items() if any(x["k"] is not None for x in d["types"])), reverse=True)
        quick = [s for _, s in busy[:5]]
    meta = {"asof": end.strftime("%Y-%m-%d"), "region": rid or "seoul", "top": top, "fg_page": fg_page,
            "sub_word": "구" if rid is None else sub_word(rid), "quick": quick, "B": round(float(b_), 2),
            "check": check, "gu": gu_fg, "n_complex": len(items), "n_scored": scored, "n_mixed": mixed,
            "floor": dict(zip(["1층 이하", "2층", "3층", "4층", "5층", "6~7층", "8~10층", "11~14층", "15~19층", "20~29층", "30층 이상"],
                              [round(float(np.expm1(v)) * 100, 1) for v in ftab])),
            "has_info": bool(len(bld))}
    (out / "index.json").write_text(json.dumps({"meta": meta, "items": items}, ensure_ascii=False, separators=(",", ":")))
    size = sum(f.stat().st_size for f in [out / "index.json", *gdir.glob("*.json")]) / 1e6
    print(f"{top}: 기준일 {meta['asof']} · 단지 {len(items):,} · 최근 2년 거래 평형 {types_out:,} 중 점수 {scored:,} (다른 평형 섞임 {mixed:,}) · {size:.1f} MB", flush=True)


def targets(argv):
    """만들 지역: 인자로 준 것, 없으면 서울 + 저장소에 있는 모든 지역 (단지 이름을 아직 채우는 지역은 빼고 알림)."""
    want = argv or ["seoul", *region_store.regions_in_store()]
    out = []
    for r in want:
        if r != "seoul" and named_share(r) < NAMED:
            print(f"{REGIONS[r]['name']}: 단지 이름을 아직 채우는 중이라 건너뜀 (이름 있는 단지 {named_share(r):.0%})", flush=True)
            continue
        out.append(None if r == "seoul" else r)
    return out


def run_all(fn, argv):
    """지역마다 fn(rid)을 돌린다. 한 지역이 실패해도 나머지는 만든다.
    종료 코드: 0 = 모두 성공, 1 = 서울 실패 (화면 배포를 멈춤), 2 = 서울 밖 일부 지역만 실패 (그 지역은 빼고 배포, 월간 갱신은 알림)."""
    import traceback
    bad = []
    for rid in targets(argv):
        try:
            fn(rid)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            bad.append(rid or "seoul")
    if bad:
        print("실패한 지역:", ", ".join(bad), flush=True)
    return 1 if "seoul" in bad else 2 if bad else 0


if __name__ == "__main__":
    sys.exit(run_all(main, sys.argv[1:]))
