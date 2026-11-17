"""Atomic Streamers navigation — optimized for open-model learning.

Every move is one atom: classify place → act from a *fresh* dump → reclassify.
Trajectories land in ``streamers_nav.jsonl`` with frame + texts + lesson so a
local model can learn *how* a human walks the app (not just end-state search).

Doctrine:
- Think in **parents**: TV groups from ``streamers_tv_groups.json`` are section
  parents (e.g. ``US SPORTS``). Linear nets are **children** under that parent
  (e.g. ``US: ESPN``, ``US: ESPN 2``). Open parent first, then scroll to child.
- Search is for **events** (team/show cards), not for substituting MAX SPORTS ESPN
  or sibling nets (ESPNU ≠ ESPN).
- Reject feeds that are wrong for the goal (e.g. ``MAX SPORTS`` when we want
  national US linear commercials).
"""

from __future__ import annotations

import json
import re
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout
from .instances import adb, connect_adb, get_instance, launch_bluestacks, wait_for_adb
from .streamers_open import (
    DEFAULT_INSTANCE,
    _dump_ui,
    _tap_text,
    _texts,
    load_shortcuts,
    save_shortcut,
    save_shortcuts,
)

# ---------------------------------------------------------------------------
# Learning corpus
# ---------------------------------------------------------------------------

NAV_JSONL = "streamers_nav.jsonl"
NAV_ATLAS = "NAV_ATLAS.md"
ROUTES_NAME = "streamers_nav_routes.json"

# Hard rejects when the goal is national US linear (ads/speech corpus).
REJECT_NATIONAL_LINEAR = (
    "max sports",
    "(max sports)",
    "amazon sports",
    "amzn",
    "no event available",
    "in french",
    "(in french)",
    "roku tv",  # often FAST, not national linear sports net
)

# Sibling ESPN* rows under US SPORTS — not interchangeable with US: ESPN.
REJECT_ESPN_SIBLINGS = (
    "espnu",
    "espn u",
    "espn 2",
    "espn2",
    "espn news",
    "espnews",
    "deportes",
    "the ocho",
    "espn+",
    "espn plus",
)

# Parent group ids as stored in Streamers Manage groups / tv_groups.json.
PARENT_US_SPORTS = "US SPORTS"
CHILD_US_ESPN = "US: ESPN"
CHILD_US_ESPN2 = "US: ESPN 2"

# Places the atlas / model should know.
PLACES = (
    "bluestacks_home",
    "streamers_welcome",
    "login",
    "player",
    "search_ui",
    "search_hub",
    "guide_rail",  # All channels / Favorites / SECTION list
    "section_grid",  # inside a named SECTION
    "unknown",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / NAV_JSONL


def atlas_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / NAV_ATLAS


def routes_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / ROUTES_NAME


def tv_groups_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / "streamers_tv_groups.json"


def load_tv_groups(root: Path | None = None) -> list[str]:
    """Parent section names from the playlist groups database."""
    path = tv_groups_path(root)
    if not path.is_file():
        return [PARENT_US_SPORTS]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        groups = [str(g) for g in (data.get("groups") or []) if str(g).strip()]
        return groups or [PARENT_US_SPORTS]
    except Exception:  # noqa: BLE001
        return [PARENT_US_SPORTS]


def assert_parent_group(parent: str, root: Path | None = None) -> str:
    """Normalize to a known tv_groups parent (e.g. US SPORTS, not US SPORTS SECTION)."""
    groups = load_tv_groups(root)
    raw = parent.strip()
    if raw in groups:
        return raw
    stripped = re.sub(r"\s+SECTION$", "", raw, flags=re.I).strip()
    if stripped in groups:
        return stripped
    # Case-insensitive fallback
    low = {g.lower(): g for g in groups}
    if raw.lower() in low:
        return low[raw.lower()]
    if stripped.lower() in low:
        return low[stripped.lower()]
    return stripped or raw


def _append(row: dict[str, Any], root: Path | None = None) -> None:
    path = log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _espn_child_route(
    *,
    route_id: str,
    child: str,
    why: str,
    avoid_extra: list[str] | None = None,
) -> dict[str, Any]:
    """Parent US SPORTS → exact child row. No search fallback (siblings poison scoring)."""
    avoid = ["MAX SPORTS", "MAX-", "("] + list(avoid_extra or [])
    reject = list(REJECT_NATIONAL_LINEAR)
    if child == CHILD_US_ESPN:
        reject.extend(REJECT_ESPN_SIBLINGS)
    else:
        # ESPN2 child: still reject ESPNU / Deportes / etc., keep espn 2
        reject.extend(s for s in REJECT_ESPN_SIBLINGS if s not in ("espn 2", "espn2"))
    return {
        "id": route_id,
        "goal": "national_linear_espn",
        "feed": "national_linear",
        "parent": PARENT_US_SPORTS,  # tv_groups.json group id
        "child": child,
        "why": why,
        "atoms": [
            {"op": "ensure_guide"},
            # Do not tap left-nav "TV" here — it leaves All channels and hides US * parents.
            {"op": "tap_all_channels"},
            {
                "op": "open_section",
                "section": PARENT_US_SPORTS,  # parent — not "US SPORTS SECTION"
                "optional": False,
            },
            {
                "op": "open_row",
                "match": child,
                "prefer": [child],
                "reject": reject,
                "avoid_substr": avoid,
            },
            {"op": "keyevent_open"},
        ],
        "accept_place": ["player", "section_grid"],
        "reject_groups": ["MAX SPORTS", "ESPN+ SECTION", "ESPN UNLIMITED"],
    }


def _default_routes() -> dict[str, Any]:
    """Human-shaped recipes. Atoms only — no remembered x,y."""
    return {
        "updated_utc": _now(),
        "policy": {
            "learn": (
                "One atom per step. Fresh dump before every tap. "
                "Parents = tv_groups sections (US SPORTS); children = rows under that "
                "parent (US: ESPN). Open parent, then child. Search is for event cards only. "
                "Log place_before → atom → place_after + frame for the open model."
            ),
            "reject_national_linear": list(REJECT_NATIONAL_LINEAR),
            "parents_from": "indexes/streamers_tv_groups.json",
        },
        "routes": {
            "ESPN_US": _espn_child_route(
                route_id="ESPN_US",
                child=CHILD_US_ESPN,
                why="Parent US SPORTS → child US: ESPN (national linear). Not ESPNU / MAX.",
                avoid_extra=["ESPNU", "ESPN U", "ESPN 2", "ESPN2", "DEPORTES", "ESPNEWS"],
            ),
            "ESPN2_US": _espn_child_route(
                route_id="ESPN2_US",
                child=CHILD_US_ESPN2,
                why="Parent US SPORTS → child US: ESPN 2 (Manningcast / ESPN2 linear).",
                avoid_extra=["ESPNU", "ESPN U", "DEPORTES", "ESPNEWS"],
            ),
            "ESPN_MAX_BAD": {
                "id": "ESPN_MAX_BAD",
                "goal": "do_not_use_for_national_ads",
                "feed": "max_sports",
                "deprecated": True,
                "why": "Wrong feed for national commercial corpus — keep as negative example",
                "atoms": [],
                "reject": True,
            },
        },
    }


def load_routes(root: Path | None = None) -> dict[str, Any]:
    path = routes_path(root)
    if not path.is_file():
        data = _default_routes()
        save_routes(data, root)
        return data
    data = json.loads(path.read_text(encoding="utf-8"))
    defaults_full = _default_routes()
    defaults = defaults_full["routes"]
    data.setdefault("routes", {})
    # Parent→child ESPN recipes: always refresh from code (setdefaults left ESPNU bugs in place).
    for k in ("ESPN_US", "ESPN2_US"):
        if k in defaults:
            data["routes"][k] = defaults[k]
    for k, v in defaults.items():
        data["routes"].setdefault(k, v)
    data["policy"] = defaults_full["policy"]
    return data


def save_routes(data: dict[str, Any], root: Path | None = None) -> Path:
    path = routes_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["updated_utc"] = _now()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Place classifier (cheap, text-first — learning signal for vision later)
# ---------------------------------------------------------------------------


def _sectionish_labels(texts: list[str]) -> list[str]:
    out = []
    for t in texts:
        # Bare parents from tv_groups (US SPORTS) plus * SECTION headers
        if t in (
            "US SPORTS",
            "US ENTERTAINMENT",
            "US DOCUMENTARY",
            "US MOVIES",
            "US NEWS",
            "US KIDS",
            "NFL TEAMS/CHANNELS",
            "NFL A",
            "NFL Y",
            "NFL T",
        ):
            out.append(t)
            continue
        if t.endswith("SECTION") or "SECTION" in t.upper():
            out.append(t)
        elif re.fullmatch(r"-{3,}.+-{3,}", t.strip()):
            out.append(t)  # -------MAX SPORTS------- style
        elif t.upper() in {"MAX SPORTS", "AMAZON SPORTS", "NFL A", "NFL T", "US SPORTS"}:
            out.append(t)
    return out


def classify_place(
    texts: list[str],
    *,
    activity: str = "",
    dump_ok: bool | None = None,
    dump_reason: str | None = None,
) -> dict[str, Any]:
    """Return place id + evidence for the model."""
    from .ui_dump import DUMP_FAILED_MARKER

    low = " | ".join(t.lower() for t in texts)
    sections = _sectionish_labels(texts)
    evidence: list[str] = []

    # Tagged soft-fail / circuit — never alias as fullscreen player.
    if dump_ok is False or any(DUMP_FAILED_MARKER in str(t) for t in texts):
        return {
            "place": "dump_dead",
            "evidence": ["dump_failed", dump_reason or "ui_dump"],
            "sections": [],
            "dump_ok": False,
            "dump_reason": dump_reason or "dump_failed",
            "lesson": (
                "uiautomator dump dead (null-root/empty) — do not swipe-hunt; "
                "heal ADB / wait circuit; use frame_watch if picture needed."
            ),
        }

    if not texts:
        return {
            "place": "player_or_blank",
            "evidence": ["empty_dump"],
            "sections": [],
            "lesson": "Empty accessibility tree — usually fullscreen player or loading. Back once, re-dump.",
        }
    if any("popular games" in t.lower() or "search for games" in t.lower() for t in texts):
        return {"place": "bluestacks_home", "evidence": ["popular_games"], "sections": []}
    if "username" in low and "password" in low:
        return {"place": "login", "evidence": ["credentials"], "sections": []}
    if "add playlist" in low and "username" not in low:
        return {"place": "streamers_welcome", "evidence": ["add_playlist"], "sections": []}
    if any("fhd" in t.lower() or "stereo" in t.lower() for t in texts) and any(
        "fps" in t.lower() or re.fullmatch(r"\d{3,5}", t) for t in texts
    ):
        return {"place": "player", "evidence": ["player_chrome"], "sections": sections}
    if "search history" in low or (
        "channels" in low and "programs" in low and "movies" in low
    ):
        return {"place": "search_ui", "evidence": ["search_tabs"], "sections": sections}

    channelish = sum(
        1
        for t in texts
        if " | " in t or t.startswith("(") or re.match(r"^(AMZN|FLSP|NFL)\b", t, re.I)
    )
    group_hdr = any(re.fullmatch(r"-{3,}.+-{3,}", t.strip()) for t in texts)
    if channelish >= 2 or group_hdr or "max sports" in low:
        evidence.append(f"channel_rows~{channelish}")
        if "max sports" in low:
            evidence.append("group=MAX_SPORTS")
        return {"place": "section_grid", "evidence": evidence, "sections": sections[:8]}

    if sections and ("all channels" in low or "favorites" in low or any(t.startswith("US ") for t in texts)):
        evidence.append(f"sections={sections[:6]}")
        return {"place": "guide_rail", "evidence": evidence, "sections": sections}
    if "favorites" in low or "all channels" in low:
        return {"place": "guide_rail", "evidence": ["favorites_or_all"], "sections": sections}
    if sections:
        return {"place": "section_grid", "evidence": ["section_header"], "sections": sections}
    return {"place": "unknown", "evidence": ["no_match"], "sections": sections}


def row_allowed(title: str, *, reject: list[str] | None = None) -> bool:
    low = title.lower()
    for frag in reject or REJECT_NATIONAL_LINEAR:
        if frag.lower() in low:
            return False
    return True


def score_row(
    title: str,
    *,
    match: str,
    prefer: list[str] | None = None,
    reject: list[str] | None = None,
    avoid_substr: list[str] | None = None,
) -> int:
    """Score a channel *child* row. Prefer exact titles under the parent section.

    ``US: ESPN`` and ``ESPNU`` both contain \"ESPN\" — only the preferred child
    (and not rejected siblings) should win for national linear.
    """
    tstrip = title.strip()
    tupper = tstrip.upper()
    m = match.strip()
    mlow = m.lower()
    # Normalize ESPN2 spacing so ``US: ESPN2`` matches ``US: ESPN 2``.
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s.lower().replace("espn2", "espn 2")).strip()

    # Exact preferred child wins before avoid/reject substring traps
    # (e.g. never let sibling rules shadow ``US: ESPN``).
    if tstrip == m or tupper == m.upper() or _norm(tstrip) == _norm(m):
        return 400
    if not row_allowed(title, reject=reject):
        return -10_000
    low = title.lower()
    for frag in avoid_substr or []:
        if frag.lower() in low:
            return -10_000
    if mlow not in low and _norm(m) not in _norm(title):
        return -100
    # Prefer list: exact child first
    for p in prefer or []:
        if tstrip == p or tupper == p.upper():
            return 380
    score = 50
    # Bare network labels (no US: prefix) — weaker than US: children
    if tupper in {"ESPN", "ESPN USA"}:
        score += 60
    elif tupper in {"ESPN2", "ESPN 2"}:
        score += 40
    # Never treat ESPNU / Deportes / etc. as the ESPN child unless explicitly preferred
    prefer_low = {p.lower() for p in (prefer or [])}
    if any(sib in low for sib in REJECT_ESPN_SIBLINGS):
        if not any(p in low for p in prefer_low if p):
            return -10_000
    if tstrip.startswith("("):
        score -= 40  # group-prefixed packs often wrong feed
    for p in prefer or []:
        if p.lower() in low and tstrip != p:
            score += 20
    if "max sports" in low:
        score -= 200
    return score


