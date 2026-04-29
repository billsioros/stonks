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
