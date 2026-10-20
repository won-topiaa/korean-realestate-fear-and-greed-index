"""수도권·광역시 원자료: 부동산원 R-ONE(시도·시군구 거래 통계, 수급지수, 미분양)과 KB(시군구 매매·전세지수, 전세가율).

KB 시도 값(설문·가격·전세가율)은 서울과 같은 KB 파일에 이미 있다. 여기서는 시군구 자료와 부동산원 지역 자료만 받는다.
파일: data/raw/reb/r_{지역id}_{통계}.json (시도), data/raw/reb/r_{코드}_{통계}.json (시군구), data/raw/kb/{통계}_{지역id}.json
부동산원에 이름이 없는 시군구(새로 생긴 구의 옛 기간 등)는 건너뛰고, 계산 때 시도 값을 쓴다.

사용: python region_src_fetch.py [--refresh]
"""
import sys
from concurrent.futures import ThreadPoolExecutor

import kb_fetch as K
import reb_fetch as R
from regions import REGIONS

KB_SUB = {
    "아파트매매지수_월간": ("priceIndex", {"월간주간구분코드": "01", "매물종별구분": "01", "매매전세코드": "01", "기간": "99"}),
    "아파트전세지수_월간": ("priceIndex", {"월간주간구분코드": "01", "매물종별구분": "01", "매매전세코드": "02", "기간": "99"}),
    "전세가율_아파트": ("dealCntstTnantRato", {"매물종별구분": "01"}),
}
TRADE = [("A_2024_00609", "매입자거주지"), ("A_2024_00610", "매입자연령"), ("A_2024_00611", "거래주체")]


def _id(sid, tag, full):
    return next((x["ITM_ID"] for x in R.items(sid) if x["ITM_TAG"] == tag and x["ITM_FULLNM"] == full), None)


def reb_jobs(rid):
    """(통계표, 저장 이름, 필터) 목록과 부동산원에 없는 이름."""
    d = REGIONS[rid]
    jobs, missing = [], []

    def add(sid, name, tag, full, item=100001):
        i = _id(sid, tag, full)
        if i is None:
            missing.append(f"{name}({full})")
            return
        jobs.append((sid, name, {"CLS_ID" if tag == "분류" else "GRP_ID": i, "ITM_ID": item}))

    for sid, nm in [("A_2024_00076", "매매수급"), ("A_2024_00077", "전세수급")]:
        add(sid, f"r_{rid}_{nm}", "분류", d["reb_sup"])
    if not d.get("reb_sum_subs"):  # 시군구 합으로 쓰는 지역은 시도 값을 받지 않는다
        add("A_2024_00554", f"r_{rid}_거래량", "분류", d["reb"])
        for sid, nm in TRADE:
            add(sid, f"r_{rid}_{nm}", "그룹", d["reb"])
        add("T237973129847263", f"r_{rid}_미분양", "분류", f"{d['reb_unsold']}>계", item=10001)
    sub = d.get("reb_sub", d["reb"])
    for lawd, n in d["lawd"].items():
        full = f"{sub}>{n.replace(' ', '>')}"
        add("A_2024_00554", f"r_{lawd}_거래량", "분류", full)
        for sid, nm in TRADE:
            add(sid, f"r_{lawd}_{nm}", "그룹", full)
        if d.get("reb_sum_subs"):
            add("T237973129847263", f"r_{lawd}_미분양", "분류", full, item=10001)
    return jobs, missing


def refresh(refresh=True, workers=4):
    jobs, missing = [], []
    for rid in REGIONS:
        j, m = reb_jobs(rid)
        jobs += j
        missing += m
    errors = []

    def one(job):
        sid, name, f = job
        try:
            R.data(sid, "MM", name=name, refresh=refresh, **f)
        except Exception as e:  # noqa: BLE001  (실패한 시계열은 지난 파일 유지)
            errors.append(f"{name}: {str(e)[:160]}")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, jobs))
    kb_fail = []
    for rid, d in REGIONS.items():
        for nm, (ep, p) in KB_SUB.items():
            try:
                K.fetch(ep, {**p, "지역코드": d["kb_code"]}, f"{nm}_{rid}", refresh=refresh)
            except Exception as e:  # noqa: BLE001
                kb_fail.append(f"{nm}_{rid}: {str(e)[:80]}")
    if len(errors) == len(jobs):
        raise RuntimeError(f"지역 부동산원 전부 실패 · 예: {errors[0]}")
    msg = f"지역 부동산원 {len(jobs) - len(errors)}/{len(jobs)}개 · KB 시군구 {len(REGIONS) * len(KB_SUB) - len(kb_fail)}/{len(REGIONS) * len(KB_SUB)}개"
    if errors or kb_fail:
        msg += f" · 실패 예: {(errors + kb_fail)[0]}"
    return msg, missing


if __name__ == "__main__":
    msg, missing = refresh(refresh="--refresh" in sys.argv)
    print(msg)
    if missing:
        print("부동산원에 없는 이름 (시도 값으로 대신):", len(missing), missing[:30])