# ---------------------------------------------------------------------------
# Observation + atoms
# ---------------------------------------------------------------------------


def _screencap(instance: dict[str, Any], dest: Path) -> str | None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    remote = "/sdcard/ohush_nav.png"
    rc, _ = adb(instance, ["shell", "screencap", "-p", remote], timeout=20)
    if rc != 0:
        return None
    rc, _ = adb(instance, ["pull", remote, str(dest)], timeout=20)
    adb(instance, ["shell", "rm", remote], timeout=10)
    return str(dest) if dest.is_file() and rc == 0 else None


def _dump_ui_soft(
    instance: dict[str, Any],
    dest: Path,
    *,
    tries: int = 3,
    caller: str = "streamers_nav",
) -> ET.Element:
    """Soft dump via ui_dump contract — tagged DUMP_FAILED on exhaust, never silent empty."""
    from .ui_dump import dump_ui_soft

    return dump_ui_soft(instance, dest, tries=tries, caller=caller)


def observe(
    instance: dict[str, Any],
    *,
    root: Path,
    traj_id: str,
    step: int,
    tag: str,
) -> dict[str, Any]:
    """Fresh dump + still + place — the learning observation."""
    from .ui_dump import dump_meta_from_ui, is_dump_failed_ui

    probe = root / "work" / "streamers_nav" / traj_id
    probe.mkdir(parents=True, exist_ok=True)
    xml_path = probe / f"{step:02d}_{tag}.xml"
    png_path = probe / f"{step:02d}_{tag}.png"
    ui = _dump_ui_soft(instance, xml_path, caller=f"observe:{tag}")
    texts = _texts(ui)
    meta = dump_meta_from_ui(ui)
    dump_ok = bool(meta.get("dump_ok")) and not is_dump_failed_ui(ui, texts)
    frame = _screencap(instance, png_path)
    place = classify_place(
        texts,
        dump_ok=dump_ok,
        dump_reason=str(meta.get("dump_reason") or "") or None,
    )
    return {
        "ui": ui,
        "texts": texts,
        "texts_head": texts[:40],
        "xml": str(xml_path),
        "frame": frame,
        "place": place["place"],
        "place_meta": place,
        "dump_ok": dump_ok,
        "dump_reason": meta.get("dump_reason"),
        "dump_fabricated": bool(meta.get("dump_fabricated")),
    }


def _ensure_instance(instance_id: str, root: Path) -> dict[str, Any]:
    instance = get_instance(instance_id, root)
    launch_bluestacks(instance, launch_app=True)
    connect_adb(instance)
    if not wait_for_adb(instance, seconds=60):
        raise RuntimeError("ADB not ready")
    return instance


def atom_back(instance: dict[str, Any]) -> dict[str, Any]:
    adb(instance, ["shell", "input", "keyevent", "4"])
    time.sleep(0.8)
    return {"ok": True, "op": "back", "lesson": "Back (keyevent 4) leaves player/search one level; do not spam or you exit Streamers."}


def atom_rematchimize(instance: dict[str, Any]) -> dict[str, Any]:
    """Long-press Back — rematchimizes the channel already playing in the guide preview.

    Short Back leaves the player for the guide. Hold Back from the guide returns
    to fullscreen on the current channel (preview) without re-hunting the row.
    """
    adb(instance, ["shell", "input", "keyevent", "--longpress", "4"])
    time.sleep(1.6)
    return {
        "ok": True,
        "op": "rematchimize",
        "lesson": (
            "Long-press Back (keyevent --longpress 4) rematchimizes the preview channel. "
            "Use when the guide is up but the player is already on the right feed."
        ),
    }


def atom_keyevent_open(instance: dict[str, Any]) -> dict[str, Any]:
    adb(instance, ["shell", "input", "keyevent", "23"])
    time.sleep(2.0)
    return {"ok": True, "op": "keyevent_open", "lesson": "After the row is selected, d-pad center (23) opens the channel — not a tap on the preview."}


def _guide_rail_chrome(texts: list[str]) -> bool:
    """True when All/Favorites/US* chrome is visible (rail alive — not yet US SPORTS)."""
    if "Search history" in texts:
        return False
    if "All channels" in texts or "Favorites" in texts:
        return True
    genre = ("US SPORTS", "US ENTERTAINMENT", "US NEWS", "US MOVIES", "US KIDS")
    if sum(1 for p in genre if p in texts) >= 2:
        return True
    if any(t.startswith("US ") and len(t) < 28 for t in texts):
        return True
    return False


