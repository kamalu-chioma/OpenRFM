"""Utilities for inferring core RFM schema columns.

The module exposes helpers that inspect arbitrary tabular data and try to
identify which columns represent customer identifiers, transaction dates and
transaction amounts.  The scoring system combines heuristics based on
column-name similarity (regex and fuzzy matching), pandas dtype inspection and
value distribution statistics so that we can confidently map unfamiliar
datasets into the structure expected by the RFM pipeline.
"""

from __future__ import annotations

import logging
import re
import warnings
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd
from fuzzywuzzy import fuzz

logger = logging.getLogger(__name__)


TARGET_COLUMNS = ["CustomerID", "TransactionDate", "TransactionAmount"]


NAME_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "CustomerID": (
        "customer id",
        "customer",
        "client",
        "user",
        "buyer",
        "account",
        "member",
        "subscriber",
    ),
    "TransactionDate": (
        "transaction date",
        "date",
        "order date",
        "purchase",
        "invoice",
        "timestamp",
        "datetime",
        "sale date",
    ),
    "TransactionAmount": (
        "amount",
        "revenue",
        "sales",
        "total",
        "spend",
        "value",
        "price",
        "payment",
        "monetary",
        "charge",
    ),
}


REGEX_HINTS: Dict[str, Tuple[re.Pattern, ...]] = {
    "CustomerID": (
        re.compile(r"cust(omer)?[_-]?id", re.IGNORECASE),
        re.compile(r"client[_-]?id", re.IGNORECASE),
        re.compile(r"account[_-]?id", re.IGNORECASE),
        re.compile(r"user[_-]?id", re.IGNORECASE),
    ),
    "TransactionDate": (
        re.compile(r"(trans|order|sale|purchase|invoice).*date", re.IGNORECASE),
        re.compile(r"date$", re.IGNORECASE),
        re.compile(r"timestamp", re.IGNORECASE),
    ),
    "TransactionAmount": (
        re.compile(r"(sales|revenue|total|amount|spend|value|charge)", re.IGNORECASE),
        re.compile(r"(net|gross).*amount", re.IGNORECASE),
        re.compile(r"payment", re.IGNORECASE),
    ),
}


MIN_INFERENCE_SCORE = 0.55

NEGATIVE_AMOUNT_KEYWORDS = ("quantity", "qty", "count", "units", "unit", "volume")


@dataclass
class ColumnScore:
    column: str
    score: float
    components: Dict[str, float]


class SchemaInferenceError(Exception):
    """Raised when schema inference fails."""

    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__(message)
        self.details = details or {}


def _normalise_column_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.replace("_", " ").replace("-", " ")).strip().lower()


def _name_similarity_score(column_name: str, target: str) -> float:
    """Return a fuzzy match score between ``column_name`` and the target keywords."""

    cleaned = _normalise_column_name(column_name)
    keywords = NAME_KEYWORDS[target]

    max_ratio = 0.0
    for keyword in keywords:
        ratio = fuzz.partial_ratio(cleaned, keyword) / 100.0
        if ratio > max_ratio:
            max_ratio = ratio
    return max_ratio


def _regex_bonus(column_name: str, target: str) -> float:
    cleaned = column_name.lower()
    for pattern in REGEX_HINTS[target]:
        if pattern.search(cleaned):
            return 0.4
    return 0.0


def _attempt_numeric(series: pd.Series) -> Tuple[pd.Series, float]:
    """Return a numeric Series and the ratio of successfully coerced values."""

    # Convert to string for cleaning, preserving NaNs.
    as_str = series.astype(str)
    as_str = as_str.str.replace(r"[,$]", "", regex=True).str.replace("(", "-", regex=False).str.replace(")", "", regex=False)
    numeric = pd.to_numeric(as_str, errors="coerce")
    return numeric, numeric.notna().mean() if len(numeric) else 0.0


def _attempt_datetime(series: pd.Series) -> Tuple[pd.Series, float]:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Could not infer format, so each element will be parsed individually.*")
        parsed = pd.to_datetime(series, errors="coerce")
    return parsed, parsed.notna().mean() if len(parsed) else 0.0


