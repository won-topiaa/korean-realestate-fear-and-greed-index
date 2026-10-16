"""링크 미리보기 이미지 (카카오톡·문자·SNS에 링크를 보낼 때 뜨는 그림) → assets/og/{페이지}.jpg (1200×630).

사이트와 같은 모습(페이지 사진을 어둡게 깐 띠 + 로고 + 두 단 제목)을 HTML로 그려 헤드리스 Chrome으로 찍는다.
글꼴은 사이트와 같은 Google Fonts라 인터넷 연결이 필요하다. 로컬에서 한 번 만들어 저장소에 올린다 (사이트 빌드는 이 파일을 쓰기만 한다).
사용: python og_build.py   (Chrome 위치는 CHROME 환경변수로 바꿀 수 있음)
"""
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parent
OUT = ROOT / "assets" / "og"
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
SITE = "won-topiaa.github.io/korean-realestate-fear-and-greed-index"

# 페이지: (사진, 사진 세로 위치, 윗줄, 큰 제목, 설명)
PAGES = {
    "map": ("bg-map", "50%", "서울 아파트", "공포탐욕지도", "서울 5대 권역·25개 구의 공포와 탐욕을 0~100으로 매달 보여드려요"),
    "apt": ("bg-apt", "40%", "최근 실거래가, 비싼 편일까?", "단지 검색", "우리 단지 최근 거래가 최근 2년 거래 중 어디쯤인지 0~100점으로"),
    "highs": ("bg-highs", "45%", "이번 달 가장 비싸게 팔린 집", "신고가 단지", "같은 단지·같은 평형의 지난 모든 거래보다 비싸게 팔린 거래"),
    "sim": ("bg-sim", "38%", "그때 샀다면 지금 얼마?", "모의 투자", "실거래로 계산하는 가상 투자 · 단지 2~3개 같은 기간 비교"),
    "report": ("bg-report", "50%", "서울 공포탐욕지수", "백테스트", "실거래 141만 건으로 검증한 지수의 정확도와 한계"),
}

HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@100..125,400..900&family=Noto+Sans+KR:wght@400;600;700;900&family=Poiret+One&display=block">
<style>
* {{ box-sizing: border-box; margin: 0; }}
html, body {{ width: 1200px; height: 630px; overflow: hidden; background: #141414; }}
.card {{ position: relative; width: 1200px; height: 630px; color: #fff; font-family: "Noto Sans KR", sans-serif; overflow: hidden; }}
.bg {{ position: absolute; inset: 0; background: #1d1d1d url('{img}') center {y} / cover no-repeat; }}
.shade {{ position: absolute; inset: 0; background: linear-gradient(90deg, rgba(16,16,16,.92) 0%, rgba(16,16,16,.78) 50%, rgba(16,16,16,.5) 100%); }}
.in {{ position: absolute; inset: 0; padding: 56px 64px; display: flex; flex-direction: column; }}
.logo {{ display: grid; line-height: 1.15; }}
.logo .en {{ font-family: "Poiret One", sans-serif; font-size: 34px; letter-spacing: .04em; }}
.logo .ko {{ font-size: 19px; font-weight: 600; color: #d6d6d6; }}
.h {{ margin-top: auto; display: grid; gap: 4px; }}
.h .a {{ font-size: 40px; font-weight: 600; letter-spacing: -.02em; }}
.h .b {{ font-family: "Archivo", "Noto Sans KR", sans-serif; font-size: 104px; font-weight: 900; font-stretch: 112%; letter-spacing: -.025em; line-height: 1.02; }}
.d {{ margin-top: 18px; font-size: 25px; color: #e2e2e2; }}
.foot {{ margin-top: 26px; display: flex; align-items: center; gap: 14px; font-size: 18px; color: #cfcfcf; }}
.tag {{ background: #fff; color: #1d1d1d; font-weight: 700; padding: 6px 14px; }}
.dot1 {{ position: absolute; width: 170px; height: 170px; border-radius: 50%; border: 3px solid rgba(255,255,255,.55); right: 70px; top: 56px; }}
.dot2 {{ position: absolute; width: 70px; height: 70px; border-radius: 50%; background: rgba(255,255,255,.9); right: 96px; top: 262px; }}
</style></head><body><div class="card"><div class="bg"></div><div class="shade"></div><i class="dot1"></i><i class="dot2"></i>
<div class="in">
  <div class="logo"><span class="en">SEOUL FEAR &amp; GREED</span><span class="ko">서울 아파트 공포탐욕지도</span></div>
  <div class="h"><span class="a">{a}</span><span class="b">{b}</span></div>
  <p class="d">{d}</p>
  <div class="foot"><span class="tag">매달 20일 갱신</span><span>국토교통부 실거래가 · 공공데이터</span><span style="margin-left:auto">{site}</span></div>
</div></div></body></html>"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name, (img, y, a, b, d) in PAGES.items():
            html = Path(tmp) / f"{name}.html"
            html.write_text(HTML.format(img=(ROOT / "assets" / "img" / f"{img}.jpg").as_uri(), y=y, a=a, b=b, d=d, site=SITE))
            png = Path(tmp) / f"{name}.png"
            subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                            "--virtual-time-budget=8000", "--allow-file-access-from-files", "--window-size=1200,630",
                            f"--screenshot={png}", html.as_uri()], check=True, capture_output=True, timeout=120)
            im = Image.open(png).convert("RGB").crop((0, 0, 1200, 630))
            im.save(OUT / f"{name}.jpg", "JPEG", quality=84, optimize=True, progressive=True)
            print(name, (OUT / f"{name}.jpg").stat().st_size // 1000, "KB")


if __name__ == "__main__":
    main()
