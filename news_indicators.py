"""빅카인즈 키워드 월간 기사 수(전국일간지+경제일간지) → 뉴스 언급 지표.

모든 키워드는 '부동산' 기사 수로 나눈 비율로 쓴다 (수록 언론사가 늘어나는 효과를 상쇄).
결과: data/news_indicators.csv
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent
GREED = ["집값상승", "신고가", "과열", "청약열풍", "갭투자", "영끌"]
FEAR = ["집값하락", "급매", "거래절벽", "미분양", "하우스푸어", "역전세"]


def load():
    df = pd.read_csv(ROOT / "data" / "raw" / "bigkinds" / "keyword_trends_monthly.csv", dtype={"date": str})
    df.columns = [c.lstrip("﻿") for c in df.columns]
    df.index = pd.to_datetime(df.pop("date"), format="%Y%m")
    df = df.iloc[:-1]  # 2026-10은 12일까지만 집계돼 제외
    return df.fillna(0).astype(float)  # 갭투자·영끌 초기 공백 = 그 시기엔 없던 말 (0건)


def build():
    c = load()
    s3 = c.rolling(3).sum()
    base = s3["부동산"]
    ind = {}
    for k in GREED:
        ind[f"뉴스_{k}"] = s3[k] / base
    for k in FEAR:
        ind[f"뉴스_{k}역수"] = -s3[k] / base
    g, f = s3[GREED].sum(axis=1), s3[FEAR].sum(axis=1)
    ind["뉴스_탐욕비중"] = g / (g + f)
    ind["뉴스_탐욕공포비"] = np.log((g + 1) / (f + 1))
    ind["뉴스_부동산관심"] = np.log(s3["부동산"] / s3["부동산"].rolling(24).mean())
    return pd.DataFrame(ind).where(base.notna())


META_NEWS = {
    "뉴스_탐욕비중": ("뉴스 탐욕어 / (탐욕어+공포어) 기사 비중 (빅카인즈)", "뉴스", "선행", "뉴스", "언론", "매매", "", "언급수"),
    "뉴스_탐욕공포비": ("뉴스 탐욕어 대 공포어 로그비", "뉴스", "선행", "뉴스", "언론", "매매", "", "언급수"),
    "뉴스_부동산관심": ("'부동산' 기사 수 단기 급증 (3개월/24개월)", "뉴스", "선행", "뉴스", "언론", "매매", "", "언급수"),
    **{f"뉴스_{k}": (f"'{k}' 기사 / '부동산' 기사", "뉴스", "선행", "뉴스", "언론", "매매", "", "언급수") for k in GREED},
    **{f"뉴스_{k}역수": (f"'{k}' 기사 / '부동산' 기사 (부호 반대)", "뉴스", "선행", "뉴스", "언론", "매매", "", "언급수") for k in FEAR},
}

if __name__ == "__main__":
    n = build()
    n.to_csv(ROOT / "data" / "news_indicators.csv")
    print(n.dropna(how="all").iloc[[0, 60, 120, 180, 200, -1]].round(3).to_string())
