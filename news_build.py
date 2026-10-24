"""주간 소식 (지수와 엮은 소식 정리) → data/news/YYYY-MM-DD.json (그 주 월요일 = 발행일, 저장소에 쌓음).
화면은 site_build.py가 render()로 news/template.html에 넣어 만든다 (site/news/).

매주 월요일 weekly-update.yml이 돈다. 구글 뉴스 RSS에서 발행일 전 7일(월요일 발행이면 지난주 월~일, 한국 시간) 국내 기사의 제목·언론사·날짜·링크만
주제별로 모은다. 기사 내용은 가져오지 않고, 링크는 각 언론사 기사로 간다. 주제는 지수의 주제 점수와 같은 이름(자금·가격·거래·전세·공급)이고,
그 주제의 서울 점수(발행 때의 최신 달 값과 지난달 대비)를 함께 남겨 '이번 주 소식이 지수의 어느 칸에 닿는지' 보여 준다.
고르는 규칙은 기계적이다: 구글 뉴스 관련도 순에 서울·수도권·정부·한국은행·통계처럼 시장 전체를 다룬 제목을 앞으로 당기고,
해외·광고성(견본주택·분양 홍보 등) 기사를 빼고, 같은 사건을 다룬 기사(제목 글자 두 개씩 묶음이 많이 겹치는 것)는 하나만,
한 주제 안에서 언론사는 하나씩. 사고팔 시점을 알려 주는 글이 아니다.

사용: python news_build.py           # 오늘 발행. 지난 호가 6일 안에 나왔으면 건너뜀 (호끼리 기간이 겹치지 않게, 같은 날이면 덮어씀)
      python news_build.py --force   # 그래도 오늘 발행 (구글 뉴스는 최근 7일만 주므로 지난 호는 다시 만들 수 없음)
"""
import datetime as dt
import html
import json
import re
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).parent
DIR = ROOT / "data" / "news"
KST = dt.timezone(dt.timedelta(hours=9))
PER_THEME = 4

# (지수의 주제 이름, 부제, 구글 뉴스 검색어, 이 주제 점수가 움직이는 방향)
THEMES = [
    ("자금", "금리·대출", ["주택담보대출 금리", "기준금리 한국은행 부동산", "가계대출 규제 DSR"],
     "대출 금리가 오르거나 대출 규제가 조이면 이 점수는 공포 쪽으로, 금리가 내리고 대출이 풀리면 탐욕 쪽으로 움직여요."),
    ("가격", "매매가격", ["서울 아파트값 부동산원", "아파트 매매가격 상승률"],
     "가격이 빠르게 오르면 탐욕 쪽, 내리면 공포 쪽으로 움직여요."),
    ("거래", "거래량·거래 규제", ["아파트 거래량", "토지거래허가구역 아파트"],
     "거래가 늘면 탐욕 쪽, 줄면 공포 쪽으로 움직여요."),
    ("전세", "전셋값·전세 매물", ["아파트 전셋값", "전세 매물 아파트"],
     "전셋값이 오르면 매매로 옮겨 가는 수요가 늘어 탐욕 쪽, 내리면 공포 쪽으로 움직여요."),
    ("공급", "공급·미분양", ["미분양 아파트", "주택 공급 착공 인허가"],
     "미분양이 쌓이면 공포 쪽, 줄어들면 탐욕 쪽으로 움직여요."),
]
SKIP = re.compile(r"美|미국|中|중국|日|일본|홍콩|싱가포르|영국|유럽|호주|캐나다|독일|베트남|호치민|하노이|태국|인도네시아|필리핀|두바이|"
                  r"\[(포토|사진|영상|광고|AD)\]|모델하우스|견본주택|분양 ?중|그랜드 ?오픈|특별공급|청약 ?접수|오피스텔|상가|지식산업센터|생활숙박")
SKIP_SRC = {"인사이드비나"}  # 해외 부동산 전문지
WIDE = re.compile(r"서울|수도권|전국|정부|국토부|국토교통부|한국은행|한은|금융위|부동산원|통계|대책|규제|기준금리|주담대")  # 시장 전체를 다룬 제목
SAME = 0.3  # 제목 글자 두 개씩 묶음이 이만큼 겹치면 같은 사건으로 봄