def _guide_rail_ready(texts: list[str], *, need_us_sports: bool = False) -> bool:
    """True when the left rail can reach US SPORTS (not Search, not a lone DMA section).

    ESPN routes must pass ``need_us_sports=True`` — bare All channels is NOT done.
    """
    if "Search history" in texts:
        return False
    if need_us_sports:
        return "US SPORTS" in texts
    return _guide_rail_chrome(texts)


def _dump_texts_empty(texts: list[str] | None) -> bool:
    """Soft/null dumps yield no usable labels — hunting on them cascades Bug 2."""
    if not texts:
        return True
    useful = [t for t in texts if str(t).strip()]
    return len(useful) == 0


def atom_ensure_guide(instance: dict[str, Any], obs: dict[str, Any], root: Path, traj_id: str, step: int) -> dict[str, Any]:
    """Leave Search/player and land with US SPORTS on the left rail (ESPN path).

    Bare All channels is chrome-alive only — not ready for sports linear.
    """
    probe = root / "work" / "streamers_nav" / traj_id
    place = obs["place"]
    texts = list(obs.get("texts") or [])
    if place == "bluestacks_home" or (
        not texts and place in {"unknown", "player_or_blank"}
    ):
        adb(
            instance,
            ["shell", "monkey", "-p", "ar.tvplayer.tv", "-c", "android.intent.category.LAUNCHER", "1"],
        )
        time.sleep(3.5)
        actions = ["relaunch"]
        ui = _dump_ui_soft(instance, probe / f"{step:02d}_ensure_relaunch.xml")
        texts = _texts(ui)
        place = classify_place(texts)["place"]
        for i in range(4):
            # Intermediate: chrome is enough to stop backing; Sports required at end.
            if _guide_rail_chrome(texts):
                break
            atom_back(instance)
            time.sleep(0.8)
            actions.append("back_after_relaunch")
            ui = _dump_ui_soft(instance, probe / f"{step:02d}_ensure_relaunch_back_{i}.xml")
            texts = _texts(ui)
            place = classify_place(texts)["place"]
        # Fall through with fresh ui/texts/place after relaunch attempts.

    actions: list[str] = []
    ui = obs["ui"]
    # Dismiss Search overlay — classify often calls this guide_rail while Search history is up.
    for i in range(4):
        texts = _texts(ui)
        if "Search history" in texts or (
            place in {"search_ui", "search_hub"} and not _guide_rail_chrome(texts)
        ):
            atom_back(instance)
            time.sleep(0.55)
            actions.append("back_search")
            ui = _dump_ui_soft(instance, probe / f"{step:02d}_ensure_back_{i}.xml")
            place = classify_place(_texts(ui))["place"]
            continue
        break

    texts = _texts(ui)
    # ESPN path: US SPORTS on rail is the only early success — not bare All.
    if _guide_rail_ready(texts, need_us_sports=True):
        return {
            "ok": True,
            "op": "ensure_guide",
            "via": "+".join(actions) or "already",
            "lesson": "Guide rail ready — US SPORTS visible (not bare All / Entertainment).",
            "us_sports_visible": True,
        }

    # Stuck inside a DMA / pack EPG (US FOX SECTION, NFL A, …) without the
    # left-rail genre list — Back reveals US SPORTS / All channels.
    pack_or_dma = (
        any(
            t in texts
            for t in (
                "US FOX SECTION",
                "US CBS SECTION",
                "US NBC SECTION",
                "US ABC SECTION",
                "US CW/MY/PBS SECTION",
                "NFL A",
                "NFL Y",
                "NFL T",
                "NFL TEAMS/CHANNELS",
            )
        )
        and "US SPORTS" not in texts
        and "All channels" not in texts
    )
    if pack_or_dma or (
        place in {"section_grid", "guide_rail", "guide"} and not _guide_rail_chrome(texts)
    ):
        for i in range(4):
            atom_back(instance)
            time.sleep(0.7)
            actions.append("back_dma_epg")
            ui = _dump_ui_soft(instance, probe / f"{step:02d}_ensure_back_dma_{i}.xml")
            texts = _texts(ui)
            place = classify_place(texts)["place"]
            if _guide_rail_ready(texts, need_us_sports=True):
                return {
                    "ok": True,
                    "op": "ensure_guide",
                    "via": "+".join(actions),
                    "lesson": "Backed out of DMA/pack EPG — US SPORTS on rail.",
                    "texts_head": texts[:20],
                    "us_sports_visible": True,
                }
            if "US SPORTS" in texts or _guide_rail_chrome(texts):
                break
            # Too many Backs leave Streamers — relaunch once.
            if any("popular games" in t.lower() for t in texts):
                adb(
                    instance,
                    [
                        "shell",
                        "monkey",
                        "-p",
                        "ar.tvplayer.tv",
                        "-c",
                        "android.intent.category.LAUNCHER",
                        "1",
                    ],
                )
                time.sleep(3.2)
                actions.append("relaunch_after_home")
                ui = _dump_ui_soft(instance, probe / f"{step:02d}_ensure_relaunch_home.xml")
                texts = _texts(ui)
                place = classify_place(texts)["place"]
                if _guide_rail_ready(texts, need_us_sports=True):
                    return {
                        "ok": True,
                        "op": "ensure_guide",
                        "via": "+".join(actions),
                        "lesson": "Relaunched after Back hit BlueStacks home; US SPORTS on rail.",
                        "texts_head": texts[:20],
                        "us_sports_visible": True,
                    }
                break

    if "TV guide" in texts:
        _tap_text(instance, ui, "TV guide")
        time.sleep(1.6)
        actions.append("tv_guide")
        ui = _dump_ui_soft(instance, probe / f"{step:02d}_ensure_tvguide.xml")
        texts = _texts(ui)
        if _guide_rail_ready(texts, need_us_sports=True):
            return {
                "ok": True,
                "op": "ensure_guide",
                "via": "+".join(actions),
                "lesson": "US SPORTS on rail after TV guide.",
                "us_sports_visible": True,
            }

    # Only tap All channels when Sports is missing — retapping while already on
    # the rail often lands a huge hit-target and blanks the dump.
    if "All channels" in texts and not _guide_rail_ready(texts, need_us_sports=True):
        _tap_text(instance, ui, "All channels")
        time.sleep(1.0)
        actions.append("all_channels")
        ui = _dump_ui_soft(instance, probe / f"{step:02d}_ensure_allch.xml")
        texts = _texts(ui)

    if _guide_rail_ready(texts, need_us_sports=True):
        return {
            "ok": True,
            "op": "ensure_guide",
            "via": "+".join(actions) or "already",
            "lesson": "Guide rail ready — US SPORTS visible (not bare All / Entertainment).",
            "us_sports_visible": True,
        }

    # player / blank / unknown — Back once, then require rail on next atoms
    if place in {"player", "player_or_blank", "unknown"} or not texts:
        atom_back(instance)
        time.sleep(0.6)
        actions.append(f"back_from_{place}")
        ui = _dump_ui_soft(instance, probe / f"{step:02d}_ensure_back_player.xml")
        texts = _texts(ui)
        if "TV guide" in texts:
            _tap_text(instance, ui, "TV guide")
            time.sleep(1.4)
            actions.append("tv_guide")
            texts = _texts(_dump_ui_soft(instance, probe / f"{step:02d}_ensure_tvguide2.xml"))

    ready = _guide_rail_ready(texts, need_us_sports=True)
    # Must scroll to US SPORTS — NFL/Entertainment pages hide it below the fold.
    # Bare All channels after this is still a fail for ESPN routes.
    if not ready:
        try:
            scrolled = scroll_left_rail_for_label(
                instance,
                label="US SPORTS",
                probe=probe,
                tag=f"{step:02d}_ensure_us_sports",
                max_swipes=20,
            )
            texts = list(scrolled.get("texts") or [])
            if scrolled.get("ok") or _guide_rail_ready(texts, need_us_sports=True):
                ready = True
                actions.append("scroll_to_us_sports")
        except Exception:
            pass
    return {
        "ok": ready,
        "op": "ensure_guide",
        "via": "+".join(actions) or f"from_{place}",
        "us_sports_visible": bool(ready),
        "error": None if ready else "guide_rail_not_ready_need_us_sports",
        "texts_head": texts[:20],
        "lesson": (
            "Guide rail ready — US SPORTS visible."
            if ready
            else (
                "Could not land US SPORTS on the left rail (bare All / Entertainment / empty "
                "does not count). Recover before open_section."
            )
        ),
    }


def atom_tap_left_nav(instance: dict[str, Any], obs: dict[str, Any], *, label: str) -> dict[str, Any]:
    texts = obs["texts"]
    if label not in texts:
        # Left chrome sometimes hidden on guide — still ok
        return {
            "ok": True,
            "op": "tap_left_nav",
            "label": label,
            "skipped": True,
            "lesson": f"Left nav '{label}' not in dump (chrome may be collapsed). Continue.",
        }
    tapped = _tap_text(instance, obs["ui"], label)
    time.sleep(1.0)
    return {
        "ok": bool(tapped),
        "op": "tap_left_nav",
        "label": label,
        "tap": tapped,
        "lesson": f"Human path starts at left nav '{label}' (TV / Search / …), not a random grid tap.",
    }


