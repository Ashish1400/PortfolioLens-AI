from pathlib import Path
import hashlib
import json
import platform
import sqlite3
from importlib.metadata import version
import numpy as np
import pandas as pd
from .data import generate, clean_frames
from .model import train_model


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, default=lambda x: x.item() if hasattr(x, "item") else str(x),
                               allow_nan=False), encoding="utf-8")


def records(frame):
    # to_json turns undefined ratios into JSON null instead of invalid JSON NaN.
    return json.loads(frame.to_json(orient="records", double_precision=8))


def build(root: Path, n_loans: int = 4000, seed: int = 42):
    manifest = generate(root, n_loans, seed)
    output = root / "artifacts"
    output.mkdir(exist_ok=True)
    loans = pd.read_csv(root / "data/raw/loans.csv")
    raw = pd.read_csv(root / "data/raw/snapshots.csv")
    fact, rejected, quality = clean_frames(loans, raw)
    rejected.to_csv(output / "quarantine.csv", index=False)
    db_path = output / "portfolio.sqlite"
    # Rebuild only the project's own generated database; no external DB connection.
    if db_path.exists():
        db_path.unlink()
    with sqlite3.connect(db_path) as con:
        loans.to_sql("dim_loan", con, index=False)
        fact.to_sql("fact_loan_snapshot", con, index=False)
        con.execute("CREATE UNIQUE INDEX loan_pk ON dim_loan(loan_id)")
        con.execute("CREATE UNIQUE INDEX snapshot_pk ON fact_loan_snapshot(loan_id, snapshot_month)")
        con.executescript((root / "sql/marts.sql").read_text())
        panel = pd.read_sql_query("SELECT * FROM loan_panel", con)
        marts = {name: pd.read_sql_query(f"SELECT * FROM mart_{name}", con)
                 for name in ["monthly", "segment", "vintage", "roll_rates"]}
    model_card, queue = train_model(panel)
    for name, mart in marts.items():
        mart.to_csv(output / f"mart_{name}.csv", index=False)
    loans.to_csv(output / "dim_loan.csv", index=False)
    fact.to_csv(output / "fact_loan_snapshot.csv", index=False)
    queue.to_csv(output / "risk_queue.csv", index=False)
    latest_month = marts["monthly"].snapshot_month.max()
    latest_regions = marts["segment"].query("snapshot_month == @latest_month").groupby("region", as_index=False).agg(
        ending_balance=("ending_balance", "sum"), dpd30_balance=("dpd30_balance", "sum"), observed_loans=("observed_loans", "sum"))
    latest_regions["dpd30_rate"] = latest_regions.dpd30_balance / latest_regions.ending_balance
    monthly = marts["monthly"].sort_values("snapshot_month")
    facts = []
    last, prev = monthly.iloc[-1], monthly.iloc[-2]
    delta = float((last.dpd30_rate - prev.dpd30_rate) * 10000)
    facts.append({"id": "F-PORTFOLIO", "kind": "portfolio", "text":
        f"Accepted synthetic portfolio at {latest_month}: principal ${last.ending_balance:,.2f}; "
        f"active loans {int(last.active_loans):,}; balance-weighted 30+ DPD {last.dpd30_rate:.2%}; "
        f"60+ DPD {last.dpd60_rate:.2%}. 30+ DPD changed by {delta:+.1f} basis points versus {prev.snapshot_month}."})
    for row in latest_regions.sort_values("dpd30_rate", ascending=False).itertuples():
        facts.append({"id": "F-REGION-" + row.region.upper(), "kind": "segments", "text":
            f"At {latest_month}, {row.region}: balance ${row.ending_balance:,.2f}; "
            f"30+ DPD balance rate {row.dpd30_rate:.2%}; observed loans {row.observed_loans:,}."})
    facts.append({"id": "F-QUALITY", "kind": "quality", "text":
        f"Raw rows {quality['raw_rows']:,}; duplicate rows removed {quality['duplicates_removed']}; "
        f"quarantined unique rows {quality['quarantined_rows']}; accepted rows {quality['accepted_rows']:,}. " + quality["scope_note"]})
    tm = model_card["test"]
    facts.append({"id": "F-MODEL", "kind": "model", "text":
        f"Selected {model_card['selected_model']} using validation average precision. "
        f"Loan-disjoint chronological test: {tm['rows']} loan-month rows, {tm['events']} events; "
        f"ROC-AUC {tm['roc_auc']:.4f}; average precision {tm['average_precision']:.4f}; "
        f"Brier score {tm['brier_score']:.4f}; top-decile lift {tm['lift_at_top_10pct']:.2f}x. "
        "This is synthetic-only validation; September 2026 scoring has no observed next-month labels."})
    docs = json.loads((root / "docs/knowledge.json").read_text())
    report = {"title": "PortfolioLens AI", "synthetic": True, "as_of": latest_month,
              "monthly": records(monthly), "regions": records(latest_regions),
              "vintage": records(marts["vintage"]), "roll_rates": records(marts["roll_rates"]),
              "risk_queue": records(queue.head(25)), "quality": quality,
              "model": model_card, "evidence": facts + docs}
    manifest["runtime"] = {"python": platform.python_version(), **{n: version(n) for n in ["numpy", "pandas", "scikit-learn"]}}
    manifest["raw_sha256"] = {n: hashlib.sha256((root / "data/raw" / n).read_bytes()).hexdigest()
                               for n in ["loans.csv", "snapshots.csv"]}
    save_json(output / "data_manifest.json", manifest)
    save_json(output / "model_card.json", model_card)
    save_json(output / "quality_report.json", quality)
    save_json(output / "dashboard.json", report)
    return report
