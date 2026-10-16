"""GitHub Pages용 정적 사이트: site/index.html (지도), site/report/index.html (보고서), site/apt/ (단지 검색).

아티팩트용 HTML에는 문서 머리말이 없어서, 문자 인코딩·뷰포트·doctype을 감싸 정식 문서로 만든다.
세 페이지에 공통 겉모습(assets/skin.css: 레퍼런스 'Legacy Homes' 스타일)과 머리글·첫 화면 사진·바닥글을 입힌다.
사진은 위키미디어 공용의 CC0 사진 (출처: assets/img/credits.json).
"""
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).parent
SITE = ROOT / "site"
HEAD = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="{desc}">
{title}
<style>[hidden]{{display:none!important}} body{{margin:0}}</style>
</head>
<body>
"""
TAIL = "\n</body>\n</html>\n"
FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@100..125,400..900'
         '&family=Noto+Sans+KR:wght@400;500;600;700;900&family=Poiret+One&family=Work+Sans:wght@400;500;600;700&display=swap">')
REPO = "https://github.com/won-topiaa/korean-realestate-fear-and-greed-index"
PAGES = [("", "지도"), ("apt/", "단지 검색"), ("report/", "보고서")]


def nav(base, cur):
    links = "".join(f'<a href="{base}{h}"' + (' aria-current="page"' if n == cur else "") + f">{n}</a>" for h, n in PAGES)
    cta = ("", "지도 보기") if cur == "단지 검색" else ("apt/", "단지 검색")
    return (f'<header class="sk-nav"><div class="sk-in"><a class="sk-logo" href="{base}" aria-label="서울 아파트 공포탐욕지도 처음으로">'
            f'SEOUL FEAR &amp; GREED</a><nav class="sk-menu" aria-label="사이트 메뉴">{links}</nav>'
            f'<div class="sk-right" id="sk-right"><a class="sk-cta" href="{base}{cta[0]}">{cta[1]}</a></div></div></header>\n')


def photo(base, name, alt):
    return (f'<figure class="sk-photo"><img src="{base}assets/img/{name}.jpg" alt="{alt}" width="900" height="1200">'
            '<i class="sk-dot a" aria-hidden="true"></i><i class="sk-dot b" aria-hidden="true"></i></figure>\n')


def footer(base):
    cr = json.loads((ROOT / "assets" / "img" / "credits.json").read_text())
    who = ", ".join(f'<a href="{v["page"]}">{v["artist"]}</a>' for v in cr.values())
    links = "".join(f'<li><a href="{base}{h}">{n}</a></li>' for h, n in
                    [("", "공포탐욕 지도"), ("apt/", "단지 검색"), ("report/", "백테스트 보고서")])
    return (f'\n<footer class="sk-foot" style="--sk-foot-img:url(\'{base}assets/img/footer.jpg\')"><div class="sk-in">'
            f'<div class="sk-about"><a class="sk-logo" href="{base}">SEOUL FEAR &amp; GREED</a>'
            '<p>서울 아파트 시장의 공포와 탐욕을 0~100으로 보여주는 지수예요. 공공데이터로 매달 20일에 갱신해요. '
            '사고팔 시점을 알려주는 신호가 아니에요.</p></div>'
            f'<div><h4>둘러보기</h4><ul>{links}<li><a href="{REPO}">소스 코드 (GitHub)</a></li></ul></div>'
            '<div><h4>자료</h4><ul><li>국토교통부 실거래가 · 건축물대장</li><li>한국부동산원 · 청약홈 · 한국은행</li>'
            '<li>자세한 출처는 각 페이지 설명에 있어요</li></ul></div>'
            f'<p class="sk-copy">사진: 위키미디어 공용 CC0 (저작권 없음) — {who}</p></div></footer>\n')


def skin(html, base, cur, hero, h1, photo_args, maxw):
    """페이지 html에 공통 겉모습을 입힌다. hero=(여는 태그, 닫는 태그): 첫 화면 묶음, h1=(원래, 바꿀 것)."""
    css = f'{FONTS}\n<link rel="stylesheet" href="{base}assets/skin.css">\n<style>:root{{--sk-max:{maxw}px}}</style>\n'
    i = html.index("</style>") + len("</style>")  # 페이지 스타일 바로 뒤 (덮어쓰기)
    html = html[:i] + "\n" + css + html[i:]
    j = html.index('<div class="wrap">')
    html = html[:j] + nav(base, cur) + html[j:]
    op, cl = hero
    assert html.count(op) == 1, op
    a = html.index(op)
    b = html.index(cl, a)
    block = html[a:b].replace(op, op.replace(">", ' class="sk-hero">', 1) if "class=" not in op else op.replace('class="', 'class="sk-hero ', 1), 1)
    assert block.count(h1[0]) == 1, h1[0]
    block = block.replace(h1[0], h1[1]) + photo(base, *photo_args)
    html = html[:a] + block + html[b:]
    # 화면 밝기 버튼을 머리글로 옮긴다 (기능은 그대로)
    return html + footer(base) + ('<script>(() => { const t = document.getElementById("theme-ctl"), r = document.getElementById("sk-right");'
                                  ' if (t && r) r.prepend(t); })();</script>\n')


def wrap(src, dst, desc, inject=None, skin_args=None):
    html = src.read_text()
    m = re.search(r"<title>.*?</title>", html)
    title = m.group(0) if m else ""
    html = html.replace(title, "", 1) if title else html  # 제목은 head로 (링크 미리보기용)
    for a, b in inject or []:
        assert html.count(a) == 1, a
        html = html.replace(a, b)
    if skin_args:
        html = skin(html, *skin_args)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(HEAD.format(desc=desc, title=title) + html + TAIL)


if __name__ == "__main__":
    shutil.rmtree(SITE / "assets", ignore_errors=True)
    shutil.copytree(ROOT / "assets", SITE / "assets", ignore=shutil.ignore_patterns("credits.json"))
    wrap(ROOT / "map" / "index.html", SITE / "index.html",
         "서울 5대 권역별 아파트 공포탐욕지수 지도. 매달 자동 갱신.",
         inject=[('<footer class="foot">', '<footer class="foot">\n    <p><a href="apt/" style="color:var(--ink)">단지 검색 (최근 실거래 위치) →</a> · <a href="report/" style="color:var(--ink)">백테스트 보고서 보기 →</a></p>'),
                 ("<h1>서울 아파트 공포탐욕지도</h1>", '<h1>서울 아파트 공포탐욕지도</h1>\n    <p style="margin:6px 0 4px"><a class="btn" href="apt/" style="text-decoration:none;display:inline-block">단지 검색 · 최근 실거래가 위치 보기 →</a></p>')],
         skin_args=("", "지도", ('<header style="display:grid;gap:6px">', "</header>"),
                    ("<h1>서울 아파트 공포탐욕지도</h1>", '<h1><span class="sk-h1a">서울 아파트</span><span class="sk-h1b">공포탐욕지도</span></h1>'),
                    ("hero-map", "하늘을 배경으로 올려다본 서울 강남구 도곡동의 고층 아파트"), 1180))
    wrap(ROOT / "apt" / "template.html", SITE / "apt" / "index.html",
         "서울 아파트 단지별 최근 실거래가가 최근 거래 범위 중 어디쯤인지 0~100으로 (층·시장 변화 보정).",
         skin_args=("../", "단지 검색", ('<header style="display:grid;gap:6px">', "</header>"),
                    ("<h1>단지 검색</h1>", '<h1><span class="sk-h1a">최근 실거래가, 비싼 편일까?</span><span class="sk-h1b">단지 검색</span></h1>'),
                    ("hero-apt", "맑은 날 서울 도봉구의 고층 아파트 단지"), 960))
    data = ROOT / "results_apt"
    if (data / "index.json").exists():
        shutil.rmtree(SITE / "apt" / "data", ignore_errors=True)
        shutil.copytree(data, SITE / "apt" / "data")
    else:
        print("알림: results_apt가 없어 단지 검색 자료 없이 빌드 (python apt_score.py 먼저)")
    wrap(ROOT / "report" / "index.html", SITE / "report" / "index.html",
         "서울 아파트 공포탐욕지수 v3 백테스트 보고서.",
         skin_args=("../", "보고서", ('<section class="top">', "</section>"),
                    ("<h1>서울 공포탐욕지수 백테스트</h1>", '<h1><span class="sk-h1a">서울 공포탐욕지수</span><span class="sk-h1b">백테스트</span></h1>'),
                    ("hero-report", "밤의 한강 너머로 보이는 서울 송파구 롯데월드타워와 아파트"), 1040))
    (SITE / ".nojekyll").write_text("")
    print("site:", [str(p.relative_to(ROOT)) for p in SITE.rglob("*.html")])
