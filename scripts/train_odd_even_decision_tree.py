#!/usr/bin/env python3
"""
Train a simple decision tree for MSport VFL **Odd/Even** (total goals parity).

Uses gold view `v_results_odd_even_ready`:
  - Training set: rows with Odd/Even prematch odds (same event_id).
  - Label: total_goals_odd (1 = Odd, 0 = Even) — MSport settlement.

Walk-forward: train on seasons with vflm_num < cutoff, test on >= cutoff.

Outputs: metrics JSON, joblib model, feature importance.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db  # noqa: E402

OUT = EMPIRE / "models" / "odd_even"
OUT.mkdir(parents=True, exist_ok=True)


def load_frame(require_odds: bool = True) -> pd.DataFrame:
    sql = """
    SELECT season_name, vflm_num, matchday_number, event_id,
           home_team, away_team, total_goals, total_goals_odd,
           odd_odds, even_odds, result_source
    FROM v_results_odd_even_ready
    """
    if require_odds:
        sql += " WHERE odd_odds IS NOT NULL AND even_odds IS NOT NULL"
    with get_db() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    return df


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["implied_odd"] = 1.0 / df["odd_odds"].astype(float)
    df["implied_even"] = 1.0 / df["even_odds"].astype(float)
    over = df["implied_odd"] + df["implied_even"]
    df["implied_odd_norm"] = df["implied_odd"] / over
    df["implied_even_norm"] = df["implied_even"] / over
    df["book_bias_odd"] = df["implied_odd_norm"] - 0.5
    df["log_odd"] = np.log(df["odd_odds"].astype(float))
    df["log_even"] = np.log(df["even_odds"].astype(float))
    df["md_sin"] = np.sin(2 * np.pi * df["matchday_number"] / 30.0)
    df["md_cos"] = np.cos(2 * np.pi * df["matchday_number"] / 30.0)
    return df


FEATURE_COLS = [
    "matchday_number",
    "vflm_num",
    "odd_odds",
    "even_odds",
    "implied_odd_norm",
    "implied_even_norm",
    "book_bias_odd",
    "log_odd",
    "log_even",
    "md_sin",
    "md_cos",
]


def baseline_metrics(y_true: np.ndarray, odd_odds: np.ndarray, even_odds: np.ndarray) -> dict:
    """Bet MSport favorite (lower decimal odds) each row."""
    pick_odd = odd_odds < even_odds
    pred_odd = pick_odd.astype(int)
    acc = (pred_odd == y_true).mean()
    # flat 1u: win if picked side wins
    returns = np.where(
        pick_odd,
        np.where(y_true == 1, odd_odds - 1, -1),
        np.where(y_true == 0, even_odds - 1, -1),
    )
    return {
        "n": int(len(y_true)),
        "accuracy_favorite": float(acc),
        "roi_flat_1u": float(returns.mean()),
        "pct_actual_odd": float(y_true.mean()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoff-vflm", type=int, default=5200, help="Test seasons with vflm_num >= this")
    ap.add_argument("--max-depth", type=int, default=5)
    ap.add_argument("--min-samples-leaf", type=int, default=200)
    ap.add_argument("--export-all-results", action="store_true", help="Also write parquet without odds (labels only)")
    args = ap.parse_args()

    from sklearn.tree import DecisionTreeClassifier
    from sklearn.metrics import accuracy_score, roc_auc_score, classification_report
    import joblib

    df = load_frame(require_odds=True)
    if df.empty:
        raise SystemExit("No rows with Odd/Even odds — check vfl_prematch_odds")

    df = add_features(df)
    y = df["total_goals_odd"].astype(int).values

    train = df[df["vflm_num"] < args.cutoff_vflm]
    test = df[df["vflm_num"] >= args.cutoff_vflm]
    if len(test) < 100:
        # fallback: last 15% seasons by vflm
        cutoff = df["vflm_num"].quantile(0.85)
        train = df[df["vflm_num"] < cutoff]
        test = df[df["vflm_num"] >= cutoff]

    X_train = train[FEATURE_COLS].astype(float)
    y_train = train["total_goals_odd"].astype(int)
    X_test = test[FEATURE_COLS].astype(float)
    y_test = test["total_goals_odd"].astype(int)

    clf = DecisionTreeClassifier(
        max_depth=args.max_depth,
        min_samples_leaf=args.min_samples_leaf,
        class_weight="balanced",
        random_state=42,
    )
    clf.fit(X_train, y_train)

    proba = clf.predict_proba(X_test)[:, 1]
    pred = (proba >= 0.5).astype(int)

    base = baseline_metrics(
        y_test.values,
        test["odd_odds"].astype(float).values,
        test["even_odds"].astype(float).values,
    )

    # Model-guided bet: bet Odd if proba>=0.5 else Even
    returns_model = np.where(
        pred == 1,
        np.where(y_test.values == 1, test["odd_odds"].astype(float).values - 1, -1),
        np.where(y_test.values == 0, test["even_odds"].astype(float).values - 1, -1),
    )

    metrics = {
        "train_n": int(len(train)),
        "test_n": int(len(test)),
        "cutoff_vflm": args.cutoff_vflm,
        "test_vflm_range": [int(test["vflm_num"].min()), int(test["vflm_num"].max())],
        "accuracy": float(accuracy_score(y_test, pred)),
        "roc_auc": float(roc_auc_score(y_test, proba)) if len(np.unique(y_test)) > 1 else None,
        "baseline_favorite": base,
        "model_roi_flat_1u": float(returns_model.mean()),
        "model_bets": int(len(test)),
        "feature_importance": dict(
            zip(FEATURE_COLS, [float(x) for x in clf.feature_importances_])
        ),
    }

    imp_path = OUT / "odd_even_dt.joblib"
    joblib.dump({"model": clf, "features": FEATURE_COLS}, imp_path)
    metrics_path = OUT / "odd_even_metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2))

    print(json.dumps(metrics, indent=2))
    print(f"\nModel: {imp_path}")
    print(f"Metrics: {metrics_path}")

    if args.export_all_results:
        all_df = load_frame(require_odds=False)
        path = OUT / "results_canonical_816.parquet"
        all_df.to_parquet(path, index=False)
        print(f"Exported {len(all_df)} canonical results -> {path}")


if __name__ == "__main__":
    main()