"""GitHub Pages용 정적 사이트: site/index.html (첫 화면: 대한민국 지도), site/seoul/ (서울 지도), site/{지역id}/ (공개한
수도권·광역시 지도, 서울과 같은 템플릿), site/report/ (보고서), site/apt/·highs/·sim/ (단지 검색·신고가·모의 투자:
주소 뒤 ?r=지역id로 지역을 고르고, 자료는 data/ 아래 지역별), site/api/ (데이터 API 안내 페이지 + api_build.py가 만드는 JSON·CSV),
site/use/ (데이터 사용하기), site/news/ (주간 소식: news_build.py가 쌓은 호를 news/template.html에 넣음).
바닥글 스크립트가 페이지를 열 때마다 방문을 세고(register/worker.js의 /visit) 누적 방문자 수를 바닥글에 보여 준다.
site/status.json에는 이 사이트가 담은 자료의 날짜(지수 달·주간 소식 호·실거래 주간 갱신·만든 때)를 남긴다: 주간 갱신이 배포를 확인하고,
Worker의 매일 감시가 오래 안 바뀐 자료를 메일로 알린다.

아티팩트용 HTML에는 문서 머리말이 없어서, 문자 인코딩·뷰포트·doctype을 감싸 정식 문서로 만든다.
페이지마다 공통 겉모습(assets/skin.css: 레퍼런스 'Legacy Homes' 스타일)과 머리글·첫 화면 사진 띠(어둡게 깐 배경)·바닥글을 입힌다.
사진은 위키미디어 공용의 CC0 사진 (출처: assets/img/credits.json).
"""
import datetime as dt
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import quote

import api_build
import home_build
import news_build
from map.build import render as map_render
from regions import REGIONS, josa

