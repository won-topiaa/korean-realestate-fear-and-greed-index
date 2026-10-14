"""권역·구 단위 원자료 수집 (부동산원 R-ONE, KB). 서울 5대 권역 = 부동산원 구분."""
import reb_fetch as R
from kb_fetch import fetch as kb

ZONES = {
    "도심권": ["종로구", "중구", "용산구"],
    "동북권": ["성동구", "광진구", "동대문구", "중랑구", "성북구", "강북구", "도봉구", "노원구"],
    "서북권": ["은평구", "서대문구", "마포구"],
    "서남권": ["양천구", "강서구", "구로구", "금천구", "영등포구", "동작구", "관악구"],
    "동남권": ["서초구", "강남구", "송파구", "강동구"],
}
GU = [g for gs in ZONES.values() for g in gs]


def ids(sid, tag, prefix):
    """분류/그룹 중 '서울>…구'로 끝나는 항목의 {구: ID}."""
    out = {}
    for x in R.items(sid):
        if x["ITM_TAG"] == tag and x["ITM_FULLNM"].startswith(prefix):
            name = x["ITM_FULLNM"].split(">")[-1]
            if name in GU or name in ZONES:
                out[name] = x["ITM_ID"]
    return out


if __name__ == "__main__":
    # 권역 단위 수급지수 (월, 2012.7~)
    for sid, nm in [("A_2024_00076", "매매수급"), ("A_2024_00077", "전세수급")]:
        for z, cid in ids(sid, "분류", "서울>").items():
            if z in ZONES:
                R.data(sid, "MM", name=f"zone_{nm}_{z}", CLS_ID=cid, ITM_ID=100001)
    # 구 단위 거래 통계 (월, 2006~)
    for g, cid in ids("A_2024_00554", "분류", "서울>").items():
        R.data("A_2024_00554", "MM", name=f"gu_거래량_{g}", CLS_ID=cid, ITM_ID=100001)
    for sid, nm in [("A_2024_00609", "매입자거주지"), ("A_2024_00610", "매입자연령"), ("A_2024_00611", "거래주체")]:
        for g, gid in ids(sid, "그룹", "서울>").items():
            R.data(sid, "MM", name=f"gu_{nm}_{g}", GRP_ID=gid, ITM_ID=100001)
    for g, cid in ids("T237973129847263", "분류", "서울>").items():
        R.data("T237973129847263", "MM", name=f"gu_미분양_{g}", CLS_ID=cid, ITM_ID=10001)
    # KB 구별 전세지수, 전세가율
    kb("priceIndex", {"월간주간구분코드": "01", "매물종별구분": "01", "매매전세코드": "02", "기간": "99", "지역코드": "1100000000"}, "아파트전세지수_월간_서울구")
    kb("dealCntstTnantRato", {"매물종별구분": "01", "지역코드": "1100000000"}, "전세가율_아파트_서울구")
    import json, glob
    print("zone files:", len(glob.glob("data/raw/reb/zone_*.json")), "| gu files:", len(glob.glob("data/raw/reb/gu_*.json")))
    for n in ["아파트전세지수_월간_서울구", "전세가율_아파트_서울구"]:
        d = json.load(open(f"data/raw/kb/{n}.json"))
        print(n, d["날짜리스트"][0], d["날짜리스트"][-1], [x["지역명"] for x in d["데이터리스트"]][:5], len(d["데이터리스트"]))
