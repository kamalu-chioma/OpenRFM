"""Quick regression check for the Customer Lifetime Value (LTV) calculation.

The script recomputes the RFM metrics for the bundled sample dataset using the
same formula as the application. It exits with a non-zero code if the
calculated LTV values do not match the published sample output file within a
1e-2 tolerance after rounding.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import pandas as pd

REFERENCE_DATE = datetime(2025, 3, 1)
ROOT_DIR = Path(__file__).resolve().parents[1]
SAMPLE_INPUT = ROOT_DIR / "data" / "sample_data.csv"
SAMPLE_OUTPUT = ROOT_DIR / "data" / "sample_rfm_output.csv"

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import calculate_ltv

def compute_metrics(reference_date: datetime) -> pd.DataFrame:
    """Compute RFM metrics needed for the LTV calculation."""

    df = pd.read_csv(SAMPLE_INPUT, parse_dates=["TransactionDate"])

    customer_dates = (
        df.groupby("CustomerID")["TransactionDate"]
        .agg(FirstPurchaseDate="min", LastPurchaseDate="max")
        .reset_index()
    )
    customer_dates["CustomerTenureDays"] = (
        reference_date - customer_dates["FirstPurchaseDate"]
    ).dt.days.clip(lower=1)
    customer_dates["CustomerTenureYears"] = (
        customer_dates["CustomerTenureDays"] / 365.25
    )

    frequency_df = df.groupby("CustomerID").size().reset_index(name="Frequency")
    monetary_df = (
        df.groupby("CustomerID")["TransactionAmount"]
        .sum()
        .reset_index(name="Monetary")
    )

    rfm_df = (
        customer_dates
        .merge(frequency_df, on="CustomerID")
        .merge(monetary_df, on="CustomerID")
    )
    rfm_df["AverageOrderValue"] = (
        rfm_df["Monetary"] / rfm_df["Frequency"]
    )
    rfm_df["PurchaseFrequencyPerYear"] = (
        rfm_df["Frequency"] / rfm_df["CustomerTenureYears"]
    )

    rfm_df["LTV"] = calculate_ltv(
        rfm_df["AverageOrderValue"],
        rfm_df["PurchaseFrequencyPerYear"],
        rfm_df["CustomerTenureYears"],
    )
    return rfm_df[["CustomerID", "LTV"]]


def main() -> None:
    computed = compute_metrics(REFERENCE_DATE)
    expected = pd.read_csv(SAMPLE_OUTPUT)

    merged = computed.merge(expected[["CustomerID", "LTV"]], on="CustomerID")
    merged.rename(columns={"LTV_x": "LTV_computed", "LTV_y": "LTV_expected"}, inplace=True)

    # Compare rounded values to avoid floating point noise.
    diffs = (
        merged["LTV_computed"].round(2)
        - merged["LTV_expected"].round(2)
    ).abs()

    if (diffs > 1e-2).any():
        failures = merged.loc[diffs > 1e-2, ["CustomerID", "LTV_computed", "LTV_expected"]]
        raise SystemExit(
            "LTV regression check failed:\n" + failures.to_string(index=False)
        )

    print(f"LTV regression check passed for {len(merged)} customers.")


if __name__ == "__main__":
    main()