ROOT = Path(__file__).parent
SITE = ROOT / "site"
HEAD = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="{desc}">
{title}
{og}<style>[hidden]{{display:none!important}} body{{margin:0}}</style>
</head>
<body{body_attr}>
"""
TAIL = "\n</body>\n</html>\n"
FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@100..125,400..900'
         '&family=Noto+Sans+KR:wght@400;500;600;700;900&family=Poiret+One&family=Work+Sans:wght@400;500;600;700&display=swap">')
REPO = "https://github.com/won-topiaa/korean-realestate-fear-and-greed-index"
SITE_URL = "https://aptfeargreed.com/"  # 2026-10-23부터 (옛 github.io 주소는 GitHub이 이 주소로 넘겨 줌)
# 링크 미리보기 (카카오톡·문자·SNS): 사이트 폴더 → (미리보기 그림 assets/og/*.jpg, 제목). 그림은 og_build.py로 만든다
SITE_NAME = "아파트 공포탐욕지도"
OG = {"": ("home", "아파트 공포탐욕지도 · 서울·수도권·광역시"), "seoul/": ("seoul", "서울 아파트 공포탐욕지도"),
      "apt/": ("apt", "단지 검색 · 아파트 공포탐욕지도"),
      "highs/": ("highs", "신고가 단지 · 아파트 공포탐욕지도"), "sim/": ("sim", "모의 투자 · 아파트 공포탐욕지도"),
      "report/": ("report", "백테스트 보고서 · 서울 아파트 공포탐욕지도"), "api/": ("api", "데이터 API · 아파트 공포탐욕지도"),
      "use/": ("use", "데이터 사용하기 · 아파트 공포탐욕지도"), "news/": ("news", "주간 소식 · 아파트 공포탐욕지도")}


def og_meta(dst, desc):
    rel = str(dst.parent.relative_to(SITE)).replace(".", "")
    page = (rel + "/") if rel else ""
    if page not in OG:
        return ""
    img, title = OG[page]
    url, pic = SITE_URL + page, f"{SITE_URL}assets/og/{img}.jpg{ver(f'assets/og/{img}.jpg')}"
    tags = [("property", "og:type", "website"), ("property", "og:site_name", SITE_NAME), ("property", "og:locale", "ko_KR"),
            ("property", "og:url", url), ("property", "og:title", title), ("property", "og:description", desc),
            ("property", "og:image", pic), ("property", "og:image:width", "1200"), ("property", "og:image:height", "630"),
            ("property", "og:image:alt", title), ("name", "twitter:card", "summary_large_image"), ("name", "twitter:title", title),
            ("name", "twitter:description", desc), ("name", "twitter:image", pic)]
    return "".join(f'<meta {k}="{n}" content="{v}">\n' for k, n, v in tags) + f'<link rel="canonical" href="{url}">\n'


def ver(rel):
    """정적 파일 주소에 붙이는 내용 지문 (같은 이름으로 바꿔도 브라우저가 옛 파일을 쓰지 않게)."""
    return "?v=" + hashlib.md5((ROOT / rel).read_bytes()).hexdigest()[:8]


PAGES = [("", "지도"), ("apt/", "단지 검색"), ("highs/", "신고가 단지"), ("sim/", "모의 투자"), ("news/", "주간 소식"), ("use/", "데이터 사용하기"), ("report/", "보고서")]
CONTACT = "wontopiaaa@gmail.com"
MAILTO = f"mailto:{CONTACT}?subject=" + quote(f"[{SITE_NAME}] 문의")


TOOLS = ("apt/", "highs/", "sim/")  # 지역을 고를 수 있는 화면 (주소 뒤 ?r=지역id)


def nav(base, cur, rq="", narrow=False):
    """rq: 지역 페이지에서 도구 링크에 붙일 지역 (예: ?r=busan). narrow: 본문 폭이 좁은 페이지 (화면 밝기를 버튼 하나로, 머리글을 한 줄로)."""
    q = lambda h: h + (rq if h in TOOLS else "")
    short = lambda n: n.replace(" 사용하기", '<span class="sk-long"> 사용하기</span>').replace("주간 ", '<span class="sk-long">주간 </span>').replace("신고가 단지", '신고가<span class="sk-long"> 단지</span>')  # 휴대폰에서는 '데이터'·'소식'·'신고가'
    links = "".join(f'<a href="{base}{q(h)}" aria-label="{n}"' + (' aria-current="page"' if n == cur else "") + f">{short(n)}</a>"
                    for h, n in PAGES if n != "보고서")  # 보고서·문의는 바닥글에만
    cta = ("", "지도 보기") if cur == "단지 검색" else ("apt/", "단지 검색")
    return (f'<header class="sk-nav{" sk-narrow" if narrow else ""}"><div class="sk-in"><a class="sk-logo" href="{base}" aria-label="{SITE_NAME} 처음으로">'
            f'<span>KOREA FEAR &amp; GREED</span><span class="ko">{SITE_NAME}</span></a><nav class="sk-menu" aria-label="사이트 메뉴">{links}</nav>'
            f'<div class="sk-right" id="sk-right"><button type="button" class="sk-theme-m" id="sk-theme-m">화면: 자동</button>'
            f'<a class="sk-cta" href="{base}{q(cta[0])}">{cta[1]}</a></div></div></header>\n')


def hero_bg(base, name, y):
    """첫 화면 띠의 배경 사진 (어둡게 깔림) + 레퍼런스의 원 장식 두 개. 주소는 문서 기준이 되도록 인라인 배경으로."""
    url = f"{base}assets/img/{name}.jpg{ver(f'assets/img/{name}.jpg')}"
    return (f'<div class="sk-bg" aria-hidden="true" style="background-image:url(\'{url}\');background-position:center {y}"></div>'
            '<i class="sk-dot a" aria-hidden="true"></i><i class="sk-dot b" aria-hidden="true"></i>\n')


def footer(base, rq=""):
    cr = json.loads((ROOT / "assets" / "img" / "credits.json").read_text())
    seen, who = set(), []
    for v in cr.values():  # 같은 촬영자는 한 번만
        if v["artist"] not in seen:
            seen.add(v["artist"])
            who.append(f'<a href="{v["page"]}">{v["artist"]}</a>')
    who = ", ".join(who)
    links = "".join(f'<li><a href="{base}{h}{rq if h in TOOLS else ""}">{n}</a></li>' for h, n in
                    [("", "전국 지도"), ("seoul/", "서울 지도"), ("apt/", "단지 검색"), ("highs/", "신고가 단지"), ("sim/", "모의 투자"), ("news/", "주간 소식"),
                     ("report/", "백테스트 보고서"), ("use/", "데이터 사용하기"), ("api/", "데이터 API")])
    return (f'\n<footer class="sk-foot"><div class="sk-foot-bg" aria-hidden="true" style="background-image:url(\'{base}assets/img/footer.jpg{ver("assets/img/footer.jpg")}\')"></div><div class="sk-in">'
            f'<div class="sk-about"><a class="sk-logo" href="{base}">KOREA FEAR &amp; GREED</a>'
            '<p>아파트 시장의 공포와 탐욕을 0~100으로 보여주는 지수예요. 서울에서 시작해 수도권·광역시로 넓히고 있어요. 지수는 매달 20일, '
            '실거래·신고가와 주간 소식은 매주 월요일에 갱신해요.</p></div>'
            f'<div><h4>둘러보기</h4><ul>{links}<li><a href="{REPO}">소스 코드 (GitHub)</a></li></ul></div>'
            '<div><h4>자료</h4><ul><li>가공 자료(지수·점수): 원토피아</li><li>원자료: KB부동산 · 국토교통부 실거래가 · 건축물대장</li>'
            '<li>한국부동산원 · 청약홈 · 한국은행 · 네이버 금융 · 구글 트렌드</li><li>자세한 출처는 각 페이지 설명에 있어요</li></ul></div>'
            f'<div class="sk-contact"><h4>문의</h4><p>지수나 데이터 오류, 제안, 제휴 문의는 메일로 보내 주세요.</p>'
            f'<a class="sk-mail" href="{MAILTO}">{CONTACT}</a><a class="sk-mailbtn" href="{MAILTO}">메일 보내기 →</a></div>'
            f'<p class="sk-copy">사진: 위키미디어 공용 CC0·퍼블릭 도메인 (저작권 없음) — {who}</p>'
            '<p class="sk-copy sk-visits">누적 방문자 <b id="sk-visits">–</b>명 <span>(2026년 10월 25일부터)</span></p></div></footer>\n')


# 방문 세기: 이 브라우저의 무작위 번호(처음 오면 만듦)와 페이지 주소만 보낸다 → 누적 방문자 수를 받아 바닥글에.
# 자동으로 여는 브라우저(검색 로봇·시험)와 '?nocount=1'로 연 브라우저(사이트 주인, '?nocount=0'으로 되돌림)는 세지 않고 수만 받는다.
# 본문은 text/plain이라 미리 묻는 요청(CORS preflight) 없이 한 번에 간다
VISIT_URL = "https://register.aptfeargreed.com/visit"
VISIT_JS = ('<script>(() => { const el = document.getElementById("sk-visits"); let v = null, n = navigator.webdriver ? 1 : 0;'
            ' try { const s = location.search; if (/[?&]nocount=1\\b/.test(s)) localStorage.setItem("fgi-nocount", "1"); if (/[?&]nocount=0\\b/.test(s)) localStorage.removeItem("fgi-nocount");'
            ' if (localStorage.getItem("fgi-nocount")) n = 1; v = localStorage.getItem("fgi-vid");'
            ' if (!/^[0-9a-f]{32}$/.test(v || "")) { v = [...crypto.getRandomValues(new Uint8Array(16))].map((x) => x.toString(16).padStart(2, "0")).join(""); localStorage.setItem("fgi-vid", v); } } catch (e) { v = null; }'
            f' fetch("{VISIT_URL}", {{ method: "POST", body: JSON.stringify({{ v, p: location.pathname, n }}), keepalive: true }})'
            ' .then((r) => r.json()).then((j) => { if (el && j.total) el.textContent = j.total.toLocaleString("ko-KR"); }).catch(() => {}); })();</script>\n')


def skin(html, base, cur, hero, h1, photo_args, maxw, intro=None, rq=""):
    """페이지 html에 공통 겉모습을 입힌다. hero=(여는 태그, 닫는 태그): 첫 화면 묶음, h1=(원래, 바꿀 것).
    rq: 머리글·바닥글의 단지 검색·신고가·모의 투자 링크에 붙일 지역 (지역 지도 페이지에서 그 지역으로 열리게)."""
    css = f'{FONTS}\n<link rel="stylesheet" href="{base}assets/skin.css{ver("assets/skin.css")}">\n<style>:root{{--sk-max:{maxw}px}}</style>\n'
    i = html.index("</style>") + len("</style>")  # 페이지 스타일 바로 뒤 (덮어쓰기)
    html = html[:i] + "\n" + css + html[i:]
    j = html.index('<div class="wrap">')
    pagebg = ""
    if intro:  # 검색 전에는 사진 한 장을 화면 전체 배경으로 (결과가 나오면 위 띠·아래 바닥글 사진으로)
        name = photo_args[0]
        pagebg = (f'<div class="sk-pagebg" aria-hidden="true" style="background-image:url(\'{base}assets/img/{name}.jpg'
                  f'{ver(f"assets/img/{name}.jpg")}\')"></div>\n')
    html = html[:j] + pagebg + nav(base, cur, rq, narrow=maxw < 1100) + html[j:]
    op, cl = hero
    assert html.count(op) == 1, op
    a = html.index(op)
    b = html.index(cl, a)
    new_op = op.replace(">", ' class="sk-hero">', 1) if "class=" not in op else op.replace('class="', 'class="sk-hero ', 1)
    block = html[a:b].replace(op, new_op + hero_bg(base, *photo_args), 1)
    assert block.count(h1[0]) == 1, h1[0]
    block = block.replace(h1[0], h1[1])
    html = html[:a] + block + html[b:]
    # 화면 밝기 버튼을 머리글로 옮긴다 (기능은 그대로)
    # 화면 밝기 버튼을 머리글로 옮기고, 휴대폰용 버튼 하나(누를 때마다 자동→밝게→어둡게)를 같은 설정에 잇는다
    tail = ('<script>(() => { const t = document.getElementById("theme-ctl"), r = document.getElementById("sk-right"), m = document.getElementById("sk-theme-m");'
            ' if (!t || !r) return; r.prepend(t); const lab = t.querySelector(".tl"); if (lab) lab.textContent = "화면 밝기";'
            ' const N = { auto: "자동", light: "밝게", dark: "어둡게" }, ORDER = ["auto", "light", "dark"];'
            ' const cur = () => (t.querySelector("button[aria-pressed=true]") || {}).dataset?.m || "auto";'
            ' const sync = () => { m.textContent = "화면: " + N[cur()]; m.setAttribute("aria-label", "화면 밝기 바꾸기, 지금 " + N[cur()]); };'
            ' m.addEventListener("click", () => { const b = t.querySelector(`button[data-m="${ORDER[(ORDER.indexOf(cur()) + 1) % 3]}"]`); if (b) b.click(); sync(); });'
            ' t.addEventListener("click", () => setTimeout(sync)); sync(); })();</script>\n')
    tail += ('<script>document.querySelectorAll(".m-fold[data-fold]").forEach((el) => { const b = document.createElement("button");'
             ' b.type = "button"; b.className = "m-fold-btn"; const lab = el.dataset.fold; b.textContent = lab + " ▾";'
             ' b.addEventListener("click", () => { const o = el.classList.toggle("m-open"); b.textContent = lab + (o ? " ▴" : " ▾");'
             ' if (o && typeof drawAll === "function") drawAll(); });'  # 접혀 있던 칸의 그래프는 펼칠 때 다시 그린다 (보고서)
             ' el.before(b); });</script>\n')  # 휴대폰에서 접어 둔 칸 펼치기
    tail += VISIT_JS
    if intro:  # 결과 칸이 보이면 첫 화면 모드를 끈다
        tail += ('<script>(() => { const el = document.querySelector(' + json.dumps(intro) + '); if (!el) return;'
                 ' const f = () => document.body.classList.toggle("sk-intro", el.hidden); f();'
                 ' new MutationObserver(f).observe(el, { attributes: true, attributeFilter: ["hidden"] }); })();</script>\n')
    return html + footer(base, rq) + tail


def wrap(src, dst, desc, inject=None, skin_args=None, intro=None, rq=""):
    html = src.read_text()
    m = re.search(r"<title>.*?</title>", html)
    title = m.group(0) if m else ""
    html = html.replace(title, "", 1) if title else html  # 제목은 head로 (링크 미리보기용)
    for a, b in inject or []:
        assert html.count(a) == 1, a
        html = html.replace(a, b)
    if skin_args:
        html = skin(html, *skin_args, intro=intro, rq=rq)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(HEAD.format(desc=desc, title=title, og=og_meta(dst, desc), body_attr=' class="sk-intro"' if intro else "") + html + TAIL)


TOOL_FILES = {"apt": lambda r: f"results_apt/{'' if r == 'seoul' else r + '/'}index.json",
              "highs": lambda r: "results_highs/" + ("highs.json" if r == "seoul" else f"{r}.json"),
              "sim": lambda r: f"results_sim/{'' if r == 'seoul' else r + '/'}meta.json"}


def tool_ready(page, rid):
    need = [TOOL_FILES[page](rid)] + ([TOOL_FILES["apt"](rid)] if page == "sim" else [])  # 모의 투자는 단지 목록을 단지 검색 자료에서 읽는다
    return all((ROOT / f).exists() for f in need)


def tool_src(page, h1):
    """도구 화면의 원본. 서울 자료를 이번 실행에서 못 만들었으면(월간 갱신에서 그 계산만 실패) '잠시 쉬어요' 안내 페이지로
    (그냥 두면 '잠시 뒤 새로고침'이라는 안내만 뜨는데, 자료는 다음 갱신 때까지 안 생김)."""
    src = ROOT / page / "template.html"
    if tool_ready(page, "seoul"):
        return src, True
    print(f"알림: 서울 {page} 자료가 없어 안내 페이지로 배포")
    title = re.search(r"<title>.*?</title>", src.read_text()).group(0)
    tmp = ROOT / "logs" / f"maint_{page}.html"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(f'{title}<style>.wrap{{max-width:960px;margin:0 auto;padding:24px 16px}}</style>\n<div class="wrap">'
                   f'<header style="display:grid;gap:6px"><h1>{h1}</h1><p>이번 달 갱신에서 이 화면의 자료를 만들지 못해 잠시 쉬어요. '
                   '다음 갱신 때 다시 열어요. 지도와 지수는 정상이에요.</p></header></div>\n')
    return tmp, False


def tool_regions(page):
    """도구 화면의 지역 목록: 서울 + 수도권·광역시 (자료를 만든 곳만 ready). pre: 그 지역 단지 번호 앞 5자리 (지역 없이 #단지번호만 있는 예전 링크용)."""
    out = []
    for rid in ["seoul", *REGIONS]:
        idx = ROOT / TOOL_FILES["apt"](rid)
        pre = sorted({it[0][:5] for it in json.loads(idx.read_text())["items"]}) if idx.exists() else []
        out.append({"id": rid, "name": "서울" if rid == "seoul" else REGIONS[rid]["name"], "ready": tool_ready(page, rid), "pre": pre})
    return out


# 단지 검색·신고가·모의 투자: 주소의 ?r=지역id → 없으면 #단지번호 앞자리 → 지난번 고른 지역 → 서울. 화면 맨 위 지역 버튼도 여기서 그린다.
PICK = r"""<script>
(() => {
  const L = __LIST__, ok = (id) => L.some((x) => x.id === id && x.ready);
  const q = new URLSearchParams(location.search).get("r");
  let id = ok(q) ? q : null;
  if (!id) {  // 예전 링크 (지역 없이 #단지번호): 단지 번호 앞자리로 지역을 찾는다
    const h = decodeURIComponent(location.hash.slice(1)).split(/[:,]/)[0].slice(0, 5);
    const hit = h && L.find((x) => x.ready && x.pre.includes(h));
    if (hit) id = hit.id;
  }
  if (!id) { try { const s = localStorage.getItem("fgi-region"); if (ok(s)) id = s; } catch (e) {} }
  id = id || "seoul";
  try { localStorage.setItem("fgi-region", id); } catch (e) {}
  const rg = L.find((x) => x.id === id);
  window.RG = { id, name: rg.name, q: "?r=" + id, data: id === "seoul" ? "data/" : "data/" + id + "/" };
  document.title = document.title + " · " + rg.name;
  const nav = document.getElementById("rg");
  if (nav) {
    nav.textContent = "";
    const lab = document.createElement("span"); lab.textContent = "지역"; nav.appendChild(lab);
    L.forEach((x) => {
      const a = document.createElement(x.ready ? "a" : "span");
      a.textContent = x.name;
      if (x.ready) { a.href = "?r=" + x.id; if (x.id === id) a.setAttribute("aria-current", "page"); }
      else { a.className = "off"; a.title = "실거래 자료를 받는 중이에요"; }
      nav.appendChild(a);
    });
  }
  document.querySelectorAll(".sk-menu a, .sk-cta").forEach((a) => {  // 머리글의 다른 도구도 같은 지역으로
    const h = a.getAttribute("href");
    if (/(apt|highs|sim)\/$/.test(h)) a.setAttribute("href", h + window.RG.q);
  });
})();
</script>
"""
MAIN_JS = "<script>\nconst $ = (s) => document.querySelector(s);"


def pick(page):
    """도구 템플릿 본 스크립트 앞에 지역 고르기를 넣는 치환 (wrap의 inject)."""
    return [(MAIN_JS, PICK.replace("__LIST__", json.dumps(tool_regions(page), ensure_ascii=False, separators=(",", ":"))) + MAIN_JS)]


def tool_links(rid, name):
    """지도 페이지에 넣을 단지 검색·신고가·모의 투자 링크 (그 지역 자료가 있는 것만)."""
    have = [(p, n) for p, n in (("apt", "단지 검색"), ("highs", "신고가 단지"), ("sim", "모의 투자")) if tool_ready(p, rid)]
    foot = " · ".join(f'<a href="../{p}/?r={rid}" style="color:var(--ink)">{name} {n} →</a>' for p, n in have)
    btn = (f'<a class="btn" href="../apt/?r={rid}" style="text-decoration:none;display:inline-block">{name} 단지 검색 · 최근 실거래가 위치 보기 →</a>'
           if tool_ready("apt", rid) else "")
    return foot, btn


def region_fill(d):
    """서울 밖 지역 페이지에 들어갈 글 (지도 템플릿의 빈칸)."""
    nm, sw, n = d["top"], d["sub_word"], len(d["gu_order"])
    return {"__TITLE__": f"{nm} 아파트 공포탐욕지도", "__TOP__": nm, "__NIND__": str(d["n_ind"]),
            "__HOWTO__": f"{sw}{josa(sw)} 누르면 그곳의 지수를, 아무 데도 누르지 않으면 {nm} 전체 지수를 보여줘요. 아래 슬라이더로 2006년부터 달마다 볼 수 있어요.",
            "__FOOT_ACC__": (f'<p><b style="color:var(--ink-2)">정확도</b> · {nm} 지수와 {n}개 {sw} 지수는 그곳 실거래 가격으로 따로 검증했어요(지수 추이 아래 참고). '
                             f'{sw} 지수는 {d["n_votes"]}표 중 일부만 그 {sw} 값이라 {nm} 지수와 크게 다르지 않고, 5점 미만 차이는 의미 있는 차이로 보기 어려워요. '
                             f'거래가 적은 {sw}일수록 점수가 더 흔들려요.</p>'),
            "__MAP_SRC__": "지도는 국토교통부 브이월드(VWorld) 시군구 경계(2026년 10월)예요."}


def status(month):
    """site/status.json: 배포된 자료의 날짜 (weekly-update.yml 배포 확인, register/worker.js 매일 감시)."""
    issues = sorted(news_build.DIR.glob("*.json"))
    news = json.loads(issues[-1].read_text()) if issues else {}
    trades = (json.loads((ROOT / "data" / "weekly_state.json").read_text()) if (ROOT / "data" / "weekly_state.json").exists() else {}).get("trades") or {}
    out = {"built": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="minutes"), "commit": os.environ.get("GITHUB_SHA", "")[:7],
           "index_month": month, "news_issue": news.get("issue"), "news_to": news.get("to"),
           "trades_week": trades.get("week"), "trades_result": trades.get("result"), "trades_at": trades.get("at")}
    (SITE / "status.json").write_text(json.dumps(out, ensure_ascii=False) + "\n")
    print("status:", out)


