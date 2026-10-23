"""링크 미리보기 이미지 (카카오톡·문자·SNS에 링크를 보낼 때 뜨는 그림) → assets/og/{페이지}.jpg (1200×630).

사이트와 같은 모습(페이지 사진을 어둡게 깐 바탕 + 로고 + 굵은 제목)에, 오른쪽에 그 페이지를 보여 주는 그림을 얹는다.
- 지도 페이지(첫 화면·서울·지역): 이번 달 점수와 0~100 막대, 점수 색으로 칠한 지도 (사이트 지도와 같은 색)
- 단지 검색: 0~100점 막대 · 신고가: 신고가 비중 막대그래프 · 모의 투자: 서울 실거래 지수 · 보고서: 지수 추이 · API: 응답 예시
점수가 들어가므로 월간 자동 갱신이 매달 다시 만든다 (monthly-update.yml, 실패해도 갱신은 계속). 화면을 고쳤을 때는 로컬에서 같은 명령.
헤드리스 Chrome으로 찍고, 글꼴은 사이트와 같은 Google Fonts라 인터넷 연결이 필요하다 (서버는 한글이 빠지지 않게 Noto CJK도 설치).
사용: python og_build.py [페이지 ...]   (없으면 전부, 예: python og_build.py home seoul. Chrome 위치는 CHROME 환경변수)
"""
import html as _html
import json
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from regions import REGIONS, sub_word

ROOT = Path(__file__).parent
OUT = ROOT / "assets" / "og"
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
SITE = "aptfeargreed.com"
TRADE_ONLY = {"apt", "highs", "sim"}  # 실거래만 쓰는 페이지. 지수 페이지는 원자료 출처에 KB부동산을 함께 적는다 (KB 담당자 답변, 2026-10-23)

# 사이트 어두운 화면의 색 (map/template.html)
FEAR, GREED, NEUTRAL, MAP_NEUTRAL, MAP_NA = "#3987e5", "#e66767", "#74777d", "#2b2c2f", "#222326"
BANDS = ["극단적 공포", "공포", "중립", "탐욕", "극단적 탐욕"]


def band(v):
    r = round(v)
    return 0 if r < 25 else 1 if r < 45 else 2 if r < 55 else 3 if r < 75 else 4


def band_color(v):
    return [FEAR, FEAR, NEUTRAL, GREED, GREED][band(v)]


def fill(v):
    """사이트 지도와 같은 칠: 50에서 멀수록 진하게."""
    if v is None:
        return MAP_NA
    d = v - 50
    p = min(85, abs(d) / 40 * 85)
    return f"color-mix(in oklab, {GREED if d >= 0 else FEAR} {p:.0f}%, {MAP_NEUTRAL})"


def ym(s):
    return f"{s[:4]}년 {int(s[5:7])}월"


def esc(s):
    return _html.escape(str(s))


def load(p):
    return json.loads((ROOT / p).read_text())


def last(series):
    """(마지막 값, 그 앞 값, 위치)."""
    i = max(k for k, v in enumerate(series) if v is not None)
    prev = next((series[k] for k in range(i - 1, -1, -1) if series[k] is not None), None)
    return series[i], prev, i


def region(rid):
    """지도 페이지 자료: (이름, 자료 dict, 맨 위 지역 이름, 공개 여부)."""
    if rid == "seoul":
        return "서울", load("results_zone/map_data.json"), "서울", True
    d = load(f"results_region/{rid}.json")
    eng = ROOT / "data" / "region_engine.json"
    pub = json.loads(eng.read_text()).get("publish", {}).get(rid, False) if eng.exists() else False
    return REGIONS[rid]["name"], d, d["top"], pub


def map_svg(geo_w, geo_h, shapes, outline=None, w=520, h=500):
    """shapes: [(path d, 칠)]."""
    ps = "".join(f'<path d="{x[0]}" style="fill:{x[1]}"{f' class="{x[2]}"' if len(x) > 2 else ""}/>' for x in shapes)
    ol = f'<path d="{outline}" class="ol"/>' if outline else ""
    return (f'<svg class="map" width="{w}" height="{h}" viewBox="0 0 {geo_w} {geo_h}" preserveAspectRatio="xMidYMid meet">'
            f'<g class="sh">{ps}</g>{ol}</svg>')


