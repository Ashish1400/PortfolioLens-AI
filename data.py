"""Reproducible principal-only simulation and explicit row quarantine."""
from pathlib import Path
import numpy as np
import pandas as pd

MONEY = ["opening_balance", "funding", "principal_paid", "chargeoff", "ending_balance"]
BUCKETS = ["Current", "30-59", "60-89", "90-119", "120+"]


def generate(root: Path, n_loans: int = 4000, seed: int = 42) -> dict:
    if n_loans < 200:
        raise ValueError("Use at least 200 loans for the three evaluation cohorts.")
    rng = np.random.default_rng(seed)
    months = pd.date_range("2024-08-01", "2026-09-01", freq="MS")
    rows, loans = [], []
    for i in range(n_loans):
        loan_id = f"SYN-{i:06d}"
        band = str(rng.choice(["A", "B", "C"], p=[.50, .33, .17]))
        region = str(rng.choice(["Northeast", "Midwest", "South", "West"]))
        product = str(rng.choice(["Personal", "Auto"], p=[.58, .42]))
        original = int(rng.integers(5000, 40001))
        term = int(rng.choice([36, 48, 60]))
        orig_index = int(rng.integers(0, 21))
        dti = float(np.clip(rng.normal(.25 + .10 * ["A", "B", "C"].index(band), .07), .05, .70))
        cohort = "train" if i % 10 < 7 else "validation" if i % 10 == 7 else "test"
        loans.append([loan_id, product, band, region, str(months[orig_index].date()),
                      original, term, round(dti, 4), cohort])
        balance, dpd, previous_ratio = 0., 0, 1.
        for m in range(orig_index, len(months)):
            if m > orig_index and balance == 0:
                break
            opening = balance
            funding = float(original) if m == orig_index else 0.
            available = opening + funding
            stress = .11 if months[m] >= pd.Timestamp("2026-04-01") and region == "South" else 0.
            late_prob = np.clip(.045 + .07 * ["A", "B", "C"].index(band) + .27 * dti
                                + stress + .18 * (previous_ratio < .75), .03, .85)
            late = rng.random() < late_prob
            if late:
                dpd = min(120, dpd + 30)
                ratio = float(rng.uniform(.0, .65))
            else:
                dpd = max(0, dpd - int(rng.choice([30, 60], p=[.65, .35])))
                ratio = float(rng.uniform(.95, 1.15))
            paid = round(min(available, original / term * ratio), 2)
            chargeoff = round(available - paid, 2) if dpd == 120 else 0.
            balance = round(available - paid - chargeoff, 2)
            utilization = round(float(np.clip(rng.normal(.20 + .80 * dti + .18 * late, .12), 0, 1)), 4)
            rows.append([loan_id, str(months[m].date()), opening, funding, paid, chargeoff,
                         balance, dpd, round(ratio, 4), utilization, m - orig_index,
                         "Charged off" if chargeoff else "Paid off" if balance == 0 else "Active"])
            previous_ratio = ratio
    dim = pd.DataFrame(loans, columns=["loan_id", "product", "risk_band", "region", "origination_month",
                        "original_principal", "term_months", "debt_to_income", "cohort"])
    fact = pd.DataFrame(rows, columns=["loan_id", "snapshot_month", *MONEY, "days_past_due",
                                      "payment_ratio", "utilization", "months_on_book", "status"])
    # Deliberate independent defects, chosen once and documented in the manifest.
    defect_ids = rng.choice(len(fact), 36, replace=False)
    fact.loc[defect_ids[:12], "ending_balance"] = np.nan
    fact.loc[defect_ids[12:24], "ending_balance"] += 123.45
    fact.loc[defect_ids[24:], "principal_paid"] = -99.
    duplicates = fact.sample(24, random_state=seed).copy()
    fact = pd.concat([fact, duplicates], ignore_index=True)
    fact["ingestion_order"] = np.arange(len(fact))
    target = root / "data" / "raw"
    target.mkdir(parents=True, exist_ok=True)
    dim.to_csv(target / "loans.csv", index=False)
    fact.to_csv(target / "snapshots.csv", index=False)
    return {"seed": seed, "loan_count": n_loans, "raw_snapshot_rows": len(fact),
            "first_month": "2024-08-01", "last_month": "2026-09-01", "synthetic": True,
            "injected_defects": {"duplicate_rows": 24, "missing_balance_rows": 12,
                                 "ledger_mismatch_rows": 12, "negative_payment_rows": 12}}


def clean_frames(loans: pd.DataFrame, raw: pd.DataFrame):
    if loans.loan_id.duplicated().any() or loans.isna().any().any():
        raise ValueError("Loan dimension must have unique IDs and no missing values.")
    data = raw.sort_values("ingestion_order").drop_duplicates(["loan_id", "snapshot_month"], keep="last").copy()
    removed = len(raw) - len(data)
    error = (data.opening_balance + data.funding - data.principal_paid - data.chargeoff - data.ending_balance).abs()
    missing = data.isna().any(axis=1)
    negative = (data[MONEY] < 0).any(axis=1)
    orphan = ~data.loan_id.isin(loans.loan_id)
    invalid_dpd = ~data.days_past_due.isin([0, 30, 60, 90, 120])
    bad = missing | negative | (error > .03) | orphan | invalid_dpd
    rejected = data[bad].copy()
    reasons = pd.Series("", index=data.index)
    for mask, name in [(missing, "missing_field;"), (negative, "negative_money;"),
                       (error > .03, "ledger_mismatch;"), (orphan, "orphan_loan;"),
                       (invalid_dpd, "invalid_dpd;")]:
        reasons.loc[mask] += name
    rejected["rejection_reason"] = reasons.loc[bad]
    accepted = data[~bad].drop(columns="ingestion_order").copy()
    accepted["dpd_bucket"] = pd.Categorical(
        accepted.days_past_due.map({0: "Current", 30: "30-59", 60: "60-89", 90: "90-119", 120: "120+"}),
        categories=BUCKETS, ordered=True).astype(str)
    quality = {"raw_rows": len(raw), "duplicates_removed": removed, "quarantined_rows": int(bad.sum()),
               "accepted_rows": len(accepted), "ledger_tolerance_dollars": .03,
               "missing_field_rows": int(missing.sum()), "negative_money_rows": int(negative.sum()),
               "ledger_mismatch_rows": int((error > .03).sum()), "orphan_rows": int(orphan.sum()),
               "invalid_dpd_rows": int(invalid_dpd.sum()),
               "scope_note": "Metrics use accepted rows. Rejected rows can change denominators; resolve exceptions before operational use."}
    return accepted, rejected, quality