def _score_customer_id(column_name: str, series: pd.Series) -> ColumnScore:
    non_null = series.dropna()
    if non_null.empty:
        return ColumnScore(column_name, 0.0, {"non_null_ratio": 0.0})

    components: Dict[str, float] = {}
    score = 0.0

    name_score = _name_similarity_score(column_name, "CustomerID")
    regex_score = _regex_bonus(column_name, "CustomerID")
    score += min(0.3, name_score * 0.3)
    score += regex_score
    components["name_similarity"] = round(name_score, 3)
    components["regex_bonus"] = round(regex_score, 3)

    unique_ratio = non_null.nunique(dropna=True) / max(len(non_null), 1)
    uniqueness_component = min(unique_ratio, 1.0) * 0.5
    score += uniqueness_component
    components["unique_ratio"] = round(unique_ratio, 3)

    # Penalise if most values look numeric with small cardinality (more likely an amount).
    numeric, numeric_ratio = _attempt_numeric(non_null)
    components["numeric_ratio"] = round(numeric_ratio, 3)
    if numeric_ratio > 0.9 and unique_ratio < 0.3:
        score *= 0.6

    return ColumnScore(column_name, min(score, 1.0), components)


def _score_transaction_date(column_name: str, series: pd.Series) -> ColumnScore:
    non_null = series.dropna()
    if non_null.empty:
        return ColumnScore(column_name, 0.0, {"non_null_ratio": 0.0})

    components: Dict[str, float] = {}
    score = 0.0

    name_score = _name_similarity_score(column_name, "TransactionDate")
    regex_score = _regex_bonus(column_name, "TransactionDate")
    score += min(0.3, name_score * 0.3)
    score += regex_score
    components["name_similarity"] = round(name_score, 3)
    components["regex_bonus"] = round(regex_score, 3)

    parsed, valid_ratio = _attempt_datetime(non_null)
    components["valid_datetime_ratio"] = round(valid_ratio, 3)
    if valid_ratio >= 0.7:
        score += 0.6
    elif valid_ratio >= 0.4:
        score += 0.35

    # Penalise numeric-looking columns that are likely monetary.
    numeric, numeric_ratio = _attempt_numeric(non_null)
    if numeric_ratio > 0.8 and valid_ratio < 0.4:
        score *= 0.5

    return ColumnScore(column_name, min(score, 1.0), components)


def _score_transaction_amount(column_name: str, series: pd.Series) -> ColumnScore:
    non_null = series.dropna()
    if non_null.empty:
        return ColumnScore(column_name, 0.0, {"non_null_ratio": 0.0})

    components: Dict[str, float] = {}
    score = 0.0

    name_score = _name_similarity_score(column_name, "TransactionAmount")
    regex_score = _regex_bonus(column_name, "TransactionAmount")
    score += min(0.3, name_score * 0.3)
    score += regex_score
    components["name_similarity"] = round(name_score, 3)
    components["regex_bonus"] = round(regex_score, 3)

    numeric, valid_ratio = _attempt_numeric(non_null)
    components["valid_numeric_ratio"] = round(valid_ratio, 3)
    if valid_ratio >= 0.7:
        score += 0.6
    elif valid_ratio >= 0.5:
        score += 0.4

    if valid_ratio > 0:
        positive_ratio = (numeric.dropna() > 0).mean() if not numeric.dropna().empty else 0.0
        components["positive_ratio"] = round(float(positive_ratio), 3)
        if positive_ratio >= 0.7:
            score += 0.1

    # Penalise columns that look like dates.
    datetime_ratio = _attempt_datetime(non_null)[1]
    if datetime_ratio > 0.4 and valid_ratio < 0.5:
        score *= 0.4

    cleaned_name = _normalise_column_name(column_name)
    if any(keyword in cleaned_name for keyword in NEGATIVE_AMOUNT_KEYWORDS):
        score *= 0.5

    return ColumnScore(column_name, min(score, 1.0), components)


SCORERS = {
    "CustomerID": _score_customer_id,
    "TransactionDate": _score_transaction_date,
    "TransactionAmount": _score_transaction_amount,
}


