"""GitHub Pages용 정적 사이트: site/index.html (지도), site/report/index.html (보고서).

아티팩트용 HTML에는 문서 머리말이 없어서, 문자 인코딩·뷰포트·doctype을 감싸 정식 문서로 만든다.
"""
from pathlib import Path

ROOT = Path(__file__).parent
SITE = ROOT / "site"
HEAD = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="{desc}">
<style>[hidden]{{display:none!important}} body{{margin:0}}</style>
</head>
<body>
"""
TAIL = "\n</body>\n</html>\n"


def wrap(src, dst, desc, inject=None):
    html = src.read_text()
    if inject:
        a, b = inject
        assert html.count(a) == 1, a
        html = html.replace(a, b)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(HEAD.format(desc=desc) + html + TAIL)


if __name__ == "__main__":
    wrap(ROOT / "map" / "index.html", SITE / "index.html",
         "서울 5대 권역별 아파트 공포탐욕지수 지도. 매달 자동 갱신.",
         inject=('<footer class="foot">', '<footer class="foot">\n    <p><a href="report/" style="color:var(--ink)">백테스트 보고서 보기 →</a></p>'))
    wrap(ROOT / "report" / "index.html", SITE / "report" / "index.html",
         "서울 아파트 공포탐욕지수 v3 백테스트 보고서.",
         inject=('<section class="top">', '<section class="top">\n    <p style="margin:0"><a href="../" style="color:var(--ink-2);font-size:13px">← 서울 공포탐욕 지도</a></p>'))
    (SITE / ".nojekyll").write_text("")
    print("site:", [str(p.relative_to(ROOT)) for p in SITE.rglob("*.html")])
