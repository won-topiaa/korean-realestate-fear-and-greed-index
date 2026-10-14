# 서울 아파트 공포탐욕지수

서울 아파트 시장의 심리를 0~100으로 나타내는 지수(v3.2)와, 5대 권역·25개 구별로 볼 수 있는 지도.
매달 20일 GitHub Actions가 자료를 새로 받아 다시 계산하고 GitHub Pages에 배포한다.

- 지도: `site/index.html` (Pages 첫 화면)
- 보고서: `site/report/index.html`
- 계산 방식과 갱신 절차: [README_자동갱신.md](README_자동갱신.md)

## 처음 한 번 설정
1. **Settings → Secrets and variables → Actions**에 저장소 비밀값 두 개를 추가한다.
   - `DATA_GO_KR_KEY`: 공공데이터포털 인증키 (Encoding 키)
   - `REB_KEY`: 한국부동산원 R-ONE 인증키
2. **Settings → Pages → Build and deployment → Source**를 `GitHub Actions`로 바꾼다.
3. **Actions → 월간 자동 갱신 → Run workflow**로 한 번 실행해 본다.

## 로컬에서 돌리기
```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
# .env 에 DATA_GO_KR_KEY=..., REB_KEY=... 를 넣고
./update.sh --no-publish
```

## 자료 출처와 이용 조건
- 계산에 쓰는 자료: KB부동산 데이터허브, 한국부동산원 R-ONE, 국토교통부 실거래가(공공데이터포털), 청약홈, 한국은행 ECOS, 네이버 금융, 구글 트렌드.
- 각 원자료의 저작권과 이용 조건은 해당 기관에 있다.
- 이 저장소에는 공공데이터(국토부 실거래, 한국부동산원, 청약홈, 한국은행)와 계산 결과만 올린다. KB부동산·네이버 금융 원자료와 그 원값이 담긴 지표 표는 올리지 않고, Actions가 매달 새로 받아 캐시에만 보관한다.
- 공개 사이트와 보고서에는 직접 계산한 점수와 실거래 반복매매지수만 싣는다.