def infer_schema(df: pd.DataFrame, min_score: float = MIN_INFERENCE_SCORE) -> Tuple[Dict[str, str], Dict[str, List[ColumnScore]]]:
    """Infer the RFM schema mapping for ``df``.

    Returns a mapping of canonical column names to the detected column along
    with detailed score information for every candidate column.
    """

    scores: Dict[str, List[ColumnScore]] = {target: [] for target in TARGET_COLUMNS}
    for column in df.columns:
        series = df[column]
        for target, scorer in SCORERS.items():
            scores[target].append(scorer(column, series))

    # Determine best mapping while ensuring each input column is only used once.
    mapping: Dict[str, str] = {}
    used_columns: set[str] = set()

    # Evaluate more confident targets first based on highest available score.
    target_order = sorted(
        TARGET_COLUMNS,
        key=lambda target: max((s.score for s in scores[target]), default=0.0),
        reverse=True,
    )

    for target in target_order:
        candidates = sorted(scores[target], key=lambda c: c.score, reverse=True)
        for candidate in candidates:
            if candidate.column in used_columns:
                continue
            if candidate.score >= min_score:
                mapping[target] = candidate.column
                used_columns.add(candidate.column)
                break

    missing_targets = [target for target in TARGET_COLUMNS if target not in mapping]
    if missing_targets:
        suggestions = {}
        for target in missing_targets:
            candidates = sorted(scores[target], key=lambda c: c.score, reverse=True)
            if candidates:
                top = candidates[0]
                suggestions[target] = {
                    "best_column": top.column,
                    "score": round(top.score, 3),
                    "components": top.components,
                }
            else:
                suggestions[target] = None

        raise SchemaInferenceError(
            "Unable to infer required columns: "
            + ", ".join(missing_targets)
            + ". Please rename the relevant fields or supply mapping hints.",
            details={"suggestions": suggestions},
        )

    return mapping, scores


def _summarise_invalid(message: str, count: int, total: int) -> Optional[str]:
    if count <= 0:
        return None
    percentage = (count / total) * 100 if total else 0
    return f"{message}: {count} rows ({percentage:.1f}%)."


def infer_and_standardize_rfm(
    df: pd.DataFrame,
    *,
    min_score: float = MIN_INFERENCE_SCORE,
    log: Optional[logging.Logger] = None,
) -> Tuple[pd.DataFrame, Dict[str, object]]:
    """Infer the schema of ``df`` and return a standardized dataframe.

    The resulting DataFrame has canonical column names and normalized data types
    ready for the downstream RFM calculations. Diagnostics about the inference
    process (scores, warnings, coercion summaries) are returned in the second
    element of the tuple.
    """

    mapping, scores = infer_schema(df, min_score=min_score)
    rename_map = {source: target for target, source in mapping.items()}
    standardized = df.rename(columns=rename_map).copy()

    diagnostics: Dict[str, object] = {
        "mapping": rename_map,
        "source_columns": mapping,
        "warnings": [],
    }
    if log is None:
        log = logger

    # Customer IDs
    standardized["CustomerID"] = standardized["CustomerID"].astype(str).str.strip()
    empty_mask = standardized["CustomerID"].eq("")
    empty_ids = int(empty_mask.sum())
    standardized.loc[empty_mask, "CustomerID"] = pd.NA
    msg = _summarise_invalid("Blank CustomerID values detected", empty_ids, len(standardized))
    if msg:
        diagnostics["warnings"].append(msg)
        log.warning(msg)

    # Transaction dates
    parsed_dates, valid_date_ratio = _attempt_datetime(standardized["TransactionDate"])
    invalid_dates = parsed_dates.isna().sum()
    standardized["TransactionDate"] = parsed_dates
    msg = _summarise_invalid("Rows with unparseable TransactionDate", invalid_dates, len(standardized))
    if msg:
        diagnostics["warnings"].append(msg)
        log.warning(msg)

    # Transaction amounts
    numeric_amounts, valid_amount_ratio = _attempt_numeric(standardized["TransactionAmount"])
    invalid_amounts = numeric_amounts.isna().sum()
    standardized["TransactionAmount"] = numeric_amounts.fillna(0)
    msg = _summarise_invalid("Rows with non-numeric TransactionAmount", invalid_amounts, len(standardized))
    if msg:
        diagnostics["warnings"].append(msg)
        log.warning(msg)

    diagnostics["coercion_ratios"] = {
        "TransactionDate": round(valid_date_ratio, 3),
        "TransactionAmount": round(valid_amount_ratio, 3),
    }

    return standardized, diagnostics