def atom_search_channels(
    instance: dict[str, Any],
    obs: dict[str, Any],
    *,
    query: str,
    match: str,
    prefer: list[str] | None = None,
    reject: list[str] | None = None,
    avoid_substr: list[str] | None = None,
    root: Path,
    traj_id: str,
    step: int,
) -> dict[str, Any]:
    """Search → Channels tab → pick allowed row. Used when section rail lacks US SPORTS."""
    from .streamers_open import (
        _clear_search_field,
        _type_search_query,
        _open_search_via_longpress,
    )

    probe = root / "work" / "streamers_nav" / traj_id
    ui = obs["ui"]
    texts = obs["texts"]
    if "Search" not in texts:
        # Peek left chrome (TV / Search) — often collapsed while grid-focused
        adb(instance, ["shell", "input", "tap", "40", "200"])
        time.sleep(0.6)
        ui = _dump_ui(instance, probe / f"{step:02d}_left_peek.xml")
        texts = _texts(ui)
    if "Search" in texts:
        _tap_text(instance, ui, "Search")
        time.sleep(0.9)
        ui = _dump_ui(instance, probe / f"{step:02d}_search.xml")
    else:
        opened = _open_search_via_longpress(instance, ui, probe)
        if not opened.get("ok"):
            # Last resort: long-press any EPG row text (even AMZN) only to open the menu
            parents = {c: p for p in ui.iter() for c in list(p)}
            pressed = False
            for node in ui.iter("node"):
                t = (node.attrib.get("text") or "").strip()
                b = node.attrib.get("bounds") or ""
                if not t or not b or len(t) < 4:
                    continue
                if not ( " | " in t or t.startswith("(") or t.startswith("NFL") or t.startswith("SN")):
                    continue
                m = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
                if not m:
                    continue
                x1, y1, x2, y2 = map(int, m.groups())
                if y1 < 380:
                    continue
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                adb(instance, ["shell", "input", "swipe", str(cx), str(cy), str(cx), str(cy), "2800"])
                time.sleep(1.5)
                menu = _dump_ui(instance, probe / f"{step:02d}_menu.xml")
                mt = _texts(menu)
                if "Search" in mt:
                    _tap_text(instance, menu, "Search")
                    time.sleep(0.8)
                    ui = _dump_ui(instance, probe / f"{step:02d}_search.xml")
                    pressed = True
                    break
            if not pressed:
                return {
                    "ok": False,
                    "op": "search_channels",
                    "error": "search_not_opened",
                    "detail": opened,
                    "lesson": "Could not open Search (no left Search + long-press failed). Need a visible EPG row to long-press.",
                }
        else:
            ui = opened["ui"]
    _clear_search_field(instance, ui)
    _type_search_query(instance, query)
    adb(instance, ["shell", "input", "keyevent", "66"])
    time.sleep(2.0)
    ui = _dump_ui(instance, probe / f"{step:02d}_results.xml")
    texts = _texts(ui)
    if "Channels" in texts:
        _tap_text(instance, ui, "Channels")
        time.sleep(1.0)
        ui = _dump_ui(instance, probe / f"{step:02d}_channels_tab.xml")
        texts = _texts(ui)
    scored = []
    rejected = []
    for t in texts:
        s = score_row(t, match=match, prefer=prefer, reject=reject, avoid_substr=avoid_substr)
        if match.lower() in t.lower() and s <= -10_000:
            rejected.append(t)
        elif s >= 10:
            scored.append((s, t))
    if not scored:
        return {
            "ok": False,
            "op": "search_channels",
            "query": query,
            "rejected_examples": rejected[:12],
            "titles_head": texts[:30],
            "lesson": (
                "Search ESPN only returned rejected packs (e.g. MAX SPORTS). "
                "That is the wrong feed for national commercials — do not open them. "
                "Need a bare ESPN / US linear row in the playlist."
            ),
            "chose": None,
        }
    score, title = max(scored, key=lambda x: x[0])
    tapped = _tap_text(instance, ui, title, contains=False) or _tap_text(instance, ui, title, contains=True)
    time.sleep(0.6)
    return {
        "ok": bool(tapped),
        "op": "search_channels",
        "query": query,
        "chosen": title,
        "score": score,
        "rejected_examples": rejected[:12],
        "tap": tapped,
        "lesson": (
            f"Search '{query}' → Channels tab → chose '{title}' (score={score}). "
            f"Rejected {len(rejected)} MAX/pack titles — model must learn that reject list."
        ),
    }


def _rail_has_us_sports(texts: list[str]) -> bool:
    """True only when the US SPORTS parent label is on the rail — not Entertainment/All."""
    return "US SPORTS" in texts


def _wrong_us_parent(texts: list[str]) -> str | None:
    """Selected / visible sibling parent that is NOT US SPORTS."""
    # Top-right section chrome often echoes the active group.
    for bad in (
        "US ENTERTAINMENT",
        "US NEWS",
        "US MOVIES",
        "US DOCUMENTARY",
        "US KIDS",
        "US MUSIC",
    ):
        if bad in texts and "US SPORTS" not in texts:
            return bad
    if "-------US ENTERTAINMENT-------" in " | ".join(texts).upper():
        return "US ENTERTAINMENT"
    return None


def _rail_chrome_visible(texts: list[str]) -> bool:
    return (
        "All channels" in texts
        or "Favorites" in texts
        or _rail_has_us_sports(texts)
        or any(t.startswith("US ") and t.endswith(("ENTERTAINMENT", "NEWS", "MOVIES", "SPORTS")) for t in texts)
    )


