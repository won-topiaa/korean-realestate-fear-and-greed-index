"""template.html + results_v2/report_data.json → index.html  (v1은 index_v1.html에 보관)"""
from pathlib import Path
here = Path(__file__).parent
data = (here.parent / "results_v2" / "report_data_v3.json").read_text()
(here / "index.html").write_text((here / "template.html").read_text().replace("__DATA__", data))