if __name__ == "__main__":
    shutil.rmtree(SITE / "assets", ignore_errors=True)
    shutil.copytree(ROOT / "assets", SITE / "assets", ignore=shutil.ignore_patterns("credits.json"))
    wrap(ROOT / "home" / "index.html", SITE / "index.html",
         "서울과 수도권·광역시 아파트 시장의 공포와 탐욕을 0~100으로. 지도에서 지역을 누르면 구·시군별 지수와 2006년부터의 추이, 매달 20일 갱신.",
         skin_args=("", "지도", ('<header style="display:grid;gap:6px">', "</header>"),
                    ("<h1>아파트 공포탐욕지도</h1>", '<h1><span class="sk-h1a">지역별 아파트</span><span class="sk-h1b">공포탐욕지도</span></h1>'),
                    ("bg-map", "50%"), 1180))
    FOOT, HERO = '<footer class="foot m-fold" data-fold="계산 방법·출처 보기">', '<p class="hero-now" id="hero-now" aria-live="polite"></p>'

    def map_links(rid, name, report=False):
        foot, btn = tool_links(rid, name)
        foot += ' · <a href="../report/" style="color:var(--ink)">백테스트 보고서 보기 →</a>' if report else ""
        out = [(FOOT, FOOT + f"\n    <p>{foot}</p>")] if foot else []
        return out + ([(HERO, HERO + f'\n    <p class="m-hide" style="margin:2px 0 4px">{btn}</p>')] if btn else [])
    wrap(ROOT / "map" / "index.html", SITE / "seoul" / "index.html",
         "서울 아파트 시장의 공포와 탐욕을 0~100으로. 5대 권역·25개 구 지도와 2006년부터의 추이, 매달 20일 갱신.",
         inject=map_links("seoul", "서울", report=True),
         skin_args=("../", "지도", ('<header style="display:grid;gap:6px">', "</header>"),
                    ("<h1>서울 아파트 공포탐욕지도</h1>", '<h1><span class="sk-h1a">서울 아파트</span><span class="sk-h1b">공포탐욕지도</span></h1>'),
                    ("bg-map", "50%"), 1180), rq="?r=seoul")
    for rid in home_build.published():  # 공개 기준을 넘은 수도권·광역시 (같은 지도 템플릿)
        d = json.loads((ROOT / "results_region" / f"{rid}.json").read_text())
        nm, sw, n = d["top"], d["sub_word"], len(d["gu_order"])
        OG[f"{rid}/"] = (rid if (ROOT / "assets" / "og" / f"{rid}.jpg").exists() else "home", f"{nm} 아파트 공포탐욕지도")
        src = ROOT / "results_region" / f"page_{rid}.html"
        src.write_text(map_render(region_fill(d), json.dumps(d, ensure_ascii=False, separators=(",", ":"))))
        wrap(src, SITE / rid / "index.html",
             f"{nm} 아파트 시장의 공포와 탐욕을 0~100으로. {n}개 {sw} 지도와 2006년부터의 추이, 매달 20일 갱신.",
             inject=map_links(rid, nm), rq=f"?r={rid}",
             skin_args=("../", "지도", ('<header style="display:grid;gap:6px">', "</header>"),
                        (f"<h1>{nm} 아파트 공포탐욕지도</h1>", f'<h1><span class="sk-h1a">{nm} 아파트</span><span class="sk-h1b">공포탐욕지도</span></h1>'),
                        (f"bg-{rid}" if (ROOT / "assets" / "img" / f"bg-{rid}.jpg").exists() else "bg-map", "50%"), 1180))  # 지역 사진이 없으면 서울 사진
    src, ok = tool_src("apt", "단지 검색")
    wrap(src, SITE / "apt" / "index.html",
         "우리 단지 최근 실거래가가 비싼 편인지 싼 편인지 0~100점으로. 서울·수도권·광역시, 세대수·용적률 같은 단지 정보도 함께.",
         inject=pick("apt") if ok else None, skin_args=("../", "단지 검색", ('<header style="display:grid;gap:6px">', "</header>"),
                    ("<h1>단지 검색</h1>", '<h1><span class="sk-h1a">최근 실거래가, 비싼 편일까?</span><span class="sk-h1b">단지 검색</span></h1>'),
                    ("bg-apt", "40%"), 960), intro="#detail")
    for res, page, script in [("results_apt", "apt", "apt_score.py"), ("results_highs", "highs", "highs_build.py"), ("results_sim", "sim", "sim_build.py")]:
        data = ROOT / res
        if data.exists() and any(data.iterdir()):
            shutil.rmtree(SITE / page / "data", ignore_errors=True)
            shutil.copytree(data, SITE / page / "data")
        else:
            print(f"알림: {res}가 없어 {page} 자료 없이 빌드 (python {script} 먼저)")
    src, ok = tool_src("highs", "신고가 단지")
    wrap(src, SITE / "highs" / "index.html",
         "이번 달 아파트 신고가 단지 (서울·수도권·광역시). 같은 단지·같은 평형의 지난 모든 거래보다 비싸게 팔린 거래를 구·시군별로.",
         inject=pick("highs") if ok else None, skin_args=("../", "신고가 단지", ('<header style="display:grid;gap:6px">', "</header>"),
                    ("<h1>신고가 단지</h1>", '<h1><span class="sk-h1a">이번 달 가장 비싸게 팔린 집</span><span class="sk-h1b">신고가 단지</span></h1>'),
                    ("bg-highs", "45%"), 1040))
    src, ok = tool_src("sim", "모의 투자")
    wrap(src, SITE / "sim" / "index.html",
         "그때 이 단지를 샀다면 지금 얼마일까? 서울·수도권·광역시 실거래로 계산하는 가상 투자. 단지 2~3개를 같은 기간으로 비교.",
         inject=pick("sim") if ok else None, skin_args=("../", "모의 투자", ('<header style="display:grid;gap:6px">', "</header>"),
                    ("<h1>모의 투자</h1>", '<h1><span class="sk-h1a">그때 샀다면 지금 얼마?</span><span class="sk-h1b">모의 투자</span></h1>'),
                    ("bg-sim", "38%"), 960), intro="#res-panel")
    wrap(ROOT / "report" / "index.html", SITE / "report" / "index.html",
         "서울 아파트 공포탐욕지수를 실거래 141만 건으로 검증한 보고서. 정확도와 한계까지.",
         skin_args=("../", "보고서", ('<section class="top">', "</section>"),
                    ("<h1>서울 공포탐욕지수 백테스트</h1>", '<h1><span class="sk-h1a">서울 공포탐욕지수</span><span class="sk-h1b">백테스트</span></h1>'),
                    ("bg-report", "50%"), 1040))
    shutil.rmtree(SITE / "api", ignore_errors=True)
    month, n = api_build.build(SITE / "api" / "v1")
    wrap(ROOT / "api" / "template.html", SITE / "api" / "index.html",
         "아파트 공포탐욕지수를 JSON·CSV로. 서울·25개 구와 공개한 수도권·광역시의 2006년부터 월별 점수, 키 없이 호출, 매달 20일 갱신.",
         skin_args=("../", "데이터 API", ('<header style="display:grid;gap:6px">', "</header>"),
                    ("<h1>데이터 API</h1>", '<h1><span class="sk-h1a">아파트 공포탐욕지수</span><span class="sk-h1b">데이터 API</span></h1>'),
                    ("bg-report", "50%"), 960))
    print(f"api: {month} · 지역 {n}곳")
    wrap(ROOT / "use" / "template.html", SITE / "use" / "index.html",
         "아파트 공포탐욕지수를 서비스·리서치에 쓰려면: 키 없이 무료, 1분 사용 신청, JSON·CSV, 매달 20일 갱신.",
         skin_args=("../", "데이터 사용하기", ('<header style="display:grid;gap:6px">', "</header>"),
                    ("<h1>데이터 사용하기</h1>", '<h1><span class="sk-h1a">아파트 공포탐욕지수</span><span class="sk-h1b">데이터 사용하기</span></h1>'),
                    ("bg-report", "40%"), 960))
    wrap(ROOT / "news" / "template.html", SITE / "news" / "index.html",
         "지난 한 주 부동산·금리 소식을 공포탐욕지수의 주제(자금·가격·거래·전세·공급)별로 모으고, 그 주제의 서울 지수 점수를 함께. 매주 월요일.",
         inject=[("<!--NEWS-->", news_build.render())],
         skin_args=("../", "주간 소식", ('<header style="display:grid;gap:6px">', "</header>"),
                    ("<h1>주간 소식</h1>", '<h1><span class="sk-h1a">지수와 엮은</span><span class="sk-h1b">주간 소식</span></h1>'),
                    ("bg-report", "45%"), 960))
    status(month)
    (SITE / ".nojekyll").write_text("")
    print("site:", [str(p.relative_to(ROOT)) for p in SITE.rglob("*.html")])