def gauge(v):
    segs = "".join(f"<i style=\"background:{c};opacity:{o}\"></i>" for c, o in
                   [(FEAR, 1), (FEAR, .55), (NEUTRAL, .8), (GREED, .55), (GREED, 1)])
    pin = f'<b class="gpin" style="left:{max(0.6, min(99.4, v))}%"></b>' if v is not None else ""
    return (f'<div class="gauge"><div class="gbar">{segs}{pin}</div>'
            '<div class="glab"><span>0 극단적 공포</span><span>50 중립</span><span>극단적 탐욕 100</span></div></div>')


def chip(v):
    c = band_color(v)
    return f'<span class="chip" style="border-color:{c};background:color-mix(in oklab, {c} 22%, transparent)">{BANDS[band(v)]}</span>'


def map_page(rid):
    name, d, top, pub = region(rid)
    v, prev, i = last(d["regions"][top]["score"])
    month = d["dates"][i]
    geo = d["geo"]
    subs = geo.get("gu") or {}
    shapes = [(s["d"], fill(d["regions"][n]["score"][i] if n in d["regions"] else None)) for n, s in subs.items()]
    n_sub = len([n for n in subs if n in d["regions"]])
    sw = "구" if rid == "seoul" else sub_word(rid)
    if pub:
        dd = None if prev is None else round(v) - round(prev)
        delta = "" if dd is None else " · 지난달과 같아요" if dd == 0 else f' · 지난달 {round(prev)}에서 {"▲" if dd > 0 else "▼"} {abs(dd)}'
        left = [f'<div class="score"><span class="num">{round(v)}</span>{chip(v)}</div>',
                f'<div class="sub">{ym(month)} 기준{delta} · {n_sub}개 {sw}</div>', gauge(v)]
    else:
        left = ['<div class="score"><span class="num small">검증 중</span></div>',
                f'<div class="sub">정확도 기준을 넘으면 공개해요 · {n_sub}개 {sw}</div>', gauge(None)]
    right = map_svg(geo["w"], geo["h"], shapes, geo.get("outline"))
    return f"{esc(name)} 아파트", "공포탐욕지도", "".join(left), right


def home_page():
    km = load("data/korea_map.json")
    rows, live = [], {}
    for rid in ["seoul", *REGIONS]:
        name, d, top, pub = region(rid)
        if not pub:
            continue
        v, _, i = last(d["regions"][top]["score"])
        live[name], month = v, d["dates"][i]
        rows.append((v, name))
    rows.sort(reverse=True)
    cells = "".join(f'<div class="cell"><span class="cn">{esc(n)}</span><span class="cv" style="color:{band_color(v)}">{round(v)}</span>'
                    f'<span class="cb">{BANDS[band(v)]}</span></div>' for v, n in rows)
    shapes = [(p["d"], "#1d1e21", "off") for n, p in km["provinces"].items() if n not in live]
    shapes += [(p["d"], fill(live[n]), "live") for n, p in km["provinces"].items() if n in live]  # 위에 그려 테두리가 덮이지 않게
    left = (f'<div class="kicker">{ym(month)} 기준 · 지수가 있는 지역 {len(rows)}곳</div>'
            f'<div class="grid">{cells}</div>')
    return "지역별 아파트", "공포탐욕지도", left, map_svg(km["w"], km["h"], shapes, km.get("outline"), 460, 500)


