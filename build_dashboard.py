"""Build the static dashboard (index.html) from results.json."""
import json
from pathlib import Path

here = Path(__file__).parent
data = json.loads((here / "results.json").read_text(encoding="utf-8"))
payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
html = (here / "dashboard_template.html").read_text(encoding="utf-8")
(here / "index.html").write_text(html.replace("/*__DATA__*/", payload), encoding="utf-8")
print("index.html written:", (here / "index.html").stat().st_size, "bytes")