def scroll_left_rail_for_label(
    instance: dict[str, Any],
    *,
    label: str,
    probe: Path,
    tag: str = "rail",
    max_swipes: int = 28,
) -> dict[str, Any]:
    """Scroll the *left group rail* until ``label`` (e.g. US SPORTS) is in the dump.

    NFL packs sit above US *; Entertainment is a sibling — must land on Sports.
    Dumping every swipe is too slow (~30s/dump when uiautomator is sick) — swipe
    in bursts, then dump once.
    """
    probe.mkdir(parents=True, exist_ok=True)

    def _swipe_down(n: int = 1) -> None:
        for _ in range(n):
            # x≈300 = center of rail labels [140,474]; avoid main grid at x=900.
            adb(instance, ["shell", "input", "swipe", "300", "720", "300", "380", "220"])
            time.sleep(0.12)

    def _swipe_up(n: int = 1) -> None:
        for _ in range(n):
            adb(instance, ["shell", "input", "swipe", "300", "380", "300", "720", "220"])
            time.sleep(0.12)

    from .ui_dump import DUMP_FAILED_MARKER, circuit_is_open, dump_meta_from_ui, is_dump_failed_ui

    def _dump(name: str):
        return _dump_ui_soft(
            instance,
            probe / f"{tag}_{name}.xml",
            tries=1,
            caller=f"scroll_rail:{tag}:{name}",
        )

    def _dead(ui_el: ET.Element, texts_l: list[str]) -> bool:
        return is_dump_failed_ui(ui_el, texts_l) or (
            not texts_l and not dump_meta_from_ui(ui_el).get("dump_ok", True)
        )

    if circuit_is_open(instance):
        return {
            "ok": False,
            "ui": None,
            "texts": [],
            "swipes": 0,
            "via": "dump_circuit_open",
            "error": "ui_dump_circuit_open",
            "dump_ok": False,
            "head": [],
        }

    # Cheap peek — if dump is dead, abort (do not blind-swipe the rail).
    ui = _dump("peek")
    texts = _texts(ui)
    dead_streak = 0
    if _dead(ui, texts):
        return {
            "ok": False,
            "ui": ui,
            "texts": texts,
            "swipes": 0,
            "via": "dump_dead",
            "error": "dump_dead",
            "dump_ok": False,
            "dump_reason": dump_meta_from_ui(ui).get("dump_reason"),
            "head": texts[:24],
        }
    if label in texts:
        return {"ok": True, "ui": ui, "texts": texts, "swipes": 0, "via": "already", "dump_ok": True}
    if not _rail_chrome_visible(texts):
        atom_back(instance)
        time.sleep(0.55)
        # Past NFL packs toward US * — Entertainment is a sibling, Sports is the target.
        _swipe_down(6)
        ui = _dump("after_burst")
        texts = _texts(ui)
        if _dead(ui, texts):
            return {
                "ok": False,
                "ui": ui,
                "texts": texts,
                "swipes": 6,
                "via": "dump_dead",
                "error": "dump_dead",
                "dump_ok": False,
                "head": texts[:24],
            }
        if label in texts:
            return {
                "ok": True,
                "ui": ui,
                "texts": texts,
                "swipes": 6,
                "via": "burst_down",
                "dump_ok": True,
            }

    total = 0
    for direction, budget in (("down", max_swipes), ("up", max(8, max_swipes // 2))):
        while total < budget:
            n = min(5, budget - total)
            if direction == "down":
                _swipe_down(n)
            else:
                _swipe_up(n)
            total += n
            ui = _dump(f"{direction}_{total}")
            texts = _texts(ui)
            if _dead(ui, texts) or not texts:
                dead_streak += 1
                if dead_streak >= 2:
                    return {
                        "ok": False,
                        "ui": ui,
                        "texts": texts,
                        "swipes": total,
                        "via": "dump_dead",
                        "error": "dump_dead_consecutive",
                        "dump_ok": False,
                        "dump_reason": dump_meta_from_ui(ui).get("dump_reason"),
                        "head": texts[:24],
                    }
                continue
            dead_streak = 0
            if label in texts:
                return {
                    "ok": True,
                    "ui": ui,
                    "texts": texts,
                    "swipes": total,
                    "via": f"scroll_{direction}",
                    "dump_ok": True,
                }
            # Stop this direction when we overshoot past Sports into ABC/CBS locals.
            if direction == "down" and any(
                t in texts for t in ("US ABC SECTION", "US CBS SECTION", "US NBC SECTION")
            ) and label not in texts:
                break
    return {
        "ok": label in texts,
        "ui": ui,
        "texts": texts,
        "swipes": total,
        "via": "exhausted",
        "dump_ok": not _dead(ui, texts),
        "head": texts[:24],
    }


def atom_tap_all_channels(
    instance: dict[str, Any],
    obs: dict[str, Any],
    *,
    root: Path | None = None,
    traj_id: str = "adhoc",
    step: int = 0,
) -> dict[str, Any]:
    """Land All channels + scroll the left rail until US * parents show (esp. US SPORTS)."""
    texts = list(obs["texts"] or [])
    ui = obs["ui"]
    # Only US SPORTS counts — US ENTERTAINMENT / All on the rail is NOT done.
    if _rail_has_us_sports(texts):
        return {
            "ok": True,
            "op": "tap_all_channels",
            "skipped": True,
            "us_sports_visible": True,
            "lesson": "US SPORTS already on the left rail.",
        }
    wrong = _wrong_us_parent(texts)
    if wrong:
        # Force rail scroll past Entertainment/News/Movies to Sports.
        pass
    if "All channels" not in texts and not _rail_chrome_visible(texts):
        return {
            "ok": False,
            "op": "tap_all_channels",
            "error": "all_channels_not_visible",
            "lesson": (
                "All channels not visible and US * parents missing — still on Favorites/NFL/Search. "
                "ensure_guide must land on the guide rail first."
            ),
        }
    tapped = None
    # Only tap All channels when Favorites/NFL pack is selected — not when already on it
    # (retap collapses the rail and US SPORTS never appears).
    if "All channels" in texts and (
        "NFL TEAMS/CHANNELS" in texts or "NFL A" in texts or "Favorites" in texts
    ):
        # If top-right / grid says NFL* while All channels is on the rail, select it once.
        tapped = _tap_text(instance, ui, "All channels")
        time.sleep(1.0)
    # Always scroll the rail for US SPORTS — that is the missing step.
    root = root or ensure_data_layout()
    probe = root / "work" / "streamers_nav" / traj_id
    probe.mkdir(parents=True, exist_ok=True)
    scrolled = scroll_left_rail_for_label(
        instance,
        label="US SPORTS",
        probe=probe,
        tag=f"{step:02d}_allch_us_sports",
    )
    texts_after = list(scrolled.get("texts") or [])
    ok_scroll = bool(scrolled.get("ok")) and _rail_has_us_sports(texts_after)
    wrong = _wrong_us_parent(texts_after)
    # Hard-fail when scroll exhausted without Sports — especially Entertainment head.
    # Soft ok:True here was the live lie that let ESPN_US walk Entertainment.
    if not ok_scroll:
        return {
            "ok": False,
            "op": "tap_all_channels",
            "tap": tapped,
            "us_sports_visible": False,
            "wrong_parent": wrong,
            "scroll": {k: scrolled.get(k) for k in ("ok", "swipes", "via", "head")},
            "texts_head": texts_after[:20],
            "error": "us_sports_not_visible_after_rail_scroll",
            "lesson": (
                f"Rail scroll exhausted without US SPORTS"
                + (f" (stuck under {wrong})" if wrong else "")
                + ". Refuse soft-success — open_section must not hunt under Entertainment/All."
            ),
        }
    return {
        "ok": True,
        "op": "tap_all_channels",
        "tap": tapped,
        "us_sports_visible": True,
        "scroll": {k: scrolled.get(k) for k in ("ok", "swipes", "via", "head")},
        "lesson": "Scrolled left rail to US SPORTS after All channels.",
    }


def _match_section_label(texts: list[str], section: str) -> str | None:
    """Match rail label or in-grid header ``-------US SPORTS-------`` only.

    Never match program titles (e.g. 'Indigenous Sports Academy').
    """
    aliases = {
        section.lower(),
        section.replace(" SECTION", "").lower(),
        "us sports section",
        "us sports",
        "-------us sports section-------",
        "-------us sports-------",
    }
    scored: list[tuple[int, str]] = []
    for t in texts:
        tl = t.strip().lower()
        # Must be short group/section chrome — not a long EPG title
        if len(t) > 48 or " | " in t or re.search(r"\d{1,2}:\d{2}", t):
            continue
        if "max" in tl:
            continue
        if tl in aliases:
            scored.append((100, t))
            continue
        if tl.startswith("-------") and "us sports" in tl:
            scored.append((90, t))
            continue
        if tl.endswith("section") and "us sports" in tl:
            scored.append((95, t))
    if not scored:
        return None
    return max(scored, key=lambda x: x[0])[1]


# Grid children that prove US SPORTS — never US ENTERTAINMENT (BBC/AWE/…) or All.
_US_SPORTS_CHILD_MARKERS = (
    "US: ESPN",
    "US: ESPN 2",
    "US: ESPN2",
    "US: ESPNEWS",
    "US: CBS SPORTS",
    "US: NBC SPORTS",
    "US: FOX SPORTS",
    "US: MLB NETWORK",
    "US: NBA TV",
    "US: NFL NETWORK",
    "US: GOLF",
    "US: TENNIS",
    "US: DAZN",
    "US: COURT SPORTS",
    "US: CHICAGO SPORTS",
    "US: DETROIT SPORTS",
)


def _section_open_confirmed(texts: list[str], section: str) -> bool:
    """True only when the *grid* shows the parent group, not merely the left-rail label."""
    want = re.sub(r"\s+SECTION$", "", section.strip(), flags=re.I).upper()
    dashed = f"-------{want}-------"
    joined_u = " | ".join(texts).upper()
    for t in texts:
        tl = t.strip()
        tu = tl.upper()
        if tu == dashed or tu == f"-------{want} SECTION-------":
            return True
    if want == "US SPORTS":
        # Reject Entertainment / other US * parents mistaken for Sports.
        if _wrong_us_parent(texts) and "US SPORTS" not in texts:
            return False
        if "US ENTERTAINMENT" in texts and "US SPORTS" not in texts:
            return False
        # Only sports children count — bare ``US:`` hits Entertainment too.
        for m in _US_SPORTS_CHILD_MARKERS:
            if m.upper() in joined_u:
                return True
        return False
    return False


def _still_on_wrong_locals(texts: list[str]) -> bool:
    """CBS/NBC/FOX DMA grid or wrong US * parent — Sports open did not stick."""
    joined = " | ".join(texts[:40]).upper()
    if "US: ESPN" in joined or "-------US SPORTS-------" in joined:
        return False
    if _wrong_us_parent(texts):
        return True
    markers = (
        "CBS LOCALS",
        "NBC LOCALS",
        "FOX LOCALS",
        "ABC LOCALS",
        "| CBS -",
        "| NBC -",
        "| FOX -",
        "| ABC -",
        "US ENTERTAINMENT",
        "-------US ENTERTAINMENT-------",
    )
    return any(m in joined for m in markers)


def atom_open_section(
    instance: dict[str, Any],
    obs: dict[str, Any],
    *,
    section: str,
    root: Path,
    traj_id: str,
    step: int,
) -> dict[str, Any]:
    """Find parent on left rail or dashed header, tap the *label* (not a huge parent), verify children."""
    probe = root / "work" / "streamers_nav" / traj_id
    ui = obs["ui"]
    texts = obs["texts"]
    found = None
    mode = "rail"
    negs: list[str] = []
    # Pass A: dedicated left-rail scroll (NFL packs bury US SPORTS below the fold).
    scrolled = scroll_left_rail_for_label(
        instance,
        label=re.sub(r"\s+SECTION$", "", section.strip(), flags=re.I),
        probe=probe,
        tag=f"{step:02d}_open_section",
        max_swipes=30,
    )
    ui = scrolled.get("ui") or ui
    texts = list(scrolled.get("texts") or _texts(ui))
    found = _match_section_label(texts, section)
    if found:
        mode = "rail_or_visible"
    # Pass B: scroll main channel grid for dashed headers / flat US: list
    if not found:
        mode = "grid_header"
        empty_streak = 0
        for attempt in range(36):
            texts = _texts(ui)
            if _dump_texts_empty(texts):
                empty_streak += 1
                if empty_streak >= 2:
                    return {
                        "ok": False,
                        "op": "open_section",
                        "section": section,
                        "error": "consecutive_empty_dumps",
                        "empty_streak": empty_streak,
                        "attempt": attempt,
                        "lesson": (
                            "uiautomator returned empty hierarchy twice during section open — "
                            "abort route (do not hunt under blind dumps)."
                        ),
                    }
            else:
                empty_streak = 0
            found = _match_section_label(texts, section)
            if found:
                break
            # Only accept sports children / -------US SPORTS------- — never Entertainment.
            if _section_open_confirmed(texts, section) and not _still_on_wrong_locals(texts):
                found = section
                mode = "sports_children_visible"
                break
            negs = [t for t in texts if "MAX SPORTS" in t.upper() or "AMZN" in t.upper()][:4]
            # Prefer left-rail swipes while a wrong US * parent is selected.
            if _wrong_us_parent(texts):
                adb(instance, ["shell", "input", "swipe", "300", "720", "300", "380", "420"])
            else:
                adb(instance, ["shell", "input", "swipe", "900", "820", "900", "280", "480"])
            time.sleep(0.45)
            ui = _dump_ui_soft(instance, probe / f"{step:02d}_grid_scroll_{attempt}.xml")
    if not found:
        seen = [
            t
            for t in texts
            if "SECTION" in t.upper()
            or t.startswith("US ")
            or re.fullmatch(r"-{3,}.+-{3,}", t.strip())
            or t.upper() in {"MAX SPORTS", "AMAZON SPORTS"}
        ][:24]
        return {
            "ok": False,
            "op": "open_section",
            "section": section,
            "error": "section_not_found",
            "seen_sections": seen,
            "lesson": (
                f"Could not find {section}. Grid often shows -------GROUP------- headers "
                f"(saw MAX SPORTS packs — those are the WRONG feed for national ads). "
                f"Playlist may lack a US SPORTS group; confirm in Streamers groups list."
            ),
        }

    # Already inside the parent (US: ESPN rows visible) — do not retap the rail.
    texts_now = _texts(ui)
    if _section_open_confirmed(texts_now, section) and not _still_on_wrong_locals(texts_now):
        return {
            "ok": True,
            "op": "open_section",
            "section": section,
            "matched_label": found,
            "mode": mode if mode.startswith("sports") else "already_open",
            "skipped_negatives": negs,
            "tap": None,
            "verified_children": True,
            "lesson": (
                f"Inside {section} (sports children / header visible) — skipped rail retap. "
                "Pick US: ESPN next. Not Entertainment / All."
            ),
        }

    confirmed = False
    last_tap: dict[str, Any] | None = None
    after_texts: list[str] = []
    empty_streak = 0
    for attempt in range(4):
        last_tap = _tap_text(instance, ui, found, contains=False) or _tap_text(
            instance, ui, found, contains=True
        )
        time.sleep(1.4)
        ui = _dump_ui_soft(instance, probe / f"{step:02d}_section_verify_{attempt}.xml")
        after_texts = _texts(ui)
        if _dump_texts_empty(after_texts):
            empty_streak += 1
            if empty_streak >= 2:
                return {
                    "ok": False,
                    "op": "open_section",
                    "section": section,
                    "matched_label": found,
                    "error": "consecutive_empty_dumps",
                    "empty_streak": empty_streak,
                    "tap": last_tap,
                    "lesson": (
                        "Empty dumps after section tap — abort (Bug 2 cascade). "
                        "Do not keep hunting under blind UI."
                    ),
                }
        else:
            empty_streak = 0
        after_place = classify_place(after_texts)["place"]
        # Accidental player open (huge parent hit-target) — Back, then retap the label.
        if after_place in {"player", "player_or_blank"} or (
            "TV guide" in after_texts and "FHD" in after_texts
        ):
            atom_back(instance)
            time.sleep(0.8)
            ui = _dump_ui_soft(instance, probe / f"{step:02d}_section_back_player_{attempt}.xml")
            after_texts = _texts(ui)
        if _section_open_confirmed(after_texts, section) and not _still_on_wrong_locals(after_texts):
            confirmed = True
            break
        # Rail label visible but grid unchanged — nudge and retap (tight target via _tap_text).
        adb(instance, ["shell", "input", "swipe", "160", "500", "160", "350", "250"])
        time.sleep(0.35)
        ui = _dump_ui_soft(instance, probe / f"{step:02d}_section_retarget_{attempt}.xml")
        found = _match_section_label(_texts(ui), section) or found

    if not confirmed:
        return {
            "ok": False,
            "op": "open_section",
            "section": section,
            "matched_label": found,
            "mode": mode,
            "error": "section_tap_did_not_open_children",
            "tap": last_tap,
            "after_head": after_texts[:24],
            "lesson": (
                f"Tapped '{found}' but grid still looks like locals/other group — "
                f"not inside {section}. Parent open must show US: children (or -------{section}-------), "
                f"not only the left-rail label."
            ),
        }
    return {
        "ok": True,
        "op": "open_section",
        "section": section,
        "matched_label": found,
        "mode": mode,
        "skipped_negatives": negs,
        "tap": last_tap,
        "verified_children": True,
        "lesson": (
            f"Opened '{found}' via {mode} and verified parent children. "
            f"Section headers look like -------US SPORTS-------; rail taps must hit the label, "
            f"not the center of a huge clickable parent."
        ),
    }


def atom_open_row(
    instance: dict[str, Any],
    obs: dict[str, Any],
    *,
    match: str,
    prefer: list[str] | None = None,
    reject: list[str] | None = None,
    avoid_substr: list[str] | None = None,
    root: Path,
    traj_id: str,
    step: int,
    visible_only: bool = False,
    require_sports_parent: bool = True,
) -> dict[str, Any]:
    probe = root / "work" / "streamers_nav" / traj_id
    ui = obs["ui"]
    best: tuple[int, str] | None = None
    rejected: list[str] = []
    seen_espn: list[str] = []

    def _score_visible(dump_ui: Any) -> tuple[int, str] | None:
        texts = _texts(dump_ui)
        scored: list[tuple[int, str]] = []
        for t in texts:
            if "espn" in t.lower():
                seen_espn.append(t)
            s = score_row(
                t,
                match=match,
                prefer=prefer,
                reject=reject,
                avoid_substr=avoid_substr,
            )
            if s <= -10_000 and match.lower() in t.lower():
                rejected.append(t)
            elif s >= 10:
                scored.append((s, t))
        return max(scored, key=lambda x: x[0]) if scored else None

    texts0 = _texts(ui)
    wrong = _wrong_us_parent(texts0)
    if require_sports_parent and wrong and not _section_open_confirmed(texts0, "US SPORTS"):
        return {
            "ok": False,
            "op": "open_row",
            "match": match,
            "error": "wrong_parent",
            "wrong_parent": wrong,
            "lesson": (
                f"On {wrong}, not US SPORTS — refuse to hunt '{match}' here. "
                "Open the US SPORTS parent first."
            ),
        }

    # Already on screen (common after a stuck guide with ESPN visible) — pick it.
    # Do NOT scroll-to-top first; that throws the visible row off-screen.
    best = _score_visible(ui)
    if not best and not visible_only:
        # Jump toward top of US SPORTS (A…) so ESPN is not skipped after a bottom landing.
        for i in range(6):
            adb(instance, ["shell", "input", "swipe", "900", "280", "900", "820", "450"])
            time.sleep(0.35)
            ui = _dump_ui_soft(instance, probe / f"{step:02d}_grid_top_{i}.xml")
            best = _score_visible(ui)
            if best:
                break
    if not best and not visible_only:
        for attempt in range(24):
            # Scroll channel grid upward (toward Z) looking for the child.
            adb(instance, ["shell", "input", "swipe", "900", "820", "900", "320", "500"])
            time.sleep(0.5)
            ui = _dump_ui_soft(instance, probe / f"{step:02d}_grid_scroll_{attempt}.xml")
            best = _score_visible(ui)
            if best:
                break
    if not best:
        return {
            "ok": False,
            "op": "open_row",
            "match": match,
            "error": "no_allowed_row",
            "rejected_examples": rejected[:8],
            "seen_espn": seen_espn[:12],
            "lesson": (
                f"No allowed row matching {match}. Rejected pack titles (e.g. MAX SPORTS) stay "
                "out of the national-linear corpus — keep scrolling US Sports or fix playlist."
                + (f" Saw ESPN-ish: {seen_espn[:6]}" if seen_espn else " No ESPN* text in any scroll dump.")
            ),
        }
    score, title = best
    tapped = _tap_text(instance, ui, title, contains=False) or _tap_text(instance, ui, title, contains=True)
    time.sleep(0.6)
    return {
        "ok": bool(tapped),
        "op": "open_row",
        "match": match,
        "chosen": title,
        "score": score,
        "rejected_examples": rejected[:8],
        "tap": tapped,
        "lesson": (
            f"Chose '{title}' (score={score}). Reject list keeps MAX SPORTS / AMZN out when "
            "the goal is national US linear commercials."
        ),
    }


def run_atom(
    op: str,
    instance: dict[str, Any],
    obs: dict[str, Any],
    params: dict[str, Any],
    *,
    root: Path,
    traj_id: str,
    step: int,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = state if state is not None else {}
    if op == "ensure_guide":
        return atom_ensure_guide(instance, obs, root, traj_id, step)
    if op == "tap_left_nav":
        return atom_tap_left_nav(instance, obs, label=str(params.get("label") or "TV"))
    if op == "tap_all_channels":
        return atom_tap_all_channels(
            instance, obs, root=root, traj_id=traj_id, step=step
        )
    if op == "open_section":
        result = atom_open_section(
            instance,
            obs,
            section=assert_parent_group(str(params.get("section") or PARENT_US_SPORTS), root),
            root=root,
            traj_id=traj_id,
            step=step,
        )
        if result.get("ok") and result.get("matched_label"):
            state["section_failed"] = False
            state["section_label"] = result.get("matched_label")
        elif params.get("optional"):
            state["section_failed"] = True
            result = {
                **result,
                "ok": True,
                "optional_failed": True,
                "lesson": (result.get("lesson") or "")
                + " OPTIONAL step failed — will try search_channels next (still reject MAX SPORTS).",
            }
        else:
            state["section_failed"] = True
        return result
    if op == "search_channels":
        # Always run search when section missing OR when we need Channels-tab pick
        if (
            params.get("fallback_if_section_failed")
            and not state.get("section_failed")
            and state.get("section_label")
        ):
            return {
                "ok": True,
                "op": "search_channels",
                "skipped": True,
                "lesson": f"Section '{state.get('section_label')}' opened — skip search fallback.",
            }
        result = atom_search_channels(
            instance,
            obs,
            query=str(params.get("query") or "ESPN"),
            match=str(params.get("match") or "ESPN"),
            prefer=list(params.get("prefer") or []),
            reject=list(params.get("reject") or REJECT_NATIONAL_LINEAR),
            avoid_substr=list(params.get("avoid_substr") or []),
            root=root,
            traj_id=traj_id,
            step=step,
        )
        if result.get("chosen"):
            state["search_channels_chose"] = result["chosen"]
        return result
    if op == "open_row":
        if params.get("skip_if") == "search_channels_chose" and state.get("search_channels_chose"):
            return {
                "ok": True,
                "op": "open_row",
                "skipped": True,
                "chosen": state["search_channels_chose"],
                "lesson": "Row already chosen by search_channels — do not retap.",
            }
        return atom_open_row(
            instance,
            obs,
            match=str(params.get("match") or "ESPN"),
            prefer=list(params.get("prefer") or []),
            reject=list(params.get("reject") or REJECT_NATIONAL_LINEAR),
            avoid_substr=list(params.get("avoid_substr") or []),
            root=root,
            traj_id=traj_id,
            step=step,
        )
    if op == "keyevent_open":
        return atom_keyevent_open(instance)
    if op == "rematchimize":
        return atom_rematchimize(instance)
    if op == "back":
        return atom_back(instance)
    return {"ok": False, "op": op, "error": "unknown_atom"}


def run_route(
    route_id: str,
    *,
    instance_id: str = DEFAULT_INSTANCE,
    root: Path | None = None,
    open_player: bool = True,
    save_as: str | None = None,
) -> dict[str, Any]:
    """Execute a named route atom-by-atom; log a full learning trajectory."""
    root = ensure_data_layout(root)
    routes = load_routes(root)
    route = (routes.get("routes") or {}).get(route_id)
    if not route:
        return {"ok": False, "error": f"unknown_route:{route_id}", "known": list((routes.get("routes") or {}))}
    if route.get("deprecated") or route.get("reject"):
        return {
            "ok": False,
            "error": "route_deprecated",
            "route": route,
            "lesson": route.get("why") or "This route is a negative example — do not run for capture.",
        }

    traj_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    instance = _ensure_instance(instance_id, root)
    steps_out: list[dict[str, Any]] = []
    atoms = list(route.get("atoms") or [])
    if not open_player:
        atoms = [a for a in atoms if a.get("op") != "keyevent_open"]

    obs = observe(instance, root=root, traj_id=traj_id, step=0, tag="start")
    _append(
        {
            "kind": "traj_start",
            "traj_id": traj_id,
            "route_id": route_id,
            "goal": route.get("goal"),
            "feed": route.get("feed"),
            "instance_id": instance_id,
            "utc": _now(),
            "place": obs["place"],
            "texts_head": obs["texts_head"],
            "frame": obs["frame"],
            "dump_ok": obs.get("dump_ok"),
            "dump_reason": obs.get("dump_reason"),
            "lesson": f"Start route {route_id}: {route.get('why')}",
        },
        root,
    )

    ok = True
    state: dict[str, Any] = {}
    child = str(route.get("child") or "")
    player_places = {"player", "player_chrome", "player_fullscreen", "player_or_blank"}

    # Dump circuit / soft-fail — do not walk the rail on invented emptiness.
    if obs.get("place") == "dump_dead" or obs.get("dump_ok") is False:
        summary = {
            "ok": False,
            "traj_id": traj_id,
            "route_id": route_id,
            "error": "dump_dead",
            "dump_ok": False,
            "dump_reason": obs.get("dump_reason"),
            "place": obs.get("place"),
            "lesson": "uiautomator dump dead at route start — refused nav hunt.",
            "atoms": [],
        }
        _append({"kind": "traj_end", **summary, "utc": _now()}, root)
        return summary

    # Only short-circuit when already inside US SPORTS with the child on-screen.
    # Never scroll-hunt ESPN under US ENTERTAINMENT / All — that is the stuck loop.
    if (
        open_player
        and child
        and obs.get("place") not in player_places
        and _section_open_confirmed(list(obs.get("texts") or []), "US SPORTS")
    ):
        open_atom = next((a for a in atoms if a.get("op") == "open_row"), {}) or {}
        quick = atom_open_row(
            instance,
            obs,
            match=str(open_atom.get("match") or child),
            prefer=list(open_atom.get("prefer") or route.get("prefer") or [child]),
            reject=list(open_atom.get("reject") or route.get("reject") or REJECT_NATIONAL_LINEAR),
            avoid_substr=list(open_atom.get("avoid_substr") or route.get("avoid_substr") or []),
            root=root,
            traj_id=traj_id,
            step=1,
            visible_only=True,
            require_sports_parent=True,
        )
        if quick.get("ok") and quick.get("chosen"):
            opened = atom_keyevent_open(instance)
            after = observe(instance, root=root, traj_id=traj_id, step=2, tag="post_pick_visible")
            steps_out.append(
                {
                    "kind": "atom",
                    "traj_id": traj_id,
                    "route_id": route_id,
                    "step": 1,
                    "op": "pick_visible_child",
                    "place_before": obs["place"],
                    "place_after": after["place"],
                    "ok": True,
                    "chosen": quick.get("chosen"),
                    "lesson": (
                        f"Child '{quick.get('chosen')}' already on guide — tapped + d-pad center. "
                        "Skipped parent walk."
                    ),
                    "utc": _now(),
                }
            )
            _append(steps_out[-1], root)
            if after["place"] not in player_places:
                rem = atom_rematchimize(instance)
                after = observe(instance, root=root, traj_id=traj_id, step=3, tag="post_rematchimize")
                steps_out.append(
                    {
                        "kind": "atom",
                        "traj_id": traj_id,
                        "route_id": route_id,
                        "step": 2,
                        "op": "rematchimize",
                        "place_after": after["place"],
                        "ok": bool(rem.get("ok")),
                        "lesson": rem.get("lesson"),
                        "utc": _now(),
                    }
                )
                _append(steps_out[-1], root)
            if after["place"] in player_places:
                atoms = []  # short-circuit full route
                obs = after
            else:
                steps_out.clear()
                # Fall through to full route — visible pick did not stick.
                obs = observe(instance, root=root, traj_id=traj_id, step=0, tag="restart_after_pick")

    for i, atom in enumerate(atoms, start=1):
        op = str(atom.get("op"))
        # Re-observe before every atom (stale dump = wrong tap).
        obs = observe(instance, root=root, traj_id=traj_id, step=i, tag=f"pre_{op}")
        result = run_atom(
            op, instance, obs, atom, root=root, traj_id=traj_id, step=i, state=state
        )
        time.sleep(0.3)
        after = observe(instance, root=root, traj_id=traj_id, step=i, tag=f"post_{op}")
        row = {
            "kind": "atom",
            "traj_id": traj_id,
            "route_id": route_id,
            "step": i,
            "op": op,
            "params": {k: v for k, v in atom.items() if k != "op"},
            "place_before": obs["place"],
            "place_after": after["place"],
            "texts_before": obs["texts_head"],
            "texts_after": after["texts_head"],
            "frame_before": obs["frame"],
            "frame_after": after["frame"],
            "xml_before": obs["xml"],
            "xml_after": after["xml"],
            "dump_ok_before": obs.get("dump_ok"),
            "dump_ok_after": after.get("dump_ok"),
            "dump_reason_before": obs.get("dump_reason"),
            "dump_reason_after": after.get("dump_reason"),
            "result": {k: v for k, v in result.items() if k != "tap"},
            "ok": bool(result.get("ok")),
            "lesson": result.get("lesson"),
            "utc": _now(),
        }
        _append(row, root)
        steps_out.append(row)
        if after.get("place") == "dump_dead" or after.get("dump_ok") is False:
            ok = False
            row["ok"] = False
            row["error"] = "dump_dead"
            break
        if not result.get("ok"):
            ok = False
            break
        obs = after

    final_place = (steps_out[-1]["place_after"] if steps_out else obs["place"])
    accept = list(route.get("accept_place") or ["player"])
    # Row selected but still on section grid = channel not opened. Press center, then long-Back.
    if ok and open_player and final_place in {"section_grid", "guide", "guide_rail", "section_grid"}:
        for retry in range(2):
            adb(instance, ["shell", "input", "keyevent", "23"])
            time.sleep(1.4)
            after = observe(
                instance, root=root, traj_id=traj_id, step=100 + retry, tag=f"open_retry_{retry}"
            )
            final_place = after["place"]
            steps_out.append(
                {
                    "kind": "atom",
                    "traj_id": traj_id,
                    "route_id": route_id,
                    "step": 100 + retry,
                    "op": "keyevent_open_retry",
                    "place_after": final_place,
                    "ok": final_place in player_places,
                    "lesson": "Selected row was still on guide — d-pad center again to enter player.",
                    "utc": _now(),
                }
            )
            if final_place in player_places:
                break
        if final_place not in player_places:
            rem = atom_rematchimize(instance)
            after = observe(instance, root=root, traj_id=traj_id, step=110, tag="rematchimize_retry")
            final_place = after["place"]
            steps_out.append(
                {
                    "kind": "atom",
                    "traj_id": traj_id,
                    "route_id": route_id,
                    "step": 110,
                    "op": "rematchimize",
                    "place_after": final_place,
                    "ok": final_place in player_places,
                    "lesson": rem.get("lesson"),
                    "utc": _now(),
                }
            )
            _append(steps_out[-1], root)
    if ok and open_player and final_place not in accept and "player" in accept:
        # Accept late player chrome; do NOT treat bare section_grid as success.
        ok = final_place in accept or final_place in player_places

    shortcut = None
    if ok and save_as:
        chosen = None
        for s in reversed(steps_out):
            if s.get("op") == "open_row":
                chosen = (s.get("result") or {}).get("chosen")
                break
        shortcut = save_shortcut(
            shortcut_id=save_as,
            search_query="",
            channel_title=str(chosen or "ESPN"),
            group="US SPORTS SECTION",
            kind="sports_linear",
            notes=f"route={route_id} feed={route.get('feed')} traj={traj_id}",
            root=root,
        )
        # Stamp method as section route for learners
        data = load_shortcuts(root)
        if save_as in data["shortcuts"]:
            data["shortcuts"][save_as]["open"] = {
                "method": "section_route",
                "route_id": route_id,
                "reject": list(REJECT_NATIONAL_LINEAR),
            }
            data["shortcuts"][save_as]["feed"] = route.get("feed")
            data["shortcuts"][save_as]["deprecated"] = False
            save_shortcuts(data, root)

    summary = {
        "ok": ok,
        "traj_id": traj_id,
        "route_id": route_id,
        "goal": route.get("goal"),
        "feed": route.get("feed"),
        "instance_id": instance_id,
        "final_place": final_place,
        "steps": len(steps_out),
        "atoms": steps_out,
        "shortcut": shortcut,
        "work_dir": str(root / "work" / "streamers_nav" / traj_id),
        "log": str(log_path(root)),
        "lesson": route.get("why"),
    }
    _append({"kind": "traj_end", **{k: v for k, v in summary.items() if k != "atoms"}, "utc": _now()}, root)
    write_atlas(root)
    return summary


def flag_bad_shortcuts(root: Path | None = None) -> dict[str, Any]:
    """Mark MAX SPORTS ESPN etc. as negative examples for the model."""
    root = ensure_data_layout(root)
    data = load_shortcuts(root)
    changed = []
    for sid, row in list((data.get("shortcuts") or {}).items()):
        title = f"{row.get('channel_title')} {row.get('group')}".lower()
        if "max sports" in title or sid.upper() in {"ESPN_MAX"}:
            row["deprecated"] = True
            row["feed"] = "max_sports"
            row["reject_for"] = ["national_linear", "national_ads_corpus"]
            row["notes"] = (
                (row.get("notes") or "")
                + " | NEGATIVE EXAMPLE: Max Sports pack — wrong commercials for national linear. Use ESPN_US section route."
            ).strip(" |")
            data["shortcuts"][sid] = row
            changed.append(sid)
    # Policy for learners
    pol = data.setdefault("policy", {})
    pol["linear_channels"] = (
        "Section-first: All channels → US * SECTION / US SPORTS SECTION → row. "
        "Never use MAX SPORTS ESPN for national-ad corpus."
    )
    pol["events"] = "Search team/show → Channels card (NFL 01…) → keyevent 23."
    pol["avoid"] = list(
        dict.fromkeys(
            list(pol.get("avoid") or [])
            + [
                "MAX SPORTS ESPN for national commercials",
                "Search-first for linear ESPN/FOX Sports nets",
                "Fixed x,y taps from an old dump",
            ]
        )
    )
    save_shortcuts(data, root)
    load_routes(root)  # ensure routes file exists
    return {"ok": True, "flagged": changed, "shortcuts": str(load_shortcuts.__doc__)}


def write_atlas(root: Path | None = None) -> Path:
    """Human + model readable board of places, routes, recent lessons."""
    root = ensure_data_layout(root)
    path = atlas_path(root)
    routes = load_routes(root)
    recent: list[dict[str, Any]] = []
    log = log_path(root)
    if log.is_file():
        lines = log.read_text(encoding="utf-8").splitlines()[-80:]
        for line in lines:
            try:
                recent.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    lines = [
        "# Streamers nav atlas (learning)",
        "",
        f"Updated `{_now()}`",
        "",
        "## How the open model should think",
        "",
        "1. **Observe** — fresh uiautomator dump + still; classify `place`.",
        "2. **Act** — one atom only (tap text from *this* dump, or keyevent 23/4).",
        "3. **Re-observe** — log `place_before → atom → place_after` + lesson.",
        "4. **Routes** — section-first for linear; search for events.",
        "5. **Reject** — MAX SPORTS / AMZN empty slots when goal is national US ads.",
        "",
        "## Places",
        "",
        "| Place | Meaning |",
        "|---|---|",
        "| `guide_rail` | All channels / Favorites / SECTION list |",
        "| `section_grid` | Inside a SECTION; channel rows |",
        "| `search_ui` | Search results tabs |",
        "| `player` | Tuned picture + chrome |",
        "| `login` / `streamers_welcome` | Need Salvation |",
        "| `bluestacks_home` | Outside Streamers |",
        "",
        "## Routes",
        "",
        "| Id | Feed | Deprecated | Why |",
        "|---|---|---|---|",
    ]
    for rid, r in (routes.get("routes") or {}).items():
        lines.append(
            f"| `{rid}` | {r.get('feed')} | {r.get('deprecated') or r.get('reject') or False} | {r.get('why')} |"
        )
    lines.extend(["", "## Recent atom lessons", ""])
    for row in recent:
        if row.get("kind") != "atom":
            continue
        lines.append(
            f"- `{row.get('traj_id')}` step {row.get('step')} "
            f"**{row.get('place_before')}** → `{row.get('op')}` → **{row.get('place_after')}** "
            f"— {row.get('lesson')}"
        )
    lines.extend(
        [
            "",
            "## Commands",
            "",
            "```powershell",
            "python -m tools.windows_lab nav routes",
            "python -m tools.windows_lab nav teach --route ESPN_US --save-as ESPN_US",
            "python -m tools.windows_lab nav atlas",
            "```",
            "",
            f"Trajectories: `{log_path(root)}`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Atomic Streamers nav (learning trajectories)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("routes", help="List routes + ensure defaults")
    t = sub.add_parser("teach", help="Run a route; log frames/dumps/lessons")
    t.add_argument("--route", required=True)
    t.add_argument("--instance", default=DEFAULT_INSTANCE)
    t.add_argument("--save-as", default=None)
    t.add_argument("--no-open", action="store_true", help="Stop before keyevent 23")
    sub.add_parser("atlas", help="Rewrite NAV_ATLAS.md")
    sub.add_parser("flag-bad", help="Deprecate MAX SPORTS shortcuts as negatives")
    c = sub.add_parser("classify", help="Classify current place on an instance")
    c.add_argument("--instance", default=DEFAULT_INSTANCE)

    args = p.parse_args(argv)
    if args.cmd == "routes":
        data = load_routes()
        print(json.dumps(data, indent=2))
        return 0
    if args.cmd == "flag-bad":
        print(json.dumps(flag_bad_shortcuts(), indent=2))
        write_atlas()
        return 0
    if args.cmd == "atlas":
        path = write_atlas()
        print(json.dumps({"ok": True, "atlas": str(path)}, indent=2))
        return 0
    if args.cmd == "classify":
        root = ensure_data_layout()
        inst = _ensure_instance(args.instance, root)
        obs = observe(inst, root=root, traj_id="classify", step=0, tag="now")
        print(
            json.dumps(
                {
                    "place": obs["place"],
                    "place_meta": obs["place_meta"],
                    "texts_head": obs["texts_head"],
                    "frame": obs["frame"],
                },
                indent=2,
            )
        )
        return 0
    if args.cmd == "teach":
        report = run_route(
            args.route,
            instance_id=args.instance,
            open_player=not args.no_open,
            save_as=args.save_as,
        )
        # Compact stdout for chat; full atoms on disk
        slim = {k: v for k, v in report.items() if k != "atoms"}
        slim["atom_ops"] = [
            {
                "step": a["step"],
                "op": a["op"],
                "place_before": a["place_before"],
                "place_after": a["place_after"],
                "ok": a["ok"],
                "lesson": a.get("lesson"),
                "chosen": (a.get("result") or {}).get("chosen"),
            }
            for a in report.get("atoms") or []
        ]
        print(json.dumps(slim, indent=2, default=str))
        return 0 if report.get("ok") else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