def chart_line(vals, w=420, h=280, lo=None, hi=None, bands=False, color="#ffffff"):
    xs = [k for k, v in enumerate(vals) if v is not None]
    lo = min(vals[k] for k in xs) if lo is None else lo
    hi = max(vals[k] for k in xs) if hi is None else hi
    X = lambda k: k / (len(vals) - 1) * w
    Y = lambda v: h - (v - lo) / (hi - lo) * h
    pts = " ".join(f"{X(k):.1f},{Y(vals[k]):.1f}" for k in xs)
    bg = ""
    if bands:  # 지수 구간 띠 (사이트 추이 그래프와 같게)
        for a, b, c, o in [(0, 25, FEAR, .32), (25, 45, FEAR, .14), (45, 55, NEUTRAL, .12), (55, 75, GREED, .14), (75, 100, GREED, .32)]:
            bg += f'<rect x="0" y="{Y(b):.1f}" width="{w}" height="{Y(a) - Y(b):.1f}" fill="{c}" opacity="{o}"/>'
    k = xs[-1]
    return (f'<svg class="chart" width="{w}" height="{h}" viewBox="0 0 {w} {h}">{bg}'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="3" stroke-linejoin="round"/>'
            f'<circle cx="{X(k):.1f}" cy="{Y(vals[k]):.1f}" r="7" fill="{color}"/></svg>')


def tool_page(name):
    md = load("results_zone/map_data.json")
    dates = md["dates"]
    if name == "apt":
        n = sum(len(json.loads(f.read_text())["items"]) for f in (ROOT / "results_apt").glob("**/index.json")) if (ROOT / "results_apt").exists() else 0
        left = (f'<div class="kicker">서울·수도권·광역시 {n:,}개 단지 · 최근 2년 실거래</div>' if n else '<div class="kicker">서울·수도권·광역시 · 최근 2년 실거래</div>')
        left += '<div class="lead">우리 단지 가장 최근 거래가<br>최근 거래 중 어디쯤인지 0~100점으로</div>'
        segs = "".join(f'<i style="background:{c};opacity:{o}"></i>' for c, o in [(FEAR, 1), (FEAR, .55), (NEUTRAL, .8), (GREED, .55), (GREED, 1)])
        right = (f'<div class="panel"><div class="pt">가장 최근 거래</div><div class="pbig">비싼 편<span>72 / 100점</span></div>'
                 f'<div class="gauge"><div class="gbar">{segs}<b class="gpin" style="left:72%"></b></div>'
                 '<div class="glab"><span>가장 싼 쪽</span><span>중간쯤</span><span>가장 비싼 쪽</span></div></div>'
                 '<div class="pnote">층·거래 시기를 맞춰 같은 단지 최근 10건과 비교 · 세대수·용적률 같은 단지 정보도</div>'
                 '<div class="pex">보기 그림이에요</div></div>')
        return "최근 실거래가, 비싼 편일까?", "단지 검색", left, right
    if name == "highs":
        h = load("results_highs/highs.json") if (ROOT / "results_highs" / "highs.json").exists() else None
        if h:
            full = [m for m in h["months"] if m["ym"] <= dates[-1]][0]
            share = full["high"] / full["cmp"] if full["cmp"] else 0
            tr = [(a, b / c if c else 0) for a, b, c in h["trend"] if a <= full["ym"]][-30:]
            top = max(s for _, s in tr) or 1
            bw = 420 / len(tr)
            bars = "".join(f'<rect x="{k * bw + 2:.1f}" y="{280 - s / top * 260:.1f}" width="{bw - 4:.1f}" height="{s / top * 260:.1f}" '
                           f'fill="{GREED if k == len(tr) - 1 else "#5a5a5a"}"/>' for k, (_, s) in enumerate(tr))
            left = (f'<div class="kicker">{ym(full["ym"])} 서울</div>'
                    f'<div class="stats"><div><b>{full["high"]:,}</b><span>신고가 거래</span></div><div><b>{share * 100:.0f}%</b><span>신고가 비중</span></div>'
                    f'<div><b>{full["complexes"]:,}</b><span>신고가 단지</span></div></div>'
                    '<div class="lead small">같은 단지·같은 평형의 지난 모든 거래보다 비싸게 팔린 거래</div>')
            right = (f'<div class="panel"><div class="pt">서울 신고가 비중 · 최근 {len(tr)}개월</div>'
                     f'<svg class="chart" width="420" height="290" viewBox="0 0 420 290">{bars}</svg>'
                     f'<div class="axis"><span>{ym(tr[0][0])}</span><span>{ym(tr[-1][0])}</span></div></div>')
        else:
            left, right = '<div class="lead">같은 단지·같은 평형의 지난 모든 거래보다 비싸게 팔린 거래</div>', ""
        return "이번 달 가장 비싸게 팔린 집", "신고가 단지", left, right
    if name == "sim":
        rs = md["regions"]["서울"]["rs"]
        v1, _, i1 = last(rs)
        i0 = next(k for k, v in enumerate(rs) if v is not None)
        left = ('<div class="kicker">2006년부터의 실제 거래 가격으로 계산</div>'
                '<div class="lead">단지 2~3개를 골라 같은 기간의<br>가격 변화를 나란히 비교해요</div>'
                '<div class="lead small">산 때와 판 때의 공포탐욕지수도 함께 보여 드려요</div>')
        right = (f'<div class="panel"><div class="pt">서울 아파트 실거래 지수 · {dates[i0][:4]}~{dates[i1][:4]}</div>'
                 f'{chart_line(rs, color=GREED)}<div class="axis"><span>{dates[i0][:4]}</span>'
                 f'<span>{ym(dates[i1])} · {dates[i0][:4]}년의 {v1 / rs[i0]:.1f}배</span></div></div>')
        return "그때 샀다면 지금 얼마?", "모의 투자", left, right
    if name == "report":
        sc = md["regions"]["서울"]["score"]
        v, _, i = last(sc)
        left = ('<div class="kicker">서울 아파트 공포탐욕지수 v3.5</div>'
                '<div class="lead">실거래 141만 건으로 검증한<br>지수의 정확도와 한계</div>'
                '<div class="lead small">어떤 지표를 어떻게 묶었는지, 어디서 틀렸는지까지</div>')
        right = (f'<div class="panel"><div class="pt">서울 공포탐욕지수 · 2006~{dates[i][:4]}</div>'
                 f'{chart_line(sc, lo=0, hi=100, bands=True)}<div class="axis"><span>2006</span><span>{ym(dates[i])} {round(v)}</span></div></div>')
        return "서울 공포탐욕지수", "백테스트", left, right
    if name == "api":
        rows = []
        for rid in ["seoul", *REGIONS]:
            nm, d, top, pub = region(rid)
            if pub:
                v, _, i = last(d["regions"][top]["score"])
                rows.append((rid, v, d["dates"][i]))
        body = ",\n".join(f'    {{ "id": "{r}", "score": {v:.1f} }}' for r, v, _ in rows[:5])
        code = f'GET /api/v1/latest.json\n\n{{\n  "month": "{rows[0][2]}",\n  "regions": [\n{body},\n    …\n  ]\n}}'
        left = ('<div class="kicker">키 없이 · CORS 허용 · 매달 20일 갱신</div>'
                '<div class="lead">아파트 공포탐욕지수를<br>JSON·CSV로 가져다 쓰세요</div>'
                '<div class="lead small">서울·5대 권역·25개 구와 수도권·광역시 시군구, 2006년부터 월별</div>')
        return "아파트 공포탐욕지수", "데이터 API", left, f'<pre class="code">{esc(code).replace("GET", '<span class="c">GET</span>', 1)}</pre>'
    raise KeyError(name)


