"""공개 시차와 갱신 일정.

백테스트와 실제 운영이 같은 정의를 쓰게 해서, 과거 점수에 미래 정보가 섞이거나 다음 달에 지난 점수가 바뀌는 일을 막는다.
실제 일정 (2026-10-22 확인): KB 월간 t월 자료는 t월 둘째 주 월요일 조사, t월 23~28일쯤 공개(명절이면 다음 달 2일쯤).
그래서 매달 20일 갱신의 기준월은 늘 지난달이고, 기준월 t 점수는 t+1월 20일에 나온다 (PUB_OFFSET = 1).
늦춤은 v3.5(2026-10-22)부터 이 실제 일정에 맞춘다: 그날 나와 있는 가장 새 달을 쓴다.
- 0개월: KB 월간, 금리·국고채(그달 평균·말), 주가(월말), 구글 검색량, CSI, 청약, 부동산원 수급
- 1개월: 부동산원 거래현황, 미분양, 주담대 금리(build_indicators), 국토연 소비심리(부동산원 사본)
- 실거래 신고가·급락: 2020년 2월 전 2개월, 뒤 1개월 (trade_lag) · 가계신용: 분기 끝 + 2개월 · PIR·구매력: 분기 공개 달부터 (quarterly_release)
(v3.4까지는 '갱신 = 기준월 20일'이라는 옛 전제로 정해 한 달씩 보수적이었음 — 미래 정보는 섞이지 않았음)
"""
import numpy as np
import pandas as pd

# v3.5 (2026-10-22): 기준월 t 점수는 t+1월 20일에 나오므로 그날 나와 있는 달을 쓴다 (발표일 조사, README '공개 시차').
# 금리·주가·검색량·CSI·청약·부동산원 수급은 t월 값이 그날 이미 있어 늦추지 않는다 (예전엔 '20일 = 기준월' 전제로 1개월 늦췄음).
LAG1 = [
    # 한국부동산원 거래현황(거래량·매입자 거주지·연령·주체): t월 값은 t+1월 말 공개 → t−1월까지
    "거래_거래량", "거래_거래량증가", "거래_외지인비중", "거래_원정매수비중", "거래_2030비중", "거래_법인매수비중",
    # 국토연 소비심리(부동산원 사본, 보조 지표): t+1월 20일에 t−1월까지
    "설문_국토연소비심리",
    # 국토부 주택통계(미분양): t월 값은 t+1월 말 공개 → t−1월까지
    "공급_미분양역수",
]
LAG2 = []


def apply(df, cols=None):
    """df의 LAG1 열은 1개월, LAG2 열은 2개월 늦춘다 (cols를 주면 그중에서만)."""
    pool = cols if cols is not None else df.columns
    df = df.copy()
    for lag, names in ((1, LAG1), (2, LAG2)):
        cs = [c for c in pool if c in names and c in df.columns]
        df[cs] = df[cs].shift(lag)
    return df

# 분기·저빈도 자료는 다음 발표까지 이어 쓴다 (월간 자료의 기본 이어쓰기 3개월로는 최신 달 근처에서 끊김)
SLOW_FFILL = {"자금_가계신용증가": 5}  # 한국은행 분기 가계신용 (분기 끝 2개월 뒤 기준월부터, 다음 분기가 늦어져도 끊기지 않게 여유)


UPDATE_DAY = 20    # 월간 갱신일 (한국 시간). 예비 실행·감시는 이날부터 LAST_TRY_DAY까지 다시 시도
LAST_TRY_DAY = 22  # 이날까지 자료가 다 안 들어오면 있는 자료로 실시간 기록을 남긴다
PUB_OFFSET = 1     # 기준월 t 점수는 t+1월 갱신일에 발표 (그때 KB 월간 최신이 t)


def trade_lag(s):
    """실거래 지표(신고가·급락 비중, 그때 알 수 있던 실거래 변화)의 늦춤. 기준월 t 점수는 t+1월 20일 발표.
    신고 기한 30일(2020-02-21 계약부터)이면 t−1월 계약까지 다 들어와 1개월, 그 전(60일)은 t−2월까지라 2개월."""
    return s.shift(1).where(s.index >= "2020-03-01", s.shift(2))


def quarterly_release(s):
    """KB PIR·주택구매력: 1~3월분 5월, 4~6월분 8월, 7~9월분 11월, 10~12월분 2월 공개 (KB 데이터허브 안내).
    공개된 달을 기준월로 하는 점수부터 쓴다 (그 점수는 다음 달 20일 발표라 그때는 이미 나와 있음)."""
    s = s.dropna()
    avail = (s.index.to_period("Q").asfreq("M", "end") + 2).to_timestamp()
    return s.groupby(avail).last()


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
        if c in SLOW_FFILL:  # 분기 자료를 달마다 펼쳐 둔 열 (가계신용): 다음 분기가 나올 때까지는 모자란 게 아님
            gap = 3
        need = label - pd.DateOffset(months=lag + gap - 1)
        out[c] = {"last": f"{s.index[-1]:%Y-%m}", "need": f"{need:%Y-%m}", "stale": bool(s.index[-1] < need)}
    return out


def fill_slow(df):
    df = df.copy()
    for c, lim in SLOW_FFILL.items():
        if c in df.columns:
            df[c] = df[c].ffill(limit=lim)
    return df
