"""Run the pipeline for every STORE folder and write results.json + daily CSVs."""
import json
import sys
from pathlib import Path

from analysis import run_store

data_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
out_dir = Path(sys.argv[2] if len(sys.argv) > 2 else ".")
out_dir.mkdir(exist_ok=True)

results = {}
for folder in sorted(p for p in data_dir.glob("STORE*") if p.is_dir()):
    r = run_store(folder)
    daily = r.pop("daily")
    daily.to_csv(out_dir / f"{folder.name}_daily_revenue.csv", index=False)
    r["daily_revenue"] = [
        {"date": d.isoformat(), "revenue": float(v)}
        for d, v in zip(daily["date"], daily["revenue"])
    ]
    results[folder.name] = r
    print(folder.name, "ok")

(out_dir / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
