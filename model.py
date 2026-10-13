"""Loan-disjoint, chronological model development with validation-only selection."""
import math
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from threadpoolctl import threadpool_limits

NUMERIC = ["days_past_due", "payment_ratio", "utilization", "debt_to_income", "months_on_book", "balance_ratio"]
CATEGORICAL = ["risk_band", "product", "region"]
FEATURES = NUMERIC + CATEGORICAL


def make_features(panel):
    data = panel.sort_values(["loan_id", "snapshot_month"]).copy()
    data["balance_ratio"] = data.ending_balance / data.original_principal
    group = data.groupby("loan_id", sort=False)
    data["next_dpd"] = group.days_past_due.shift(-1)
    data["label_month"] = group.snapshot_month.shift(-1)
    current_date = pd.to_datetime(data.snapshot_month)
    next_date = pd.to_datetime(data.label_month)
    contiguous = next_date.dt.to_period("M") == (current_date.dt.to_period("M") + 1)
    eligible = (data.ending_balance > 0) & (data.days_past_due < 60)
    labeled = data[contiguous & eligible].copy()
    labeled["target"] = (labeled.next_dpd >= 60).astype(int)
    return data, labeled


def split_frames(data):
    train = data[(data.cohort == "train") & (data.label_month <= "2026-04-01")]
    validation = data[(data.cohort == "validation") & data.snapshot_month.between("2026-04-01", "2026-05-01")]
    test = data[(data.cohort == "test") & data.snapshot_month.between("2026-06-01", "2026-08-01")]
    for split in [train, validation, test]:
        if split.empty or split.target.nunique() != 2:
            raise ValueError("A split is empty or contains only one target class. Increase --loans.")
    assert set(train.loan_id).isdisjoint(validation.loan_id)
    assert set(train.loan_id).isdisjoint(test.loan_id)
    assert set(validation.loan_id).isdisjoint(test.loan_id)
    assert train.label_month.max() <= validation.snapshot_month.min()
    assert validation.label_month.max() <= test.snapshot_month.min()
    return train, validation, test


def metrics(y, probability):
    y, probability = np.asarray(y), np.asarray(probability)
    n_top = max(1, math.ceil(len(y) * .1))
    top = np.argsort(-probability, kind="stable")[:n_top]
    prevalence = float(y.mean())
    precision = float(y[top].mean())
    return {"rows": len(y), "events": int(y.sum()), "event_rate": prevalence,
            "roc_auc": float(roc_auc_score(y, probability)),
            "average_precision": float(average_precision_score(y, probability)),
            "brier_score": float(brier_score_loss(y, probability)),
            "precision_at_top_10pct": precision,
            "recall_at_top_10pct": float(y[top].sum() / y.sum()),
            "lift_at_top_10pct": precision / prevalence if prevalence else None}


def train_model(panel):
    all_features, labeled = make_features(panel)
    train, validation, test = split_frames(labeled)
    preprocessor = ColumnTransformer([
        ("numeric", StandardScaler(), NUMERIC),
        ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL)
    ])
    candidates = {
        "logistic_regression": Pipeline([("preprocess", preprocessor),
                         ("estimator", LogisticRegression(max_iter=700, C=1.0, random_state=42))]),
        "hist_gradient_boosting": Pipeline([("preprocess", ColumnTransformer([
            ("numeric", StandardScaler(), NUMERIC),
            ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL)])),
            ("estimator", HistGradientBoostingClassifier(max_iter=90, max_leaf_nodes=15,
                            l2_regularization=5.0, learning_rate=.07, random_state=42))])
    }
    validation_metrics = {}
    with threadpool_limits(limits=2):
        for name, model in candidates.items():
            model.fit(train[FEATURES], train.target)
            validation_metrics[name] = metrics(validation.target, model.predict_proba(validation[FEATURES])[:, 1])
        champion_name = max(validation_metrics, key=lambda n: validation_metrics[n]["average_precision"])
        champion = candidates[champion_name]
        test_probability = champion.predict_proba(test[FEATURES])[:, 1]
        test_metrics = metrics(test.target, test_probability)
        # A constant-probability baseline is calibrated to TRAIN prevalence, never test prevalence.
        baselines = {
            "train_prevalence": metrics(test.target, np.full(len(test), train.target.mean())),
            "current_dpd_rule": metrics(test.target, np.where(test.days_past_due >= 30, .3, .03))
        }
        latest = all_features[(all_features.snapshot_month == all_features.snapshot_month.max()) &
                              (all_features.ending_balance > 0) & (all_features.days_past_due < 60)].copy()
        latest["risk_probability"] = champion.predict_proba(latest[FEATURES])[:, 1]
    queue = latest.sort_values(["risk_probability", "loan_id"], ascending=[False, True])
    queue = queue[["loan_id", "snapshot_month", "region", "product", "risk_band", "ending_balance",
                   "days_past_due", "payment_ratio", "utilization", "risk_probability"]]
    bins = pd.cut(test_probability, np.linspace(0, 1, 11), include_lowest=True)
    calibration = pd.DataFrame({"bin": bins, "probability": test_probability, "target": test.target.to_numpy()})
    cal = calibration.groupby("bin", observed=True).agg(count=("target", "size"),
             predicted=("probability", "mean"), observed=("target", "mean")).reset_index()
    cal["bin"] = cal["bin"].astype(str)
    segments = []
    scored = test.copy()
    scored["probability"] = test_probability
    for region, group in scored.groupby("region"):
        if group.target.nunique() == 2:
            segments.append({"region": region, **metrics(group.target, group.probability)})
    split_details = {}
    for name, frame in [("train", train), ("validation", validation), ("test", test)]:
        split_details[name] = {"rows": len(frame), "loans": frame.loan_id.nunique(),
            "feature_start": frame.snapshot_month.min(), "feature_end": frame.snapshot_month.max(),
            "label_start": frame.label_month.min(), "label_end": frame.label_month.max()}
    card = {"synthetic_only": True, "target": "Reach 60+ DPD next month among loans currently below 60 DPD with positive principal",
            "selected_model": champion_name, "selection_metric": "validation average precision",
            "feature_names": FEATURES, "splits": split_details,
            "validation": validation_metrics, "test": test_metrics, "baselines": baselines,
            "calibration": cal.to_dict("records"), "segment_diagnostics": segments,
            "limitations": ["Simulation performance is not evidence of real-world credit model validity.",
                "Repeated loan-month observations are dependent; confidence intervals are not estimated.",
                "A ranking demonstration, not a lending, pricing, or collection decision engine.",
                "No protected-attribute fairness audit or real-data external validation has been performed.",
                "The latest month has no next-month labels and is scored but never evaluated."]}
    return card, queue
