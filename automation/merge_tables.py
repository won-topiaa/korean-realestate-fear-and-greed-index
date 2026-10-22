"""git 얹기(rebase) 중 겹친 단지 표를 단지 번호(aptSeq)로 합친다 (automation/push.sh가 부름).

양쪽에만 있는 단지는 모두 남기고, 같은 단지면 더 나은 줄을 고른다:
- buildings.csv: 받은 결과가 더 확실한 줄 (ok > none > missing > error > nocode > 빈칸), 같으면 나중에 받은 줄
- complexes.csv: 최근 거래 달(last)이 더 늦은 줄, 같으면 이름 목록(names)이 더 긴 줄
사용: python automation/merge_tables.py data/molit_kr/buildings.csv
"""
import io
import subprocess
import sys

import pandas as pd

RANK = {"ok": 5, "none": 4, "missing": 3, "error": 2, "nocode": 1}


def side(stage, path):
    """얹는 중 겹친 파일의 한쪽 (2 = 이미 main에 있는 쪽, 3 = 이번 실행이 바꾼 쪽)."""
    out = subprocess.run(["git", "show", f":{stage}:{path}"], capture_output=True, text=True, check=True).stdout
    return pd.read_csv(io.StringIO(out), dtype=str, keep_default_na=False)


def merge(a, b, path):
    df = pd.concat([a, b], ignore_index=True)
    if path.endswith("buildings.csv"):
        key = [df["status"].map(RANK).fillna(0), df["fetched"]]
    else:
        key = [df["last"], df["names"].str.len()]
    df = df.assign(_k1=key[0], _k2=key[1]).sort_values(["aptSeq", "_k1", "_k2"], kind="mergesort")
    return df.drop_duplicates("aptSeq", keep="last").drop(columns=["_k1", "_k2"]).sort_values("aptSeq")


if __name__ == "__main__":
    p = sys.argv[1]
    a, b = side(2, p), side(3, p)
    if list(a.columns) != list(b.columns):
        sys.exit(f"{p}: 양쪽 열이 달라 합칠 수 없어요")
    out = merge(a, b, p)[list(a.columns)]
    out.to_csv(p, index=False)
    print(f"{p}: {len(a)} + {len(b)} → {len(out)}줄로 합침")