def week():
    """(발행일 = 오늘, 정리 기간 첫날, 끝날): 발행일 전 7일 (구글 뉴스 'when:7d'와 같은 기간)."""
    today = dt.datetime.now(KST).date()
    return today, today - dt.timedelta(days=7), today - dt.timedelta(days=1)


def fetch(q):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q + " when:7d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    # curl로 (다른 수집 스크립트와 같게: 맥의 파이썬은 인증서 저장소가 비어 있을 때가 있음)
    r = subprocess.run(["curl", "-sS", "-f", "-m", "30", "-A", "Mozilla/5.0 (aptfeargreed.com weekly news)", url], capture_output=True, check=True)
    root = ET.fromstring(r.stdout)
    out = []
    for it in root.findall("./channel/item"):
        src = (it.findtext("source") or "").strip()
        title = (it.findtext("title") or "").strip()
        for _ in range(2):  # 끝의 ' - 언론사' (구글 뉴스가 붙인 것과 기사 제목에 원래 있던 것, 영문 이름일 때도)
            title = re.sub(r"\s+-\s+[^-]{1,20}$", "", title).strip()
        title = title.rstrip(" |")
        try:
            when = parsedate_to_datetime(it.findtext("pubDate")).astimezone(KST).date()
        except (TypeError, ValueError):
            continue
        out.append({"t": html.unescape(title), "s": src, "d": when.isoformat(), "u": (it.findtext("link") or "").strip()})
    return out


def grams(t):
    s = re.sub(r"[^가-힣A-Za-z0-9]", "", t)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def same(a, b):
    return len(a & b) / max(1, min(len(a), len(b))) >= SAME


def theme_scores():
    """서울 주제 점수: {주제: (최신 값, 지난달 값)}, 최신 달."""
    d = json.loads((ROOT / "results_zone" / "map_data.json").read_text())
    th, out, month = d["regions"]["서울"]["themes"], {}, None
    for name, s in th.items():
        i = max((k for k, v in enumerate(s) if v is not None), default=None)
        if i is None:
            continue
        prev = next((s[k] for k in range(i - 1, -1, -1) if s[k] is not None), None)
        out[name] = (round(s[i], 1), None if prev is None else round(prev, 1))
        month = d["dates"][i]
    return out, month


def build(force=False):
    mon, start, end = week()
    last = max((dt.date.fromisoformat(p.stem) for p in DIR.glob("*.json")), default=None)
    if last and mon - dt.timedelta(days=6) <= last < mon and not force:
        print(f"주간 소식: 지난 호({last})가 6일 안이라 건너뜀 — 다음 호는 {last + dt.timedelta(days=7)} 무렵")
        return None
    scores, month = theme_scores()
    taken, themes = [], []  # 이미 고른 기사의 제목 묶음 (주제끼리도 겹치지 않게)
    for name, sub, queries, note in THEMES:
        cands, errors = [], []
        for q in queries:
            try:
                items = fetch(q)
            except Exception as e:  # noqa: BLE001  (검색어 하나가 실패해도 나머지로)
                errors.append(f"{q}: {type(e).__name__} {getattr(e, 'stderr', b'')[:80]!r}" if isinstance(e, subprocess.CalledProcessError) else f"{q}: {type(e).__name__}")
                continue
            cands += [(i - (15 if WIDE.search(x["t"]) else 0), x) for i, x in enumerate(items)]  # 관련도 순위, 시장 전체 제목은 앞으로
        picked, srcs = [], set()
        for _, x in sorted(cands, key=lambda c: c[0]):
            g = grams(x["t"])
            if len(picked) >= PER_THEME:
                break
            if not (start.isoformat() <= x["d"] <= end.isoformat()) or SKIP.search(x["t"]) or x["s"] in SKIP_SRC or x["s"] in srcs or len(g) < 6:
                continue
            if any(same(g, h) for h in taken):
                continue
            taken.append(g)
            srcs.add(x["s"])
            picked.append(x)
        sc = scores.get(name, (None, None))
        themes.append({"name": name, "sub": sub, "note": note, "score": sc[0], "prev": sc[1],
                       "items": sorted(picked, key=lambda x: x["d"], reverse=True), **({"errors": errors} if errors else {})})
    n = sum(len(t["items"]) for t in themes)
    if not n:
        errs = [e for t in themes for e in t.get("errors", [])]
        raise SystemExit(f"주간 소식: 고른 기사가 없음 ({start}~{end}) — 지난 호 그대로" + (f" · 검색 실패 {len(errs)}건, 예: {errs[0]}" if errs else ""))
    doc = {"issue": mon.isoformat(), "from": start.isoformat(), "to": end.isoformat(), "made": dt.datetime.now(KST).isoformat(timespec="minutes"),
           "month": month, "source": "구글 뉴스 검색 (제목·언론사·날짜·링크만)", "themes": themes}
    DIR.mkdir(parents=True, exist_ok=True)
    out = DIR / f"{mon.isoformat()}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    print(f"주간 소식 {mon} 호 ({start}~{end}): 기사 {n}건 · " + " · ".join(f"{t['name']} {len(t['items'])}" for t in themes))
    return out


