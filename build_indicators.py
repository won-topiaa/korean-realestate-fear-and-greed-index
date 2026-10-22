"""원자료 → 서울 월간 지표 테이블 (data/indicators.csv) + 메타 (data/indicator_meta.csv).

모든 지표는 '값이 클수록 탐욕'이 되도록 부호를 맞춘다. 미래 정보가 섞이지 않게
발표 시차가 있는 자료(BIS 가계신용)는 뒤로 미룬다.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"


def _ym(s):
    return pd.to_datetime(s, format="%Y%m")


def kb_survey(name, field, region="서울"):
    d = json.loads((RAW / "kb" / f"{name}.json").read_text())
    row = next(x for x in d["데이터리스트"] if x["지역명"] == region)
    s = pd.Series({_ym(e["기준날짜"]): e[field] for e in row["dataList"]})
    return s.astype(float).sort_index()


def kb_aligned(name, region="서울"):
    """날짜리스트와 위치로 맞춰진 dataList (가격지수, 전세가율)."""
    d = json.loads((RAW / "kb" / f"{name}.json").read_text())
    dates = d["날짜리스트"]
    row = next(x for x in d["데이터리스트"] if x["지역명"] == region)
    return pd.Series(row["dataList"][: len(dates)], index=_ym(pd.Series(dates))).astype(float)


def kb_gu_panel():
    d = json.loads((RAW / "kb" / "아파트매매지수_월간_서울구.json").read_text())
    dates = _ym(pd.Series(d["날짜리스트"]))
    return pd.DataFrame({x["지역명"]: pd.Series(x["dataList"][: len(dates)], index=dates, dtype=float)
                         for x in d["데이터리스트"]})


def kb_lead50():
    d = json.loads((RAW / "kb" / "선도50.json").read_text())
    return pd.Series(d["선도50지수리스트"], index=_ym(pd.Series(d["날짜리스트"]))).astype(float)


def kb_hai(region="서울"):
    d = json.loads((RAW / "kb" / "HAI.json").read_text())
    dates = _ym(pd.Series(d["날짜리스트"]))
    rate = pd.Series({_ym(e["기준날짜"]): e["주택담보대출금리"] for e in d["주담보월소득리스트"]}).astype(float)
    seoul = next(x for x in d["주택구매력리스트"] if x["지역명"] == region)
    apt = next(e for e in seoul["지역구분리스트"] if e["매물종별구분"] == "아파트")
    return rate.sort_index(), pd.Series(apt["매물종별구분리스트"], index=dates).astype(float)


def kb_pir(house_q=3, income_q=3, region="서울"):
    d = json.loads((RAW / "kb" / "PIR.json").read_text())
    dates = _ym(pd.Series(d["날짜리스트"]))
    seoul = next(x for x in d["데이터리스트"] if x["지역명"] == region)
    h = next(e for e in seoul["주택분위구분"] if e["주택분위"] == house_q)
    i = next(e for e in h["소득분위구분"] if e["소득분위"] == income_q)
    return pd.Series(i["dataList"][: len(dates)], index=dates).astype(float)


def ecos(name):
    """한국은행 ECOS 월간 시계열 (ecos_fetch.py가 받은 파일)."""
    d = json.loads((RAW / "ecos" / f"{name}.json").read_text())

    def when(s):  # 202609 → 2026-09-01, 2026Q2 → 2026-04-01 (분기 첫 달)
        return pd.Timestamp(int(s[:4]), 3 * int(s[5]) - 2 if s[4] == "Q" else int(s[4:6]), 1)
    return pd.Series({when(r["date"]): r["value"] for r in d}).astype(float).sort_index()


def kb_supply(name):
    df = pd.read_csv(RAW / "kb" / f"{name}.csv")
    s = pd.Series(df["합계.세대수"].values, index=_ym(df["일정"].astype(str))).astype(float)
    full = pd.date_range(s.index.min(), s.index.max(), freq="MS")
    return s.groupby(level=0).sum().reindex(full, fill_value=0.0)


def trend(kw):
    df = pd.read_csv(RAW / "trends" / f"{kw}.csv", parse_dates=[0], index_col=0)
    return df.iloc[:, 0].astype(float)


def lag(s, months):
    """공개 시차: 값을 n개월 뒤 날짜로 옮긴다. (s.shift(n)은 자료 끝에서 n개가 사라져 최신 달이 더 오래된 값으로 채워짐)"""
    s = s.copy()
    s.index = s.index + pd.DateOffset(months=months)
    return s


def chg(s, n):
    return np.log(s).diff(n)


def attention(s):
    """단기 관심 급증: 최근 3개월 평균 / 직전 24개월 평균 (구글 사용 점유율 추세 제거)."""
    s = s.clip(lower=1)
    return np.log(s.rolling(3).mean() / s.rolling(24).mean())


def attention_rt(series):
    """여러 검색어를 더한 관심 급증. 구글 트렌드는 검색어마다 전체 기간 최고점을 100으로 맞춰 와서 그대로 더하면 섞는 비율이
    나중 최고점으로 정해진다. 그달까지의 최고점으로 다시 맞춰 더한다 (그때 받았으면 보였을 비율, v3.4)."""
    num = sum(100 * s.clip(lower=1).rolling(3).mean() / s.cummax() for s in series)
    den = sum(100 * s.clip(lower=1).rolling(24).mean() / s.cummax() for s in series)
    return np.log(num / den)


# 지표 메타: 키 → (설명, 주제, 속도, 출처성격, 행위자, 시장, cnn, 사용자원안)
META = {
    # 가격
    "가격_3개월모멘텀": ("서울 아파트 매매지수 3개월 변화", "가격", "동행", "가격실측", "시장전체", "매매", "", ""),
    "가격_12개월이평괴리": ("매매지수 / 12개월 이동평균 - 1 (CNN 모멘텀 대응)", "가격", "후행", "가격실측", "시장전체", "매매", "모멘텀", ""),
    "가격_선도50모멘텀": ("KB 선도아파트50 3개월 변화 (상급지 강도)", "가격", "동행", "가격실측", "시장전체", "매매", "강도", ""),
    "가격_상승구비율": ("25개 구 중 전월 대비 상승한 구 비율 (3개월 평균)", "가격", "동행", "가격실측", "시장전체", "매매", "폭", ""),
    # 중개사 설문
    "설문_매수우위": ("KB 매수우위지수", "수급심리", "동행", "설문", "매수자", "매매", "풋콜", ""),
    "설문_매수우위변화": ("매수우위지수 3개월 변화", "수급심리", "선행", "설문", "매수자", "매매", "", ""),
    "설문_거래활발": ("KB 매매거래활발지수 (거래량 대리)", "수급심리", "동행", "설문", "중개사", "매매", "변동성→거래량", ""),
    "설문_가격전망": ("KB 매매가격전망지수 (2013.4~)", "수급심리", "선행", "설문", "중개사", "매매", "", ""),
    # 전세
    "전세_수급": ("KB 전세수급지수 (높을수록 전세 부족)", "전세", "선행", "설문", "임차인", "전세", "", ""),
    "전세_가격전망": ("KB 전세가격전망지수 (2016~)", "전세", "선행", "설문", "중개사", "전세", "", ""),
    "전세_3개월모멘텀": ("서울 아파트 전세지수 3개월 변화", "전세", "선행", "가격실측", "임차인", "전세", "", ""),
    "전세_매매선호": ("매수우위지수 / 전세수급지수 (전세 대신 매수 선택, 안전자산 대응)", "전세", "동행", "설문", "매수자", "전세", "안전자산", ""),
    # 자금
    "자금_기준금리수준": ("한국은행 기준금리 수준 (부호 반대: 낮을수록 탐욕) — 사용자 원안 '기준금리'", "자금", "후행", "거시정책", "금융기관", "금융", "", "기준금리"),
    "자금_기준금리변화": ("한국은행 기준금리 6개월 변화 (부호 반대)", "자금", "선행", "거시정책", "금융기관", "금융", "", "기준금리"),
    "자금_주담대금리변화": ("예금은행 주택담보대출 금리(신규취급액) 6개월 변화 (부호 반대, 2개월 늦춤)", "자금", "선행", "거시정책", "금융기관", "금융", "", ""),
    "자금_국고채10년변화": ("국고채 10년 금리 6개월 변화 (부호 반대, 한국은행)", "자금", "선행", "금융시장", "금융기관", "금융", "", ""),
    "자금_가계신용증가": ("가계신용/명목 GDP 4분기 변화 (한국은행, 분기 끝 3개월 뒤 반영)", "자금", "후행", "거시정책", "금융기관", "금융", "", ""),
    # 가격 부담 (밸류에이션)
    "부담_PIR": ("서울 PIR (중위주택/중위소득)", "가격부담", "후행", "가격실측", "시장전체", "매매", "", ""),
    "부담_구매력역수": ("KB 주택구매력지수 서울 아파트 (부호 반대)", "가격부담", "후행", "가격실측", "시장전체", "매매", "", ""),
    "부담_전세가율역수": ("서울 아파트 전세가율 (부호 반대: 낮을수록 매매 과열)", "가격부담", "후행", "가격실측", "시장전체", "전세", "", ""),
    "설문_주택가격전망CSI": ("한국은행 소비자동향조사 주택가격전망 CSI (전국, 2013~)", "수급심리", "선행", "설문", "매수자", "매매", "", ""),
    # 관심 (구글 트렌드)
    "관심_아파트": ("구글 검색 '아파트' 단기 급증", "관심", "선행", "검색", "매수자", "매매", "", "언급수"),
    "관심_부동산": ("구글 검색 '부동산' 단기 급증", "관심", "선행", "검색", "매수자", "매매", "", "언급수"),
    "관심_집값": ("구글 검색 '집값' 단기 급증", "관심", "선행", "검색", "매수자", "매매", "", "언급수"),
    "관심_청약": ("구글 검색 '청약' 단기 급증", "관심", "선행", "검색", "매수자", "분양", "", "언급수"),
    "관심_갭투자": ("구글 검색 '갭투자' 단기 급증", "관심", "선행", "검색", "매수자", "매매", "", "언급수"),
    "관심_공포어역수": ("구글 검색 '급매'+'미분양' 단기 급증 (부호 반대)", "관심", "선행", "검색", "매도자", "매매", "", "언급수"),
    # 공급
    "공급_분양물량": ("서울 아파트 분양 세대수 12개월 합 (건설사 자신감)", "공급", "후행", "공급통계", "공급자", "분양", "", "공급량"),
    "공급_향후입주역수": ("향후 12개월 입주 예정 세대수 (부호 반대)", "공급", "선행", "공급통계", "공급자", "전세", "", "공급량"),
    # 금융시장
    "시장_건설주모멘텀": ("건설주 바스켓 6개월 수익률", "금융시장", "선행", "금융시장", "공급자", "금융", "", ""),
    "시장_건설주상대강도": ("건설주 바스켓 - KOSPI 6개월 수익률 (정크본드 대응)", "금융시장", "선행", "금융시장", "공급자", "금융", "정크본드", ""),
    "시장_KOSPI모멘텀": ("KOSPI 6개월 수익률 (자산효과)", "금융시장", "선행", "금융시장", "시장전체", "금융", "", ""),
}
META_COLS = ["설명", "주제", "속도", "출처성격", "행위자", "시장", "CNN대응", "사용자원안"]


def build():
    ind = {}
    p = kb_aligned("아파트매매지수_월간")
    ind["가격_3개월모멘텀"] = chg(p, 3)
    ind["가격_12개월이평괴리"] = p / p.rolling(12).mean() - 1
    ind["가격_선도50모멘텀"] = chg(kb_lead50(), 3)
    gu = kb_gu_panel()
    up = (gu.diff() > 0).where(gu.diff().notna())
    ind["가격_상승구비율"] = up.mean(axis=1).where(up.notna().sum(axis=1) >= 20).rolling(3).mean()

    buy = kb_survey("매수우위_월간", "매수우위지수")
    ind["설문_매수우위"] = buy
    ind["설문_매수우위변화"] = buy.diff(3)
    ind["설문_거래활발"] = kb_survey("매매거래활발_월간", "매매거래지수")
    ind["설문_가격전망"] = kb_survey("매매가격전망_월간", "매매상승하락전망지수")

    js = kb_survey("전세수급_월간", "전세수급지수")
    ind["전세_수급"] = js
    ind["전세_가격전망"] = kb_survey("전세가격전망_월간", "전세상승하락전망지수")
    ind["전세_3개월모멘텀"] = chg(kb_aligned("아파트전세지수_월간"), 3)
    ind["전세_매매선호"] = buy / js

    # 자금: 한국은행 ECOS 원자료 (v3.2부터. 공개 시차는 timing.py와 아래 shift)
    base = ecos("기준금리")
    ind["자금_기준금리수준"] = -base
    ind["자금_기준금리변화"] = -base.diff(6)
    ind["자금_국고채10년변화"] = -ecos("국고채10년").diff(6)
    ind["자금_주담대금리변화"] = lag(-ecos("주담대금리").diff(6), 2)  # 신규취급액 금리는 다음 달 말 공개 → 20일 기준 2개월 늦춤
    hh = ecos("가계신용") / ecos("명목GDP").rolling(4).sum() * 100  # 가계신용 / 최근 4분기 명목 GDP (%)
    hh_m = hh.diff(4).resample("MS").ffill()
    hh_m.index = hh_m.index + pd.DateOffset(months=5)  # 분기 끝 + 3개월 (가계신용 8월 하순, 명목 GDP 9월 초 공개 → 2분기는 9월부터)
    ind["자금_가계신용증가"] = hh_m
    ind["설문_주택가격전망CSI"] = ecos("주택가격전망CSI")  # 보조 지표 (2013~), 시차는 timing.py
    rate, hai = kb_hai()

    ind["부담_PIR"] = lag(kb_pir(), 3)  # 소득 통계 발표 시차
    ind["부담_구매력역수"] = lag(-hai, 3)
    ind["부담_전세가율역수"] = -kb_aligned("전세가율_아파트")

    for k, kw in [("관심_아파트", "아파트"), ("관심_부동산", "부동산"), ("관심_집값", "집값"),
                  ("관심_청약", "청약"), ("관심_갭투자", "갭투자")]:
        ind[k] = attention(trend(kw))
    ind["관심_공포어역수"] = -attention_rt([trend("급매"), trend("미분양")])

    if (RAW / "kb" / "분양물량.csv").exists() and (RAW / "kb" / "입주물량.csv").exists():  # v3.1에서는 쓰지 않음 (실시간 계산 불가)
        sale = kb_supply("분양물량")
        ind["공급_분양물량"] = np.log1p(sale.rolling(12).sum())
        movein = kb_supply("입주물량")
        ind["공급_향후입주역수"] = -np.log1p(movein[::-1].rolling(12).sum()[::-1].shift(-1))

    st = pd.read_csv(RAW / "market" / "stocks_monthly.csv", index_col=0, parse_dates=True)
    names = [c for c in st.columns if c != "KOSPI"]
    basket = np.log(st[names]).diff().mean(axis=1, skipna=True)  # 동일가중 월수익률
    ind["시장_건설주모멘텀"] = basket.rolling(6).sum()
    kospi6 = np.log(st["KOSPI"]).diff(6)
    ind["시장_건설주상대강도"] = basket.rolling(6).sum() - kospi6
    ind["시장_KOSPI모멘텀"] = kospi6

    import timing
    raw = pd.DataFrame(ind).sort_index()
    label = p.last_valid_index()  # 기준월 = KB 매매지수 최신 달
    # 발표가 늦는 지표는 최근 값으로 최대 3개월 이어 붙임 (실시간 운영과 동일)
    df = raw.ffill(limit=3)
    df = df[df.index >= "2000-01-01"]
    df.index.name = "date"
    extra = ROOT / "data" / "indicators_extra.csv"
    if extra.exists():  # API 키로 받은 지표 (extra_indicators.py)
        ex0 = pd.read_csv(extra, index_col=0, parse_dates=True)
        raw = raw.join(ex0, how="outer")
        df = df.join(ex0.ffill(limit=3).reindex(df.index))
    # 이어 붙이기 전에 열마다 최신 값이 기준월에 맞게 왔는지 남긴다 (이어 붙인 뒤엔 빈칸이 안 보여 점검이 못 잡음)
    tmp = ROOT / "data" / "freshness.json.tmp"
    tmp.write_text(json.dumps({"label": f"{label:%Y-%m}", "cols": timing.freshness(raw, label)}, ensure_ascii=False, indent=1))
    tmp.replace(ROOT / "data" / "freshness.json")
    df = timing.apply(df)  # 20일 갱신 시점에 아직 공개 전인 지표는 1개월 늦춤
    df = timing.fill_slow(df)  # 분기 자료는 다음 발표까지 이어 씀
    df["__price"] = p.reindex(df.index)  # 타깃용 서울 아파트 매매지수
    return df


if __name__ == "__main__":
    df = build()
    df.to_csv(ROOT / "data" / "indicators.csv")
    from extra_indicators import META_EXTRA
    allmeta = {**META, **{k: v for k, v in META_EXTRA.items() if k in df.columns}}
    meta = pd.DataFrame.from_dict(allmeta, orient="index", columns=META_COLS)
    meta.index.name = "지표"
    meta.to_csv(ROOT / "data" / "indicator_meta.csv")
    cov = pd.DataFrame({"start": df.apply(lambda s: s.first_valid_index()),
                        "end": df.apply(lambda s: s.last_valid_index()),
                        "n": df.notna().sum()})
    print(cov.to_string())
