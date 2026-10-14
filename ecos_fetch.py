"""한국은행 ECOS: 기준금리, 국고채 10년, 주택담보대출 금리, 가계신용·명목 GDP, 주택가격전망 CSI → data/raw/ecos/*.json"""
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "raw" / "ecos"
OUT.mkdir(parents=True, exist_ok=True)
KEY = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().split()).get("ECOS_KEY", "")
SERIES = {  # 이름: (통계표, 주기, 항목 코드들, 시작)
    "기준금리": ("722Y001", "M", ["0101000"], "199905"),
    "국고채10년": ("721Y001", "M", ["5050000"], "200010"),
    "주담대금리": ("121Y006", "M", ["BECBLA0302"], "200109"),
    "가계신용": ("151Y001", "Q", ["1000000"], "2002Q4"),  # 분기, 십억원
    "명목GDP": ("200Y105", "Q", ["1400"], "2000Q1"),  # 원계열 명목, 분기, 십억원
    "주택가격전망CSI": ("511Y002", "M", ["FMFB", "99988"], "201301"),
}


def get(path):
    for attempt in range(5):
        out = subprocess.run(["curl", "-sS", "--http1.1", "-m", "60", f"https://ecos.bok.or.kr/api/{path}"], capture_output=True, text=True)
        try:
            return json.loads(out.stdout)
        except json.JSONDecodeError:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"ECOS 응답 해석 실패 · {(out.stdout or out.stderr)[:160].replace(KEY, '***')}")


def fetch(name, end):
    code, cycle, items, start = SERIES[name]
    if cycle == "Q":
        end = f"{end[:4]}Q{(int(end[4:6]) - 1) // 3 + 1}"
    j = get(f"StatisticSearch/{KEY}/json/kr/1/2000/{code}/{cycle}/{start}/{end}/" + "/".join(items))
    rows = j.get("StatisticSearch", {}).get("row")
    if not rows:
        raise RuntimeError(f"{name}: {json.dumps(j.get('RESULT', j), ensure_ascii=False)[:200].replace(KEY, '***')}")
    data = [{"date": r["TIME"], "value": float(r["DATA_VALUE"]), "unit": r.get("UNIT_NAME"), "item": r.get("ITEM_NAME1")} for r in rows]
    tmp = OUT / f"{name}.json.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(OUT / f"{name}.json")
    return data


def refresh(end=None):
    import datetime as dt
    end = end or dt.date.today().strftime("%Y%m")
    done = {}
    for n in SERIES:
        d = fetch(n, end)
        done[n] = d[-1]["date"]
        time.sleep(0.5)
    return done


if __name__ == "__main__":
    for n, last in refresh().items():
        d = json.loads((OUT / f"{n}.json").read_text())
        print(f"{n}: {d[0]['date']}~{last} · {len(d)}개 · 단위 {d[0]['unit']} · 최근 {d[-1]['value']}")