# ---------------- 화면 조각 (site_build.py가 news/template.html의 <!--NEWS-->에 넣음) ----------------
def band(v):
    r = round(v)
    return ("극단적 공포", "fear2") if r < 25 else ("공포", "fear") if r < 45 else ("중립", "neutral") if r < 55 else ("탐욕", "greed") if r < 75 else ("극단적 탐욕", "greed2")


def _md(d):
    return f"{int(d[5:7])}.{int(d[8:10])}"


def _issue_title(doc):
    a, b = dt.date.fromisoformat(doc["from"]), dt.date.fromisoformat(doc["to"])
    i = dt.date.fromisoformat(doc["issue"])
    return f"{a.month}월 {a.day}일~{f'{b.month}월 ' if b.month != a.month else ''}{b.day}일 소식", f"{i.month}월 {i.day}일 정리"


def _theme(t, month):
    e = html.escape
    out = [f'<section class="th"><div class="th-h"><h3>{e(t["name"])} <small>{e(t["sub"])}</small></h3>']
    if t["score"] is not None:
        lab, cls = band(t["score"])
        dd = "" if t["prev"] is None else round(t["score"]) - round(t["prev"])
        delta = "" if dd == "" else " · 지난달과 같아요" if dd == 0 else f' · 지난달보다 {"▲" if dd > 0 else "▼"}{abs(dd)}'
        out.append(f'<span class="sc {cls}" title="서울 지수의 {e(t["name"])} 점수 ({month[:4]}년 {int(month[5:7])}월)">서울 {e(t["name"])} 점수 '
                   f'<b>{round(t["score"])}</b> {lab}{delta}</span>')
    out.append(f'</div><p class="why">{e(t["note"])}</p>')
    if t["items"]:
        out.append('<ul class="items">' + "".join(
            f'<li><a href="{e(x["u"])}" target="_blank" rel="noopener nofollow">{e(x["t"])}</a><small>{e(x["s"])} · {_md(x["d"])}</small></li>'
            for x in t["items"]) + "</ul>")
    else:
        out.append('<p class="none">이번 주에는 고른 기사가 없어요.</p>')
    return "".join(out) + "</section>"


def render(limit=12):
    files = sorted(DIR.glob("*.json"), reverse=True)[:limit]
    if not files:
        return '<section class="panel"><p class="none">첫 정리는 다음 월요일 아침에 올라와요.</p></section>'
    out = []
    for i, f in enumerate(files):
        doc = json.loads(f.read_text())
        title, rng = _issue_title(doc)
        month = doc.get("month") or ""
        body = "".join(_theme(t, month) for t in doc["themes"])
        head = (f'<h2>{title} <small>{rng} · 점수는 {int(month[:4])}년 {int(month[5:7])}월 지수</small></h2>' if month else f"<h2>{title} <small>{rng}</small></h2>")
        if i == 0:
            out.append(f'<section class="panel issue" id="w{doc["issue"]}">{head}<div class="ths">{body}</div></section>')
        else:
            out.append(f'<details class="panel issue past" id="w{doc["issue"]}"><summary>{head}</summary><div class="ths">{body}</div></details>')
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    build(force="--force" in sys.argv)
