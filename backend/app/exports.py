"""Spreadsheet-safe exports: cells that a spreadsheet would run as a formula are prefixed with an apostrophe."""

import pandas as pd

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(v):
    if isinstance(v, str) and v.startswith(FORMULA_START):
        return "'" + v
    return v


def safe_df(df: pd.DataFrame) -> pd.DataFrame:
    return df.map(safe_cell)
