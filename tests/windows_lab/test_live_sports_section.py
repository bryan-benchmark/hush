"""Live sports open must prefer NFL rows over Atlanta Opry filler."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.us_locals import _find_live_sports_station


def _node(text: str, y: int, x: int = 500) -> ET.Element:
    n = ET.Element(
        "node",
        {
            "text": text,
            "bounds": f"[{x},{y}][{x + 400},{y + 40}]",
        },
    )
    return n


def test_find_live_sports_skips_opry_picks_nfl():
    root = ET.Element("hierarchy")
    # Atlanta airing Opry (wrong pick historically)
    root.append(_node("GA | ATLANTA | CBS - WANF", 400))
    root.append(_node("Opry", 405))
    root.append(_node("The Song", 410))
    # Neighbor with live NFL
    root.append(_node("FL | PANAMA CITY | CBS - WECP", 500))
    root.append(
        _node("NFL Football : Kansas City Chiefs at Atlanta Falcons ᴸᶦᵛᵉ", 505)
    )
    hit = _find_live_sports_station(root, network="CBS")
    assert hit is not None
    title, prog, *_ = hit
    assert "PANAMA CITY" in title.upper() or "WECP" in title.upper()
    assert "NFL" in prog.upper()
    assert "opry" not in prog.lower()


def test_find_live_sports_avoids_peer_program_key():
    root = ET.Element("hierarchy")
    root.append(_node("FL | PANAMA CITY | CBS - WECP", 500))
    root.append(
        _node("NFL Football : Kansas City Chiefs at Atlanta Falcons ᴸᶦᵛᵉ", 505)
    )
    root.append(_node("FL | WEST PALM BEACH | CBS - WPEC", 600))
    root.append(
        _node("NFL Football : Miami Dolphins at Indianapolis Colts ᴸᶦᵛᵉ", 605)
    )
    hit = _find_live_sports_station(
        root,
        network="CBS",
        avoid_program_keys={"kansas city chiefs at atlanta falcons"},
    )
    assert hit is not None
    _, prog, *_ = hit
    assert "dolphins" in prog.lower() or "indianapolis" in prog.lower()


def test_find_live_sports_prefers_ga_al_over_ak():
    root = ET.Element("hierarchy")
    root.append(_node("AK | ANCHORAGE | CBS - KTBY", 300))
    root.append(
        _node("NFL Football : Minnesota Vikings at Green Bay Packers ᴸᶦᵛᵉ", 305)
    )
    root.append(_node("GA | ATLANTA | CBS - WANF", 400))
    root.append(_node("Opry", 405))
    root.append(_node("GA | AUGUSTA | CBS - WRDW", 500))
    root.append(
        _node("NFL Football : Kansas City Chiefs at Atlanta Falcons ᴸᶦᵛᵉ", 505)
    )
    root.append(_node("AL | BIRMINGHAM | CBS - WIAT", 600))
    root.append(
        _node("NFL Football : Kansas City Chiefs at Atlanta Falcons ᴸᶦᵛᵉ", 605)
    )
    hit = _find_live_sports_station(root, network="CBS", require_prefer_states=True)
    assert hit is not None
    title, prog, *_ = hit
    assert title.upper().startswith("GA |") or title.upper().startswith("AL |")
    assert "ANCHORAGE" not in title.upper()
    assert "NFL" in prog.upper()
    assert "opry" not in prog.lower()


def test_find_live_sports_skips_atlanta_opry_when_require_ga():
    root = ET.Element("hierarchy")
    root.append(_node("GA | ATLANTA | CBS - WANF", 400))
    root.append(_node("Opry", 405))
    root.append(_node("GA | MACON | CBS - WMAZ", 500))
    root.append(
        _node("NFL Football : Kansas City Chiefs at Atlanta Falcons ᴸᶦᵛᵉ", 505)
    )
    hit = _find_live_sports_station(root, network="CBS", require_prefer_states=True)
    assert hit is not None
    title, *_ = hit
    assert "MACON" in title.upper() or "WMAZ" in title.upper()
    assert "WANF" not in title.upper()
