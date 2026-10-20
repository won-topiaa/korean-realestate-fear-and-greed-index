"""template.html + results_zone/map_data.json → index.html (서울 지도). 서울 밖 지역 페이지도 같은 템플릿을 쓴다 (region_build.py)."""
from pathlib import Path

here = Path(__file__).parent
SEOUL = {
    "__TITLE__": "서울 아파트 공포탐욕지도",
    "__TOP__": "서울",
    "__NIND__": "34",
    "__HOWTO__": "권역이나 구를 누르면 그곳의 지수를, 아무 데도 누르지 않으면 서울 전체 지수를 보여줘요. 지도 위 버튼으로 5대 권역과 25개 구를 바꿔 보고, 아래 슬라이더로 2006년부터 달마다 볼 수 있어요.",
    "__FOOT_ACC__": '<p><b style="color:var(--ink-2)">정확도</b> · 권역·구 지수는 지금 어디가 더 뜨거운지를 보는 데 쓰세요. 점수 차이가 5점 미만이면 의미 있는 차이로 보기 어렵고, 서남권처럼 서울 지수가 더 잘 맞은 곳도 있어요. 25개 구 평균으로 보면 구 지수, 권역 지수, 서울 지수가 그 구의 이후 가격을 맞힌 정도가 거의 같고, 구 점수의 높낮이로 어느 구가 더 오를지 맞히는 힘은 약해요. 구끼리 비교할 때는 \'서울 안 상대 강도\'(신고가 비중의 25개 구 안 순위)를 함께 보세요. 이 순위는 공포탐욕 점수와 따로 실시간 기록으로 검증해요. 권역이나 구를 누르면 해당 수치가 나와요.</p>',
    "__MAP_SRC__": "지도는 통계청 2013년 구 경계(southkorea/seoul-maps)와 Natural Earth 한강 중심선이에요.",
}


def render(fill, data):
    html = (here / "template.html").read_text()
    for k, v in fill.items():
        html = html.replace(k, v)
    return html.replace("__DATA__", data)


if __name__ == "__main__":
    (here / "index.html").write_text(render(SEOUL, (here.parent / "results_zone" / "map_data.json").read_text()))
