"""Regression: section child row must match call letters (not city-only)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .us_locals import _find_row


def _ui(*titles: str) -> ET.Element:
    root = ET.Element("hierarchy")
    y = 400
    for t in titles:
        n = ET.SubElement(root, "node")
        n.set("text", t)
        n.set("bounds", f"[600,{y}][1400,{y + 80}]")
        y += 100
    return root


def test_find_row_requires_calls_not_city() -> None:
    ui = _ui(
        "NY | BINGHAMTON | CBS - WBNG",
        "NY | NEW YORK | CBS - WCBS",
        "NY | BUFFALO | CBS - WIVB",
    )
    row = _find_row(ui, calls="WCBS", city="NEW YORK", network="CBS")
    assert row is not None
    assert "WCBS" in row[0]
    assert "WBNG" not in row[0]


def test_find_row_ignores_city_only_neighbor() -> None:
    ui = _ui(
        "NY | NEW YORK | CBS - WCBS",
        "NY | NEW YORK | NBC - WNBC",
    )
    row = _find_row(ui, calls="WCBS", city="NEW YORK", network="CBS")
    assert row is not None
    assert "WCBS" in row[0]


def test_find_row_no_false_wbng_for_wcbs() -> None:
    ui = _ui("NY | BINGHAMTON | CBS - WBNG")
    row = _find_row(ui, calls="WCBS", city="NEW YORK", network="CBS")
    assert row is None


if __name__ == "__main__":
    test_find_row_requires_calls_not_city()
    test_find_row_ignores_city_only_neighbor()
    test_find_row_no_false_wbng_for_wcbs()
    print("local row match regression: PASS")
