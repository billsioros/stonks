"""ScreenerEngine — filtering, sorting, pagination of the stock DataFrame."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


class ScreenerEngine:
    """Applies filters, search, sort and pagination to a stock DataFrame."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df.copy()

    @property
    def raw_df(self) -> pd.DataFrame:
        """Return the underlying raw DataFrame."""
        return self._df

    def apply_filters(self, filters: dict[str, Any]) -> pd.DataFrame:
        """Apply a set of filters to the DataFrame.

        Filters format:
            {
                "column_name": {"min": value, "max": value},   # numeric range
                "column_name": {"values": [val1, val2, ...]},   # enum / in-list
            }

        Returns:
            Filtered DataFrame.
        """
        df = self._df.copy()

        for col, spec in filters.items():
            if col not in df.columns:
                continue

            if "min" in spec:
                df = df[pd.to_numeric(df[col], errors="coerce") >= spec["min"]]
            if "max" in spec:
                df = df[pd.to_numeric(df[col], errors="coerce") <= spec["max"]]
            if "values" in spec and spec["values"]:
                df = df[df[col].isin(spec["values"])]

        return df.reset_index(drop=True)

    def search(self, df: pd.DataFrame, query: str) -> pd.DataFrame:
        """Full-text search across symbol and description columns."""
        if not query.strip():
            return df

        q = query.strip().upper()
        mask = pd.Series([False] * len(df), index=df.index)

        if "symbol" in df.columns:
            mask |= df["symbol"].str.upper().str.contains(q, na=False)
        if "description" in df.columns:
            mask |= df["description"].str.upper().str.contains(q, na=False)

        return df[mask].reset_index(drop=True)

    def sort(
        self,
        df: pd.DataFrame,
        column: str | None = None,
        ascending: bool = True,
    ) -> pd.DataFrame:
        """Sort the DataFrame by a column."""
        if column is None or column not in df.columns:
            return df

        # Convert to numeric for numeric columns
        try:
            sort_vals = pd.to_numeric(df[column], errors="coerce")
            df = df.assign(**{f"_sort_{column}": sort_vals})
            df = df.sort_values(f"_sort_{column}", ascending=ascending, na_position="last")
            df = df.drop(columns=[f"_sort_{column}"])
        except Exception:
            df = df.sort_values(column, ascending=ascending, na_position="last")

        return df.reset_index(drop=True)

    def paginate(
        self,
        df: pd.DataFrame,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[pd.DataFrame, int]:
        """Return a page of results and total number of pages.

        Args:
            df: The DataFrame to paginate.
            page: 1-indexed page number.
            page_size: Number of rows per page.

        Returns:
            Tuple of (page_df, total_pages).
        """
        total_rows = len(df)
        total_pages = max(1, math.ceil(total_rows / page_size))
        page = max(1, min(page, total_pages))
        start = (page - 1) * page_size
        end = start + page_size
        return df.iloc[start:end].reset_index(drop=True), total_pages

    def run_screen(
        self,
        filters: dict[str, Any] | None = None,
        search_query: str = "",
        sort_column: str | None = None,
        sort_ascending: bool = True,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[pd.DataFrame, int, int]:
        """Run a full screen: filter → search → sort → paginate.

        Returns:
            Tuple of (page_df, total_pages, total_matching_rows).
        """
        df = self._df.copy()

        if filters:
            df = self.apply_filters(filters)
            # Re-create engine view for chaining
            self_view = ScreenerEngine(df)
        else:
            self_view = self

        df = self_view.search(df, search_query) if search_query else df
        total_matching = len(df)

        df = self_view.sort(df, sort_column, sort_ascending) if sort_column else df
        page_df, total_pages = self_view.paginate(df, page, page_size)

        return page_df, total_pages, total_matching
