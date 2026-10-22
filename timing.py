"""공개 시차와 갱신 일정.

백테스트와 실제 운영이 같은 정의를 쓰게 해서, 과거 점수에 미래 정보가 섞이거나 다음 달에 지난 점수가 바뀌는 일을 막는다.
실제 일정 (2026-10-22 확인): KB 월간 t월 자료는 t월 둘째 주 월요일 조사, t월 23~28일쯤 공개(명절이면 다음 달 2일쯤).
그래서 매달 20일 갱신의 기준월은 늘 지난달이고, 기준월 t 점수는 t+1월 20일에 나온다 (PUB_OFFSET = 1).
아래 늦춤(LAG1·LAG2, 실거래 2개월, 미분양·주담대 2개월, PIR·구매력 3개월, 가계신용 분기 끝+5개월)은 '갱신이 기준월 20일'이라는
옛 전제로 정한 것이라, 실제(기준월 다음 달 20일)보다 한 달씩 보수적이다 (미래 정보는 섞이지 않음). 고칠지는 갱신일과 함께 정한다.
"""
import numpy as np
import pandas as pd

LAG1 = [
    # 한국부동산원 R-ONE: 다음 달 중순 공개
    "거래_거래량", "거래_거래량증가", "거래_외지인비중", "거래_원정매수비중", "거래_2030비중", "거래_법인매수비중",
    "설문_부동산원매매수급", "전세_부동산원전세수급", "설문_국토연소비심리",
    # 한국은행 기준금리(월말)·국고채(월평균): 그달이 끝나야 확정
    "자금_기준금리수준", "자금_기준금리변화", "자금_국고채10년변화",
    # 월말 주가: 20일에는 그달이 끝나지 않음
    "시장_건설주모멘텀", "시장_건설주상대강도", "시장_KOSPI모멘텀",
    # 구글 트렌드 월간값: 그달이 끝나야 확정
    "관심_아파트", "관심_부동산", "관심_집값", "관심_청약", "관심_갭투자", "관심_공포어역수",
    # 한국은행 소비자동향조사 (그달 하순 공개, 보조 지표)
    "설문_주택가격전망CSI",
    # 청약홈 월간 집계 (보조 지표)
    "청약_1순위경쟁률", "청약_미달역수", "청약_무순위경쟁률", "청약_실제공급",
]


# 국토부 주택통계(미분양)는 다음 달 말 공개 → 20일 갱신 때는 2개월 전 값까지 (v3.3)
LAG2 = ["공급_미분양역수"]


def apply(df, cols=None):
    """df의 LAG1 열은 1개월, LAG2 열은 2개월 늦춘다 (cols를 주면 그중에서만)."""
    pool = cols if cols is not None else df.columns
    df = df.copy()
    for lag, names in ((1, LAG1), (2, LAG2)):
        cs = [c for c in pool if c in names and c in df.columns]
        df[cs] = df[cs].shift(lag)
    return df

# 분기·저빈도 자료는 다음 발표까지 이어 쓴다 (월간 자료의 기본 이어쓰기 3개월로는 최신 달 근처에서 끊김)
SLOW_FFILL = {"자금_가계신용증가": 5}  # 한국은행 분기 가계신용 (분기 끝 3개월 뒤 반영, 발표가 늦어져도 끊기지 않게 여유)


UPDATE_DAY = 20    # 월간 갱신일 (한국 시간). 예비 실행·감시는 이날부터 LAST_TRY_DAY까지 다시 시도
LAST_TRY_DAY = 22  # 이날까지 자료가 다 안 들어오면 있는 자료로 실시간 기록을 남긴다
PUB_OFFSET = 1     # 기준월 t 점수는 t+1월 갱신일에 발표 (그때 KB 월간 최신이 t)


def fwd(level, h=12):
    """정답: 발표한 달(기준월 + PUB_OFFSET)부터 h개월 로그 가격 변화. 기준월 t 점수는 t+1월 20일에 나오므로
    t → t+1 가격 변화는 발표 전 일이라 성적에 넣지 않는다 (2026-10-22 점검 전에는 기준월부터 재서 정확도가 0.59로 부풀었음, 발표 기준 0.56)."""
    lp = np.log(level)
    return lp.shift(-(h + PUB_OFFSET)) - lp.shift(-PUB_OFFSET)


def expected_label(today):
    """오늘 갱신하면 나와야 할 기준월 (월초 날짜)."""
    return (pd.Timestamp(today).to_period("M") - PUB_OFFSET).to_timestamp()


def freshness(raw, label):
    """이어 붙이기 전 각 열의 마지막 값이 기준월(label) 점수에 쓰일 달까지 왔는지 (월간 갱신 점검용).
    늦춤(LAG1·LAG2)만큼 이른 달이면 되고, 분기처럼 띄엄띄엄 나오는 열은 그 간격만큼 여유를 둔다.
    반환: {열: {"last": 마지막 달, "need": 있어야 할 달, "stale": 모자란지}}"""
    out = {}
    for c in raw.columns:
        s = raw[c].dropna()
        if len(s) < 3:
            continue
        lag = 1 if c in LAG1 else 2 if c in LAG2 else 0
        gap = max(1, round(pd.Series(s.index[-9:]).diff().dt.days.median() / 30.4))  # 1 = 월간, 3 = 분기
        need = label - pd.DateOffset(months=lag + gap - 1)
        out[c] = {"last": f"{s.index[-1]:%Y-%m}", "need": f"{need:%Y-%m}", "stale": bool(s.index[-1] < need)}
    return out


def fill_slow(df):
    df = df.copy()
    for c, lim in SLOW_FFILL.items():
        if c in df.columns:
            df[c] = df[c].ffill(limit=lim)
    return df
