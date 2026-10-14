"""template.html + results_zone/map_data.json → index.html"""
from pathlib import Path
here = Path(__file__).parent
data = (here.parent / "results_zone" / "map_data.json").read_text()
(here / "index.html").write_text((here / "template.html").read_text().replace("__DATA__", data))
