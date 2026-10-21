"""Build the dashboard (index.html) from results.json.

Usage: python build_dashboard.py [--api https://my-server] [--live https://my-server]
  --api   base URL of the API server (empty = same origin as the page)
  --live  link shown on the static copy when the server is unreachable
"""
import argparse
import json
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--api", default="")
ap.add_argument("--live", default="")
args = ap.parse_args()

here = Path(__file__).parent
data = json.loads((here / "results.json").read_text(encoding="utf-8"))
payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
html = (here / "dashboard_template.html").read_text(encoding="utf-8")
html = html.replace("/*__DATA__*/", payload).replace("/*__API__*/", args.api).replace("/*__LIVE__*/", args.live)
(here / "index.html").write_text(html, encoding="utf-8")
print("index.html written:", (here / "index.html").stat().st_size, "bytes")
