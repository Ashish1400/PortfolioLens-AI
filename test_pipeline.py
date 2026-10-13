import json
from pathlib import Path
import sqlite3
import unittest
import numpy as np
import pandas as pd
from portfoliolens.data import clean_frames
from portfoliolens.model import FEATURES, make_features, split_frames

ROOT = Path(__file__).resolve().parents[1]


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / "artifacts/portfolio.sqlite").exists():
            raise RuntimeError("Run python -m portfoliolens build before running tests.")
        with sqlite3.connect(ROOT / "artifacts/portfolio.sqlite") as con:
            cls.panel = pd.read_sql_query("SELECT * FROM loan_panel", con)
            cls.monthly = pd.read_sql_query("SELECT * FROM mart_monthly", con)
            cls.roll = pd.read_sql_query("SELECT * FROM mart_roll_rates", con)
        cls.report = json.loads((ROOT / "artifacts/dashboard.json").read_text())

    def test_principal_ledger_reconciles(self):
        d = self.panel
        residual = d.opening_balance + d.funding - d.principal_paid - d.chargeoff - d.ending_balance
        self.assertLess(float(residual.abs().max()), .03)

    def test_monthly_rate_uses_balance_denominator(self):
        last = self.panel.query("snapshot_month == '2026-09-01'")
        expected = last.loc[last.days_past_due >= 30, "ending_balance"].sum() / last.ending_balance.sum()
        actual = self.monthly.query("snapshot_month == '2026-09-01'").dpd30_rate.iloc[0]
        self.assertAlmostEqual(expected, actual, places=10)

    def test_grain_and_nonnegative_money(self):
        d = self.panel
        self.assertFalse(d.duplicated(["loan_id", "snapshot_month"]).any())
        self.assertTrue((d[["opening_balance", "funding", "principal_paid", "chargeoff", "ending_balance"]] >= 0).all().all())

    def test_defects_accounted_for_exactly(self):
        q = self.report["quality"]
        self.assertEqual(q["duplicates_removed"], 24)
        self.assertEqual(q["quarantined_rows"], 36)
        self.assertEqual(q["raw_rows"], q["accepted_rows"] + q["quarantined_rows"] + q["duplicates_removed"])

    def test_latest_duplicate_version_wins(self):
        loans = pd.DataFrame({"loan_id": ["X"]})
        base = {"loan_id":"X", "snapshot_month":"2026-09-01", "opening_balance":100.,
            "funding":0., "principal_paid":10., "chargeoff":0., "ending_balance":90., "days_past_due":0}
        raw = pd.DataFrame([{**base, "ending_balance":85., "ingestion_order":0},
                            {**base, "ingestion_order":1}])
        accepted, rejected, q = clean_frames(loans, raw)
        self.assertEqual(accepted.ending_balance.iloc[0], 90.)
        self.assertTrue(rejected.empty)
        self.assertEqual(q["duplicates_removed"], 1)

    def test_roll_rates_sum_to_one(self):
        sums = self.roll.groupby(["snapshot_month", "from_bucket"]).count_roll_rate.sum()
        np.testing.assert_allclose(sums, 1., atol=1e-10)

    def test_no_labels_across_missing_months(self):
        panel = self.panel[self.panel.loan_id == self.panel.loan_id.iloc[0]].copy()
        if len(panel) < 3:
            self.skipTest("Selected loan has too few snapshots.")
        months = sorted(panel.snapshot_month.unique())
        panel = panel[panel.snapshot_month != months[1]]
        _, labeled = make_features(panel)
        self.assertNotIn(months[0], set(labeled.snapshot_month))

    def test_holdout_is_loan_disjoint_and_chronological(self):
        _, labeled = make_features(self.panel)
        train, validation, test = split_frames(labeled)
        self.assertFalse(set(train.loan_id) & set(test.loan_id))
        self.assertFalse(set(train.loan_id) & set(validation.loan_id))
        self.assertFalse(set(validation.loan_id) & set(test.loan_id))
        self.assertLessEqual(train.label_month.max(), validation.snapshot_month.min())
        self.assertLessEqual(validation.label_month.max(), test.snapshot_month.min())

    def test_target_does_not_include_already_delinquent_or_future_labels(self):
        _, labeled = make_features(self.panel)
        self.assertTrue((labeled.days_past_due < 60).all())
        self.assertNotIn("2026-09-01", set(labeled.snapshot_month))
        self.assertFalse({"target", "next_dpd", "label_month", "loan_id", "cohort"} & set(FEATURES))

    def test_balances_match_across_consecutive_snapshots(self):
        d = self.panel.sort_values(["loan_id", "snapshot_month"]).copy()
        prev_month = d.groupby("loan_id").snapshot_month.shift()
        prev_balance = d.groupby("loan_id").ending_balance.shift()
        contiguous = pd.to_datetime(d.snapshot_month).dt.to_period("M") == (pd.to_datetime(prev_month).dt.to_period("M") + 1)
        self.assertLess(float((d.loc[contiguous, "opening_balance"] - prev_balance[contiguous]).abs().max()), .03)


if __name__ == "__main__":
    unittest.main()
