"""공공데이터포털 키로 쓸 수 있는 API 확인 (키는 .env에서 읽고 출력하지 않음)."""
import subprocess
from pathlib import Path

KEY = dict(l.split("=", 1) for l in (Path(__file__).parent / ".env").read_text().split()).get("DATA_GO_KR_KEY")

CANDIDATES = {
    "국토부 아파트 매매 실거래": "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade?serviceKey={k}&LAWD_CD=11680&DEAL_YMD=202409&numOfRows=5&pageNo=1",
    "국토부 아파트 매매 실거래 상세": "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev?serviceKey={k}&LAWD_CD=11680&DEAL_YMD=202409&numOfRows=5&pageNo=1",
    "국토부 연립다세대 매매 실거래": "https://apis.data.go.kr/1613000/RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade?serviceKey={k}&LAWD_CD=11680&DEAL_YMD=202409&numOfRows=5&pageNo=1",
    "국토부 아파트 전월세 실거래": "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent?serviceKey={k}&LAWD_CD=11680&DEAL_YMD=202409&numOfRows=5&pageNo=1",
    "청약홈 APT 분양정보": "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail?page=1&perPage=3&serviceKey={k}",
    "청약홈 APT 경쟁률": "https://api.odcloud.kr/api/ApplyhomeInfoCmpetRtSvc/v1/getAPTLttotPblancCmpet?page=1&perPage=3&serviceKey={k}",
    "청약홈 APT 무순위 경쟁률": "https://api.odcloud.kr/api/ApplyhomeInfoCmpetRtSvc/v1/getRemndrLttotPblancCmpet?page=1&perPage=3&serviceKey={k}",
    "청약홈 청약 신청·당첨자 통계": "https://api.odcloud.kr/api/ApplyhomeStatSvc/v1/getAPTReqstAreaStat?page=1&perPage=3&serviceKey={k}",
}

for name, url in CANDIDATES.items():
    out = subprocess.run(["curl", "-sS", "--http1.1", "-m", "40", url.format(k=KEY)], capture_output=True, text=True)
    body = (out.stdout or out.stderr).replace(KEY, "***")
    print(f"== {name}\n{body[:420]}\n")
