"""Tests for the presets module."""

from stonks.presets import POPULAR_SCREENS


def test_presets_structure():
    assert isinstance(POPULAR_SCREENS, list)
    assert len(POPULAR_SCREENS) > 0
    for screen in POPULAR_SCREENS:
        assert "name" in screen
        assert "description" in screen
        assert "filters" in screen
        assert "view_preset" in screen
        assert "sort_column" in screen
        assert "sort_ascending" in screen


def test_all_preset_filter_columns_are_supported():
    from stonks.config import NUMERIC_FILTER_COLUMNS
    from stonks.stockanalysis import SUPPORTED_COLUMNS

    supported = (
        SUPPORTED_COLUMNS
        | {"exchange", "currency", "type", "mic"}
        | set(NUMERIC_FILTER_COLUMNS)
    )
    for preset in POPULAR_SCREENS:
        assert set(preset["filters"]) <= supported


def test_quality_screen_insider_filter_honors_not_zero():
    """The Quality screen's 'Shares Insiders Not Zero' filter must accept tiny
    nonzero fractions (e.g. DRD's 0.00069) while still excluding exact zero."""
    quality = next(s for s in POPULAR_SCREENS if "Quality Screen" in s["name"])
    threshold = quality["filters"]["shares_insiders_pct"]["min"]
    assert 0 < threshold < 0.00069
