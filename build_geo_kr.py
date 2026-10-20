"""전국 시도 지도(data/korea_map.json, 첫 화면)와 수도권·광역시 시군구 지도(data/region_maps/{지역}.json) → SVG 경로.

경계: 브이월드 시군구 경계(LT_C_ADSIGG_INFO, 국토교통부, 2026년 코드). 받은 원자료는 data/raw/geo/vworld_sigg/에 캐시 (저장소에 안 올림).
시도는 시군구를 코드 앞 두 자리로 합친다. 12(전남광주통합특별시)는 옛 광주광역시 다섯 구를 '광주', 나머지를 '전남'으로 나눈다.
경로는 바깥 고리를 반시계, 구멍을 시계 방향으로 맞춰 둔다 (서울은 경기의 구멍 → 기본 채우기 규칙에서도 비어 보임).
사용: python build_geo_kr.py   (키는 .env의 VWORLD_KEY)
"""
import json
import math
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode

from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.geometry.polygon import orient
from shapely.ops import polylabel, unary_union

from regions import REGIONS

ROOT = Path(__file__).parent
CACHE = ROOT / "data" / "raw" / "geo" / "vworld_sigg"
OUT = ROOT / "data" / "region_maps"
PREFIX = {"11": "서울", "26": "부산", "27": "대구", "28": "인천", "30": "대전", "31": "울산", "36": "세종", "41": "경기",
          "43": "충북", "44": "충남", "47": "경북", "48": "경남", "50": "제주", "51": "강원", "52": "전북", "12": None}
GWANGJU = {"12210", "12240", "12270", "12300", "12330"}
ORDER = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]
ULLEUNG = "47940"  # 울릉도·독도는 작아도 남김


def fetch(prefix):
    path = CACHE / f"{prefix}.json"
    if path.exists():
        return json.loads(path.read_text())
    key = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().split())["VWORLD_KEY"]
    feats, page = [], 1
    while True:
        q = urlencode({"service": "data", "request": "GetFeature", "data": "LT_C_ADSIGG_INFO", "key": key, "geometry": "true",
                       "attribute": "true", "format": "json", "size": 1000, "page": page, "crs": "EPSG:4326",
                       "attrFilter": f"sig_cd:like:{prefix}"})
        out = subprocess.run(["curl", "-sS", "-m", "120", "https://api.vworld.kr/req/data?" + q], capture_output=True, text=True)
        r = json.loads(out.stdout)["response"]
        if r["status"] != "OK":
            raise RuntimeError(f"{prefix} {page}쪽: {r['status']} {r.get('error', {}).get('text', '')}")
        feats += r["result"]["featureCollection"]["features"]
        if page >= int(r["page"]["total"]):
            break
        page += 1
        time.sleep(0.5)
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(feats, ensure_ascii=False))
    return feats


def parts(g):
    return [g] if g.geom_type == "Polygon" else list(getattr(g, "geoms", []))


class Proj:
    """경위도 → 화면 좌표 (경도 축을 cos(기준 위도)로 줄인 등장방형, 위가 북쪽)."""

    def __init__(self, geom, width, pad=10):
        minx, miny, maxx, maxy = geom.bounds
        self.k = math.cos(math.radians((miny + maxy) / 2))
        self.minx, self.maxy, self.pad = minx, maxy, pad
        self.s = width / ((maxx - minx) * self.k)
        self.w, self.h = width + 2 * pad, (maxy - miny) * self.s + 2 * pad

    def xy(self, lon, lat):
        return self.pad + (lon - self.minx) * self.k * self.s, self.pad + (self.maxy - lat) * self.s

    def px2(self, g):  # 화면 위 넓이 (px²)
        return g.area * self.k * self.s ** 2

    def ring(self, coords):
        return "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in (self.xy(*c[:2]) for c in coords)) + "Z"

    def path(self, g):
        return "".join(self.ring(p.exterior.coords) + "".join(self.ring(i.coords) for i in p.interiors)
                       for p in (orient(p, 1.0) for p in parts(g)))

    def label(self, g, avoid=None):
        main = max(parts(g), key=lambda p: p.area)
        if avoid is not None:  # 다른 지역(서울·인천) 쪽을 피한 안쪽 점
            rest = main.difference(avoid)
            main = max(parts(rest), key=lambda p: p.area) if not rest.is_empty else main
        c = polylabel(main, tolerance=0.002)
        return [round(v, 1) for v in self.xy(c.x, c.y)]


