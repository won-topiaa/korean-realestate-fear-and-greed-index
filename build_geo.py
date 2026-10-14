"""서울 구 경계(통계청 2013, southkorea/seoul-maps) → 권역 병합 → SVG 경로 (data/seoul_map.json).
한강은 Natural Earth 10m 하천 중심선을 서울 경계로 잘라 사용. 입력 파일 경로는 인자로 받음."""
import json
import math
import sys
from pathlib import Path

from shapely.geometry import LineString, MultiLineString, shape
from shapely.ops import unary_union

from zone_fetch import ZONES

gu_path, river_path, out_path = sys.argv[1:4]
GU2ZONE = {g: z for z, gs in ZONES.items() for g in gs}
LAT0 = 37.55
K = math.cos(math.radians(LAT0))

feats = json.loads(Path(gu_path).read_text())["features"]
gus = {f["properties"]["name"]: shape(f["geometry"]).buffer(0) for f in feats}
assert set(gus) == set(GU2ZONE), set(gus) ^ set(GU2ZONE)
seoul = unary_union(list(gus.values()))
minx, miny, maxx, maxy = seoul.bounds
W = 800.0
scale = W / ((maxx - minx) * K)
H = (maxy - miny) * scale
PAD = 10


def xy(lon, lat):
    return PAD + (lon - minx) * K * scale, PAD + (maxy - lat) * scale


def ring(coords):
    pts = [xy(*c[:2]) for c in coords]
    return "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z"


def path(geom):
    polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    return "".join(ring(p.exterior.coords) + "".join(ring(i.coords) for i in p.interiors) for p in polys)


def label(geom):
    c = geom.representative_point() if not geom.contains(geom.centroid) else geom.centroid
    return [round(v, 1) for v in xy(c.x, c.y)]


zones = {}
for z, gs in ZONES.items():
    u = unary_union([gus[g] for g in gs]).buffer(0.0004).buffer(-0.0004)  # 구 경계 틈 메우기
    zones[z] = {"d": path(u), "label": label(u)}
gu_out = {g: {"zone": GU2ZONE[g], "d": path(geom), "label": label(geom)} for g, geom in gus.items()}

rv = json.loads(Path(river_path).read_text())
lines = []
for f in rv["features"]:
    if f["properties"].get("name") == "Han":
        g = f["geometry"]
        for cs in (g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]):
            lines.append(LineString(cs))
han = unary_union(lines).intersection(seoul)
han_lines = [han] if han.geom_type == "LineString" else list(getattr(han, "geoms", []))
river = "".join("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in (xy(*c) for c in l.coords)) for l in han_lines if l.length > 0)

out = {"w": round(W + 2 * PAD, 1), "h": round(H + 2 * PAD, 1), "zones": zones, "gu": gu_out, "river": river,
       "outline": path(seoul.buffer(0))}
Path(out_path).write_text(json.dumps(out, ensure_ascii=False))
print("viewBox", out["w"], out["h"], "| bytes", len(json.dumps(out, ensure_ascii=False)), "| river segs", len(han_lines))
for z, v in zones.items():
    print(z, v["label"])
