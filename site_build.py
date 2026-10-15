"""GitHub Pages용 정적 사이트: site/index.html (지도), site/report/index.html (보고서), site/apt/ (단지 검색).

아티팩트용 HTML에는 문서 머리말이 없어서, 문자 인코딩·뷰포트·doctype을 감싸 정식 문서로 만든다.
"""
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


def wrap(src, dst, desc, inject=None):
    html = src.read_text()
    import re
    m = re.search(r"<title>.*?</title>", html)
    title = m.group(0) if m else ""
    html = html.replace(title, "", 1) if title else html  # 제목은 head로 (링크 미리보기용)
    if inject:
        a, b = inject
        assert html.count(a) == 1, a
        html = html.replace(a, b)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(HEAD.format(desc=desc, title=title) + html + TAIL)


if __name__ == "__main__":
    wrap(ROOT / "map" / "index.html", SITE / "index.html",
         "서울 5대 권역별 아파트 공포탐욕지수 지도. 매달 자동 갱신.",
         inject=('<footer class="foot">', '<footer class="foot">\n    <p><a href="apt/" style="color:var(--ink)">단지 검색 (최근 실거래 위치) →</a> · <a href="report/" style="color:var(--ink)">백테스트 보고서 보기 →</a></p>'))
    html = (SITE / "index.html").read_text()  # 제목 아래에도 단지 검색 바로가기
    a = "<h1>서울 아파트 공포탐욕지도</h1>"
    assert html.count(a) == 1, a
    (SITE / "index.html").write_text(html.replace(a, a + '\n    <p style="margin:2px 0 0"><a class="btn" href="apt/" style="text-decoration:none;display:inline-block">단지 검색 · 최근 실거래가 위치 보기 →</a></p>'))
    wrap(ROOT / "apt" / "template.html", SITE / "apt" / "index.html",
         "서울 아파트 단지별 최근 실거래가가 최근 거래 범위 중 어디쯤인지 0~100으로 (층·시장 변화 보정).")
    data = ROOT / "results_apt"
    if (data / "index.json").exists():
        shutil.rmtree(SITE / "apt" / "data", ignore_errors=True)
        shutil.copytree(data, SITE / "apt" / "data")
    else:
        print("알림: results_apt가 없어 단지 검색 자료 없이 빌드 (python apt_score.py 먼저)")
    wrap(ROOT / "report" / "index.html", SITE / "report" / "index.html",
         "서울 아파트 공포탐욕지수 v3 백테스트 보고서.",
         inject=('<section class="top">', '<section class="top">\n    <p style="margin:0"><a href="../" style="color:var(--ink-2);font-size:13px">← 서울 아파트 공포탐욕지도</a></p>'))
    (SITE / ".nojekyll").write_text("")
    print("site:", [str(p.relative_to(ROOT)) for p in SITE.rglob("*.html")])