def drop_specks(g, proj, min_px2):
    """화면에서 min_px2보다 작은 섬과 구멍(경계 틈)을 지운다."""
    ps = [Polygon(p.exterior, [i for i in p.interiors if proj.px2(Polygon(i)) >= min_px2])
          for p in parts(g) if proj.px2(p) >= min_px2]
    return unary_union(ps) if ps else Polygon(max(parts(g), key=lambda p: p.area).exterior)


def load():
    sigg = {}
    for pre in PREFIX:
        for f in fetch(pre):
            sigg[f["properties"]["sig_cd"]] = (f["properties"]["full_nm"], shape(f["geometry"]).buffer(0))
    return sigg


def korea(sigg):
    groups = {}
    for cd, (_, g) in sigg.items():
        name = PREFIX[cd[:2]] or ("광주" if cd in GWANGJU else "전남")
        groups.setdefault(name, []).append((cd, g))
    assert set(groups) == set(ORDER), set(groups) ^ set(ORDER)
    rough = Proj(unary_union([g for _, g in sigg.values()]).envelope, 560)
    tol = 0.01  # 약 1px
    prov = {}
    for name, items in groups.items():
        u = unary_union([g for _, g in items]).buffer(0.002).buffer(-0.002)  # 시군구 경계 틈 메우기
        u = u.simplify(tol, preserve_topology=True)
        uls = [p for cd, g in items if cd == ULLEUNG for p in parts(g) if p.area > 5e-6]  # 울릉도·독도 (암초는 뺌)
        keep = unary_union(uls).simplify(tol / 3, preserve_topology=True) if uls else None
        u = drop_specks(u, rough, 10)
        prov[name] = unary_union([u, keep]) if keep is not None else u
    allg = unary_union(list(prov.values()))
    proj = Proj(allg, 560)
    avoid = {"경기": unary_union([prov["서울"], prov["인천"]]).buffer(0.12), "인천": prov["서울"].buffer(0.12)}  # 수도권 이름이 겹치지 않게
    out = {"w": round(proj.w, 1), "h": round(proj.h, 1),
           "provinces": {n: {"d": proj.path(prov[n]), "label": proj.label(prov[n], avoid.get(n))} for n in ORDER},
           "outline": proj.path(drop_specks(allg.buffer(0.02).buffer(-0.02).simplify(tol, preserve_topology=True), proj, 10))}
    return out


def region(rid, sigg):
    codes = REGIONS[rid]["lawd"]
    missing = [c for c in codes if c not in sigg]
    assert not missing, f"{rid}: 경계에 없는 코드 {missing}"
    geoms = {c: sigg[c][1] for c in codes}
    if rid == "incheon":  # 옹진군: 서해5도·덕적군도는 빼고 육지 가까운 섬(북도면·영흥면 등)만 (지도가 바다로 비지 않게)
        geoms["28720"] = unary_union([p for p in parts(geoms["28720"]) if p.centroid.x >= 126.35])
    rough = Proj(unary_union(list(geoms.values())), 800)
    span = max(rough.w, rough.h) / rough.s  # 대략 도 단위 크기
    tol = span * 0.0013
    simp = {c: drop_specks(g.simplify(tol, preserve_topology=True), rough, 20) for c, g in geoms.items()}
    allg = unary_union(list(simp.values()))
    proj = Proj(allg, 800)
    areas = {c: {"name": codes[c], "d": proj.path(g), "label": proj.label(g)} for c, g in simp.items()}
    outline = drop_specks(allg.buffer(tol).buffer(-tol).simplify(tol, preserve_topology=True), proj, 20)
    return {"w": round(proj.w, 1), "h": round(proj.h, 1), "areas": areas, "outline": proj.path(outline)}


if __name__ == "__main__":
    sigg = load()
    print("시군구", len(sigg))
    k = korea(sigg)
    txt = json.dumps(k, ensure_ascii=False, separators=(",", ":"))
    (ROOT / "data" / "korea_map.json").write_text(txt)
    print("korea_map.json", k["w"], k["h"], f"{len(txt) / 1024:.0f} KB", {n: v["label"] for n, v in k["provinces"].items()})
    OUT.mkdir(parents=True, exist_ok=True)
    for rid in REGIONS:
        r = region(rid, sigg)
        txt = json.dumps(r, ensure_ascii=False, separators=(",", ":"))
        (OUT / f"{rid}.json").write_text(txt)
        print(f"{rid}.json", r["w"], r["h"], f"{len(txt) / 1024:.0f} KB", len(r["areas"]), "곳")
