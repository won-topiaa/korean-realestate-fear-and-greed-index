"""git 얹기(rebase) 중 겹친 단지 표를 단지 번호(aptSeq)로 합친다 (automation/push.sh가 부름).

양쪽에만 있는 단지는 모두 남기고, 같은 단지는 갈라지기 전(원본)과 비교한다:
- 한쪽만 바꿨으면 바꾼 쪽 (예전엔 줄을 통째로 골라, 한쪽이 채운 용적률 같은 칸이 다른 쪽 옛 줄로 지워졌음)
- 둘 다 바꿨으면 더 나은 줄을 고르고, 그 줄의 빈칸은 다른 쪽 값으로 채운다
  · buildings.csv: 받은 결과가 더 확실한 줄 (ok > none > missing > error > nocode > 빈칸), 같으면 나중에 받은 줄
  · complexes.csv: 최근 거래 달(last)이 더 늦은 줄, 같으면 이름 목록(names)이 더 긴 줄
사용: python automation/merge_tables.py data/molit_kr/buildings.csv
"""
import io
import subprocess
import sys

import pandas as pd

RANK = {"ok": 5, "none": 4, "missing": 3, "error": 2, "nocode": 1}


def side(stage, path):
    """얹는 중 겹친 파일의 한쪽 (1 = 갈라지기 전 원본, 2 = 이미 main에 있는 쪽, 3 = 이번 실행이 바꾼 쪽). 원본이 없으면 None."""
    r = subprocess.run(["git", "show", f":{stage}:{path}"], capture_output=True, text=True)
    if r.returncode != 0:
        if stage == 1:
            return None
        raise RuntimeError(r.stderr.strip())
    return pd.read_csv(io.StringIO(r.stdout), dtype=str, keep_default_na=False)


def merge(base, a, b, path):
    cols = list(a.columns)
    i_seq = cols.index("aptSeq")
    kcols = [cols.index(c) for c in (("status", "fetched") if path.endswith("buildings.csv") else ("last", "names"))]

    def rows(df):
        return {} if df is None else {r[i_seq]: r for r in df.itertuples(index=False, name=None)}

    def key(r):
        if path.endswith("buildings.csv"):
            return RANK.get(r[kcols[0]], 0), r[kcols[1]]
        return r[kcols[0]], len(r[kcols[1]])

    O, A, B = rows(base), rows(a), rows(b)
    out = []
    for seq in sorted(A.keys() | B.keys()):
        ra, rb, ro = A.get(seq), B.get(seq), O.get(seq)
        if ra is None or rb is None:
            out.append(ra or rb)
        elif ra == ro or ra == rb:  # main 쪽은 그대로 → 이번 실행 쪽
            out.append(rb)
        elif rb == ro:  # 이번 실행 쪽은 그대로 → main 쪽
            out.append(ra)
        else:  # 둘 다 바꿈 (같으면 이번 실행 쪽): 나은 줄의 빈칸은 다른 쪽 값으로
            win, lose = (ra, rb) if key(ra) > key(rb) else (rb, ra)
            out.append(tuple(w if w != "" else l for w, l in zip(win, lose)))
    return pd.DataFrame(out, columns=cols)


if __name__ == "__main__":
    p = sys.argv[1]
    o, a, b = side(1, p), side(2, p), side(3, p)
    if list(a.columns) != list(b.columns):
        sys.exit(f"{p}: 양쪽 열이 달라 합칠 수 없어요")
    if o is not None and list(o.columns) != list(a.columns):
        o = None  # 원본만 열이 다르면 (그 뒤 양쪽에 같은 열을 더함) 원본 없이 합침
    out = merge(o, a, b, p)
    out.to_csv(p, index=False)
    print(f"{p}: {len(a)} + {len(b)} → {len(out)}줄로 합침" + ("" if o is not None else " (원본 없이)"))