PHOTO = {"home": ("bg-map", "50%"), "seoul": ("bg-map", "50%"), "apt": ("bg-apt", "40%"), "highs": ("bg-highs", "45%"),
         "sim": ("bg-sim", "38%"), "report": ("bg-report", "50%"), "api": ("bg-report", "40%")}
for _rid in REGIONS:
    PHOTO[_rid] = (f"bg-{_rid}" if (ROOT / "assets" / "img" / f"bg-{_rid}.jpg").exists() else "bg-map", "50%")
PAGES = ["home", "seoul", *REGIONS, "apt", "highs", "sim", "report", "api"]

CSS = """
* { box-sizing: border-box; margin: 0; }
html, body { width: 1200px; height: 630px; overflow: hidden; background: #121212; }
.card { position: relative; width: 1200px; height: 630px; color: #fff; word-break: keep-all; font-family: "Noto Sans KR", "Noto Sans CJK KR", sans-serif; overflow: hidden; }
.bg { position: absolute; inset: 0; background: #1d1d1d url('__IMG__') center __Y__ / cover no-repeat; filter: grayscale(.35); }
.shade { position: absolute; inset: 0; background: linear-gradient(90deg, rgba(14,14,14,.95) 0%, rgba(14,14,14,.9) 48%, rgba(14,14,14,.72) 100%); }
.in { position: absolute; inset: 0; padding: 50px 60px 44px; display: grid; grid-template-columns: 560px 1fr; column-gap: 40px; }
.l { display: flex; flex-direction: column; min-width: 0; }
.r { display: grid; place-items: center; }
.logo { display: grid; line-height: 1.15; }
.logo .en { font-family: "Poiret One", sans-serif; font-size: 30px; letter-spacing: .04em; }
.logo .ko { font-size: 17px; font-weight: 600; color: #d0d0d0; }
.h { margin-top: 26px; display: grid; gap: 2px; }
.h .a { font-size: 34px; font-weight: 600; letter-spacing: -.02em; color: #ececec; }
.h .b { font-family: "Archivo", "Noto Sans KR", sans-serif; font-size: 74px; font-weight: 900; font-stretch: 112%; letter-spacing: -.025em; line-height: 1.02; }
.body { margin-top: 22px; display: grid; gap: 14px; align-content: start; }
.kicker { font-size: 21px; color: #bdbdbd; font-weight: 500; }
.score { display: flex; align-items: center; gap: 22px; margin-top: -6px; }
.num { font-family: "Archivo", sans-serif; font-size: 132px; font-weight: 900; font-stretch: 105%; line-height: .9; letter-spacing: -.03em; font-variant-numeric: tabular-nums; }
.num.small { font-family: "Noto Sans KR", sans-serif; font-size: 64px; font-weight: 800; line-height: 1.2; }
.chip { font-size: 30px; font-weight: 700; padding: 6px 18px 8px; border: 3px solid; }
.sub { font-size: 21px; color: #d8d8d8; }
.gauge { display: grid; gap: 8px; margin-top: 6px; }
.gbar { position: relative; display: grid; grid-template-columns: 25fr 20fr 10fr 20fr 25fr; gap: 4px; height: 16px; }
.gbar i { display: block; }
.gpin { position: absolute; top: -9px; bottom: -9px; width: 7px; background: #fff; transform: translateX(-3.5px); box-shadow: 0 0 0 3px rgba(0,0,0,.7); }
.glab { display: flex; justify-content: space-between; font-size: 16px; color: #a8a8a8; }
.grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 4px 0 6px; }
.cell { display: grid; gap: 0; padding: 8px 12px 7px; background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.14); }
.cn { font-size: 18px; color: #d8d8d8; font-weight: 600; }
.cv { font-family: "Archivo", sans-serif; font-size: 40px; font-weight: 900; line-height: 1; font-variant-numeric: tabular-nums; }
.cb { font-size: 14px; color: #a8a8a8; }
.lead { font-size: 30px; font-weight: 700; line-height: 1.38; letter-spacing: -.01em; }
.lead.small { font-size: 21px; font-weight: 500; color: #cfcfcf; line-height: 1.5; }
.stats { display: flex; gap: 34px; }
.stats div { display: grid; }
.stats b { font-family: "Archivo", sans-serif; font-size: 62px; font-weight: 900; line-height: 1; }
.stats span { font-size: 18px; color: #bdbdbd; margin-top: 4px; }
.foot { position: absolute; left: 60px; right: 60px; bottom: 40px; display: flex; align-items: center; gap: 14px; font-size: 17px; color: #c8c8c8; }
.tag { background: #fff; color: #1d1d1d; font-weight: 700; padding: 5px 13px; }
.site { margin-left: auto; font-size: 22px; font-weight: 700; color: #fff; letter-spacing: .01em; }
.map { display: block; filter: drop-shadow(0 10px 24px rgba(0,0,0,.55)); }
.map .sh path { stroke: #141414; stroke-width: 1.2px; vector-effect: non-scaling-stroke; stroke-linejoin: round; }
.map .sh path.live { stroke: rgba(255,255,255,.9); stroke-width: 1.6px; }
.map .sh path.off { stroke: rgba(255,255,255,.22); }
.map .ol { fill: none; stroke: rgba(255,255,255,.85); stroke-width: 2.2px; vector-effect: non-scaling-stroke; stroke-linejoin: round; }
.panel { width: 480px; padding: 26px 28px 22px; background: rgba(20,20,20,.78); border: 1px solid rgba(255,255,255,.16); display: grid; gap: 14px; margin-top: -40px; }
.pt { font-size: 19px; color: #cfcfcf; font-weight: 600; }
.pbig { font-size: 52px; font-weight: 900; display: flex; align-items: baseline; justify-content: space-between; }
.pbig span { font-family: "Archivo", sans-serif; font-size: 30px; font-weight: 700; color: #d8d8d8; }
.pnote { font-size: 17px; color: #bdbdbd; line-height: 1.5; }
.pex { font-size: 14px; color: #8a8a8a; text-align: right; }
.chart { display: block; overflow: visible; }
.axis { display: flex; justify-content: space-between; font-size: 16px; color: #a8a8a8; }
.code { width: 480px; margin-top: -40px; padding: 24px 28px; overflow: hidden; background: rgba(10,10,10,.85); border: 1px solid rgba(255,255,255,.16); font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 18px; line-height: 1.55; color: #e6e6e6; white-space: pre; }
.code .c { color: #111; background: #fff; padding: 1px 7px; font-weight: 700; }
.ring { position: absolute; width: 150px; height: 150px; border-radius: 50%; border: 3px solid rgba(255,255,255,.35); right: -40px; top: -40px; }
"""

HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@100..125,400..900&family=Noto+Sans+KR:wght@400;500;600;700;800;900&family=Poiret+One&family=JetBrains+Mono:wght@400;700&display=block">
<style>__CSS__</style></head><body><div class="card"><div class="bg"></div><div class="shade"></div><i class="ring"></i>
<div class="in">
  <div class="l">
    <div class="logo"><span class="en">KOREA FEAR &amp; GREED</span><span class="ko">아파트 공포탐욕지도</span></div>
    <div class="h"><span class="a">__A__</span><span class="b">__B__</span></div>
    <div class="body">__LEFT__</div>
  </div>
  <div class="r">__RIGHT__</div>
</div>
<div class="foot"><span class="tag">매달 20일 갱신</span><span>__SRC__</span><span class="site">__SITE__</span></div>
</div></body></html>"""


def page(name):
    if name == "home":
        return home_page()
    if name == "seoul" or name in REGIONS:
        return map_page(name)
    return tool_page(name)


def main(only=None):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "map.jpg").unlink(missing_ok=True)  # 예전 이름 (첫 화면이 서울 지도이던 때) → home·seoul
    with tempfile.TemporaryDirectory() as tmp:
        for name in PAGES:
            if only and name not in only:
                continue
            a, b, left, right = page(name)
            img, y = PHOTO[name]
            src = "국토교통부 실거래가 · 공공데이터" if name in TRADE_ONLY else "KB부동산 · 국토교통부 실거래가 · 공공데이터"
            doc = (HTML.replace("__CSS__", CSS.replace("__IMG__", (ROOT / "assets" / "img" / f"{img}.jpg").as_uri()).replace("__Y__", y))
                   .replace("__A__", a).replace("__B__", b).replace("__LEFT__", left).replace("__RIGHT__", right)
                   .replace("__SRC__", src).replace("__SITE__", SITE))
            html = Path(tmp) / f"{name}.html"
            html.write_text(doc)
            png = Path(tmp) / f"{name}.png"
            subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                            "--virtual-time-budget=10000", "--allow-file-access-from-files", "--window-size=1200,630",
                            f"--screenshot={png}", html.as_uri()], check=True, capture_output=True, timeout=120)
            im = Image.open(png).convert("RGB").crop((0, 0, 1200, 630))
            im.save(OUT / f"{name}.jpg", "JPEG", quality=86, optimize=True, progressive=True)
            print(name, (OUT / f"{name}.jpg").stat().st_size // 1000, "KB")


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
