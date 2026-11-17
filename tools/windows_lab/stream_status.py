"""Per-instance stream uptime board — what's up/down, why, and root cause.

Joins heartbeat, channel opens, recover, and job locks into one transparent
board so we always know which player is healthy and what broke it.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout

BOARD_MD = "STREAM_STATUS.md"
BOARD_JSON = "stream_status.json"
STATE_JSON = "stream_status_state.json"

# Stable root-cause classes for boards / farm_run.extra.root_cause
ROOT_CAUSES = (
    "ok",
    "open_failed",
    "wrong_channel",
    "duplicate_stream",
    "pluto_or_pack_epg",
    "picture_bad",
    "audio_lag",
    "audio_dead",
    "streamers_down",
    "guide_stuck",
    "recover_exhausted",
    "capture_dead",
    "unknown",
)

# ABC last — recovery used to default both clones to WSB and collapse the fleet.
FILLER_NETWORK_ORDER = ("FOX", "CBS", "NBC", "ABC")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def state_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / STATE_JSON


def board_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / BOARD_MD


def board_json_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / BOARD_JSON


def load_state(root: Path | None = None) -> dict[str, Any]:
    path = state_path(root)
    if not path.is_file():
        return {"version": 1, "instances": {}, "events_tail": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "instances": {}, "events_tail": []}


def save_state(state: dict[str, Any], root: Path | None = None) -> Path:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return path


def normalize_program_key(text: str | None) -> str | None:
    """Collapse chrome/program titles to a fleet-wide identity key.

    'College Football : Missouri at Georgia ᴸᶦᵛᵉ' → 'missouri at georgia'
    """
    import re

    t = (text or "").strip().lower()
    if not t:
        return None
    t = re.sub(r"[\U0001d400-\U0001d7ff]+", "", t)  # math/superscript badges
    t = t.replace("ᴸᶦᵛᵉ", "").replace("live", "")
    # Drop network/local prefixes when present.
    t = re.sub(r"^[a-z]{2}\s*\|\s*[^|]+\|\s*(abc|cbs|nbc|fox)\s*[- ]\s*[a-z0-9-]+\s*", "", t)
    if ":" in t:
        t = t.split(":", 1)[-1]
    t = re.sub(r"\b(college football|nfl|nba|nhl|mlb)\b", "", t)
    t = re.sub(r"[^a-z0-9\s@vsversus\-]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) < 6:
        return None
    return t


def identity_from_texts(texts: list[str] | None) -> dict[str, Any]:
    """Pull channel number / local / program identity from a UI dump.

    Prefer the program title that appears *before* the station row so guide
    neighbors (later in the dump) do not steal the fleet key.
    """
    import re

    from .us_locals import parse_local_title

    texts = list(texts or [])
    out: dict[str, Any] = {}
    station_idx: int | None = None
    for i, t in enumerate(texts):
        if re.fullmatch(r"\d{3,5}", t.strip()):
            out.setdefault("channel_number", int(t.strip()))
        parsed = parse_local_title(t)
        if parsed:
            if "selected_title" not in out:
                station_idx = i
            out.setdefault("selected_title", parsed.get("title") or t)
            out.setdefault("network", parsed.get("network"))
            out.setdefault("calls", parsed.get("calls"))
            out.setdefault("city", parsed.get("city"))
            out.setdefault("market", parsed.get("city"))
    # Playing program is almost always above the station title in chrome.
    scan = texts[: station_idx if station_idx is not None else len(texts)]
    for t in scan:
        pk = normalize_program_key(t)
        if pk and (" at " in pk or " vs " in pk or " versus " in pk or "@" in pk):
            out.setdefault("program_key", pk)
            out.setdefault("program_title", t)
            break
    if not out.get("program_key"):
        for t in texts:
            pk = normalize_program_key(t)
            if pk and (" at " in pk or " vs " in pk or " versus " in pk or "@" in pk):
                out["program_key"] = pk
                out["program_title"] = t
                break
    if out.get("selected_title") and not out.get("program_key"):
        out["program_key"] = normalize_program_key(str(out["selected_title"]))
    return out


def fleet_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """All tracked instances with enough identity to compare."""
    state = load_state(root)
    rows = []
    for iid, row in (state.get("instances") or {}).items():
        r = dict(row)
        r["instance_id"] = iid
        if not r.get("program_key") and r.get("selected_title"):
            r["program_key"] = normalize_program_key(str(r.get("selected_title")))
        rows.append(r)
    return rows


def _fleet_peer_gate(root: Path | None = None) -> dict[str, Any]:
    """Registry + running engines so parked clones cannot phantom-dup the live pair."""
    enabled: dict[str, bool] = {}
    try:
        from .instances import list_instances

        for row in list_instances(root):
            iid = str(row.get("id") or "")
            if iid:
                enabled[iid] = bool(row.get("enabled", True))
    except Exception:
        pass
    running: set[str] | None = None
    try:
        from .instances import list_running_engines

        got = set(list_running_engines() or [])
        # Empty list usually means ADB/BlueStacks probe flake in unit tests — ignore.
        running = got if got else None
    except Exception:
        running = None
    locked: set[str] = set()
    try:
        from .locks import get_lock

        for iid in enabled:
            if get_lock("streamers", iid, root=root):
                locked.add(iid)
    except Exception:
        pass
    return {"enabled": enabled, "running": running, "locked": locked}


def _peer_counts_for_dup(iid: str, gate: dict[str, Any]) -> bool:
    """Parked clones are out. Not-running only drops peers we know are enabled-but-off."""
    enabled = gate.get("enabled") or {}
    if iid in enabled and not enabled[iid]:
        return False
    running = gate.get("running")
    locked = gate.get("locked") or set()
    # Only apply the running filter when the registry explicitly enables the peer.
    # Unknown ids (unit tests / ephemeral) still count via identity_live.
    if (
        running is not None
        and iid in enabled
        and enabled[iid]
        and iid not in running
        and iid not in locked
    ):
        return False
    return True


def find_duplicate_streams(
    instance_id: str,
    identity: dict[str, Any] | None = None,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Detect another live player on the same number, calls, network, or game.

    Same national network (two ABCs) is a waste even with different affiliates —
    booth ads and games share the feed. ``program_key`` alone is not enough:
    late-news takes often have null keys while both sit on WSB.

    Parked (``enabled=false``) and not-running clones are ignored so ghost
    ``Nougat32_3`` rows cannot force live retunes.
    """
    identity = dict(identity or {})
    me = None
    others = []
    for row in fleet_rows(root):
        if row.get("instance_id") == instance_id:
            me = row
        else:
            others.append(row)
    if me:
        for k in ("channel_number", "calls", "network", "program_key", "selected_title", "market"):
            if identity.get(k) is None and me.get(k) is not None:
                identity[k] = me.get(k)
    if not identity.get("program_key") and identity.get("selected_title"):
        identity["program_key"] = normalize_program_key(str(identity.get("selected_title")))

    gate = _fleet_peer_gate(root)
    conflicts: list[dict[str, Any]] = []
    my_num = identity.get("channel_number")
    my_calls = (identity.get("calls") or "").upper() or None
    my_prog = identity.get("program_key")
    my_net = (identity.get("network") or "").upper() or None
    for o in others:
        peer_id = str(o.get("instance_id") or "")
        if peer_id and not _peer_counts_for_dup(peer_id, gate):
            continue
        # Live peers only: up, capture-locked, or explicitly identity_live.
        # Failed opens clear identity_live so stale WSB/1353 cannot phantom-dup.
        if o.get("identity_live") is False:
            continue
        peer_live = bool(o.get("up") or o.get("locked") or o.get("identity_live") is True)
        if not peer_live:
            continue
        if not any(
            o.get(k)
            for k in ("selected_title", "calls", "channel_number", "program_key", "network")
        ):
            continue
        why = None
        peer_net = (o.get("network") or "").upper() or None
        if my_num is not None and o.get("channel_number") is not None and int(my_num) == int(o["channel_number"]):
            why = f"same_number:{my_num}"
        elif my_calls and (o.get("calls") or "").upper() == my_calls:
            why = f"same_calls:{my_calls}"
        elif my_prog and o.get("program_key") and my_prog == o.get("program_key"):
            # Same game on different affiliates (WXIA vs KTUU) is the main waste case.
            why = f"same_program:{my_prog}"
        elif my_net and peer_net and my_net == peer_net:
            # Two ABC takes with null program_key — still same national inventory.
            why = f"same_network:{my_net}"
        if why:
            conflicts.append(
                {
                    "instance_id": o.get("instance_id"),
                    "why": why,
                    "channel_number": o.get("channel_number"),
                    "calls": o.get("calls"),
                    "network": o.get("network"),
                    "selected_title": o.get("selected_title"),
                    "program_key": o.get("program_key"),
                }
            )
    return {
        "duplicate": bool(conflicts),
        "identity": identity,
        "conflicts": conflicts,
    }


def instance_default_network(instance_id: str) -> str:
    """Stable per-clone home net so concurrent fixes do not both land on ABC/WSB.

    Primary ``Nougat32`` → FOX; ``Nougat32_1`` → CBS; ``_2`` → NBC; ``_3`` → ABC.
    ABC is only a sticky default for higher-index clones, never the dual hot pair.
    """
    order = list(FILLER_NETWORK_ORDER)
    m = re.search(r"_(\d+)$", str(instance_id or ""))
    if m:
        return order[int(m.group(1)) % len(order)]
    # Bare primary engine id (Nougat32 / Tiramisu64)
    return order[0]


def pick_filler_network(
    instance_id: str,
    *,
    root: Path | None = None,
    preferred: str | None = None,
    exclude_networks: set[str] | None = None,
) -> str:
    """Choose Atlanta net not already used by another tracked stream.

    Different affiliate on the *same* network still carries the same national game —
    so we always rotate **network**, never just market.

    When the fleet has not stamped peers yet (both fixing at once), each instance
    still gets a distinct sticky default — not ABC-first for everyone.
    """
    used_nets: set[str] = set(x.upper() for x in (exclude_networks or set()))
    gate = _fleet_peer_gate(root)
    for row in fleet_rows(root):
        peer_id = str(row.get("instance_id") or "")
        if peer_id == instance_id:
            continue
        if peer_id and not _peer_counts_for_dup(peer_id, gate):
            continue
        if row.get("network"):
            used_nets.add(str(row["network"]).upper())
    sticky = instance_default_network(instance_id)
    order = [sticky] + [n for n in FILLER_NETWORK_ORDER if n != sticky]
    if preferred:
        pref = preferred.upper()
        if pref in FILLER_NETWORK_ORDER and pref not in used_nets:
            order = [pref] + [n for n in order if n != pref]
        elif pref in FILLER_NETWORK_ORDER:
            # Preferred net already taken — keep sticky/unused order, do not force ABC.
            order = [n for n in order if n != pref] + [pref]
    for net in order:
        if net not in used_nets:
            return net
    # All four taken — still rotate by sticky index so we don't collapse to ABC.
    return sticky


def probe_instance_identity(
    instance_id: str,
    *,
    root: Path | None = None,
    tap_for_chrome: bool = True,
) -> dict[str, Any]:
    """Live chrome → fleet identity stamp (number / calls / program_key)."""
    try:
        from .streamers_chrome import read_playing_channel

        chrome = read_playing_channel(instance_id, root=root, tap_for_chrome=tap_for_chrome)
        ident = identity_from_texts(list(chrome.get("texts") or []))
        if chrome.get("program_guess") and not ident.get("program_key"):
            ident["program_title"] = chrome.get("program_guess")
            ident["program_key"] = normalize_program_key(str(chrome.get("program_guess")))
        if ident:
            record(
                instance_id,
                event="identity_probe",
                ok=True,
                detail="desk/fleet chrome",
                selected_title=ident.get("selected_title"),
                network=ident.get("network"),
                calls=ident.get("calls"),
                market=ident.get("market") or ident.get("city"),
                channel_number=ident.get("channel_number"),
                program_key=ident.get("program_key"),
                program_title=ident.get("program_title"),
                emit_farm_run=False,
                root=root,
            )
        return {"ok": True, "identity": ident, "texts": (chrome.get("texts") or [])[:20]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "identity": {}}


def _keep_instance_for_program(
    instance_ids: list[str],
    *,
    root: Path | None = None,
) -> str:
    """Prefer locked/recording instance; else lowest Nougat index."""
    from .locks import get_lock

    scored: list[tuple[int, str]] = []
    for iid in instance_ids:
        score = 0
        lock = get_lock("streamers", iid, root=root)
        if lock:
            score += 100
            if "ON_AIR" not in str(lock.get("session_id") or ""):
                score += 20  # named job > filler
        row = next((r for r in fleet_rows(root) if r.get("instance_id") == iid), {})
        if row.get("up"):
            score += 5
        # Stable tie-break: Nougat32 before clones
        score -= len(iid)
        scored.append((score, iid))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[0][1]


def retune_to_next_priority(
    instance_id: str,
    *,
    root: Path | None = None,
    avoid_program_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Open next unused Atlanta net (then Alabama); verify different program + network."""
    from .heartbeat_fix import open_booth_local

    avoid = set(avoid_program_keys or set())
    tried: list[str] = []
    attempts: list[dict[str, Any]] = []
    last: dict[str, Any] = {}
    # Atlanta unused nets first, then Birmingham failover for the same nets.
    candidates: list[tuple[str, bool]] = []
    exclude: set[str] = set()
    for _ in range(4):
        net = pick_filler_network(instance_id, root=root, exclude_networks=exclude)
        if net in exclude:
            break
        exclude.add(net)
        candidates.append((net, False))
    for net, _ in list(candidates):
        candidates.append((net, True))  # Alabama failover pass

    for net, failover in candidates:
        tag = f"{net}{'/AL' if failover else ''}"
        if tag in tried:
            continue
        tried.append(tag)
        try:
            out = open_booth_local(
                instance_id, network=net, failover=failover, root=root
            )
        except Exception as exc:  # noqa: BLE001
            attempts.append({"net": tag, "ok": False, "error": str(exc)[:200]})
            last = {"ok": False, "error": str(exc)[:200], "tried_network": tag}
            continue
        last = dict(out)
        last["tried_network"] = tag
        title = str(out.get("selected_title") or out.get("channel_title") or "")
        pick = out.get("pick") or {}
        if not out.get("ok"):
            attempts.append({"net": tag, "ok": False, "error": out.get("error")})
            continue
        # Prefer open's own player dump (less neighbor bleed than a fresh tap).
        open_texts = list(out.get("player_texts") or [])
        ident = identity_from_texts(open_texts) if open_texts else {}
        if not ident.get("program_key") or not ident.get("network"):
            probed = probe_instance_identity(instance_id, root=root, tap_for_chrome=True)
            for k, v in (probed.get("identity") or {}).items():
                ident.setdefault(k, v)
        got_net = str(ident.get("network") or pick.get("network") or "").upper()
        title_u = title.upper()
        # Must actually land on the requested network (not stuck on prior affiliate).
        if got_net and got_net != net and net not in title_u:
            attempts.append(
                {
                    "net": tag,
                    "ok": False,
                    "error": f"landed_on_{got_net or title[:40]}",
                    "title": title,
                }
            )
            continue
        pk = ident.get("program_key")
        if not pk:
            # Playing row only — never station title.
            for t in open_texts:
                cand = normalize_program_key(t)
                if cand and (" at " in cand or " vs " in cand):
                    pk = cand
                    break
        if pk and pk in avoid:
            attempts.append(
                {
                    "net": tag,
                    "ok": False,
                    "error": "same_program",
                    "program_key": pk,
                    "title": title,
                }
            )
            continue
        market = (
            ident.get("market")
            or pick.get("market")
            or ("Birmingham" if failover else "Atlanta")
        )
        record(
            instance_id,
            event="channel_open",
            ok=True,
            detail=f"retune_next_priority:{tag}",
            selected_title=title or ident.get("selected_title"),
            network=net,
            calls=ident.get("calls") or pick.get("calls"),
            market=market,
            channel_number=ident.get("channel_number"),
            program_key=pk,
            program_title=ident.get("program_title"),
            via=out.get("via"),
            root_cause="ok",
            root=root,
        )
        return {
            "ok": True,
            "network": net,
            "failover": failover,
            "program_key": pk,
            "selected_title": title or ident.get("selected_title"),
            "open": out,
            "tried": tried,
            "attempts": attempts,
        }
    return {
        "ok": False,
        "error": "no_unique_program_network",
        "tried": tried,
        "attempts": attempts,
        "last": last,
    }


def enforce_unique_programs(
    *,
    root: Path | None = None,
    instance_ids: list[str] | None = None,
    execute: bool = True,
) -> dict[str, Any]:
    """Fleet rule: never two streams on the same game **or same network**.

    Keep the locked/primary player; retune others to the next unused Atlanta
    network. Late-news takes often have null ``program_key`` while both sit on
    ABC/WSB — network grouping catches that; program_key alone does not.
    """
    root = ensure_data_layout(root)
    from .instances import list_instances
    from .locks import get_lock

    streamer_rows = [
        r
        for r in list_instances(root)
        if r.get("source_kind", "streamers") == "streamers"
    ]
    enabled = {
        str(r.get("id") or "")
        for r in streamer_rows
        if r.get("enabled", True)
    }
    disabled = {
        str(r.get("id") or "")
        for r in streamer_rows
        if not r.get("enabled", True)
    }

    if instance_ids is None:
        ids = []
        for row in streamer_rows:
            iid = str(row.get("id") or "")
            if not iid or iid == "Tiramisu64" or iid in disabled:
                continue
            lock = get_lock("streamers", iid, root=root)
            tracked = next((r for r in fleet_rows(root) if r.get("instance_id") == iid), {})
            if lock or tracked.get("selected_title") or tracked.get("program_key") or tracked.get(
                "network"
            ):
                ids.append(iid)
        instance_ids = ids
    else:
        # Skip parked/disabled clones; keep explicit ids unknown to registry (tests).
        instance_ids = [i for i in instance_ids if i not in disabled]

    probes = []
    for iid in instance_ids:
        probes.append({"instance_id": iid, **probe_instance_identity(iid, root=root)})

    by_prog: dict[str, list[str]] = {}
    by_net: dict[str, list[str]] = {}
    for p in probes:
        ident = p.get("identity") or {}
        pk = ident.get("program_key")
        if not pk:
            row = next((r for r in fleet_rows(root) if r.get("instance_id") == p["instance_id"]), {})
            pk = row.get("program_key")
        net = str(ident.get("network") or "").upper() or None
        if not net:
            row = next((r for r in fleet_rows(root) if r.get("instance_id") == p["instance_id"]), {})
            net = str(row.get("network") or "").upper() or None
        iid = str(p["instance_id"])
        if pk:
            by_prog.setdefault(str(pk), []).append(iid)
        if net:
            by_net.setdefault(net, []).append(iid)

    def _retune_group(
        *,
        key: str,
        kind: str,
        iids: list[str],
        avoid_keys: set[str],
    ) -> None:
        uniq = list(dict.fromkeys(iids))
        if len(uniq) < 2:
            return
        keep = _keep_instance_for_program(uniq, root=root)
        for iid in uniq:
            if iid == keep:
                actions.append(
                    {
                        "instance_id": iid,
                        "action": "keep",
                        kind: key,
                        "reason": f"primary_for_{kind}",
                    }
                )
                continue
            if not execute:
                actions.append(
                    {
                        "instance_id": iid,
                        "action": "would_retune",
                        kind: key,
                        "keep": keep,
                    }
                )
                continue
            lock = get_lock("streamers", iid, root=root)
            if lock and "ON_AIR_CONTINUE" not in str(lock.get("session_id") or ""):
                actions.append(
                    {
                        "instance_id": iid,
                        "action": "skip_named_job_lock",
                        kind: key,
                        "keep": keep,
                        "session_id": lock.get("session_id"),
                    }
                )
                continue
            ret = retune_to_next_priority(iid, root=root, avoid_program_keys=avoid_keys)
            actions.append(
                {
                    "instance_id": iid,
                    "action": "retune",
                    kind: key,
                    "keep": keep,
                    "result": ret,
                }
            )
            try:
                from .farm_ops import emit

                emit(
                    "duplicate_program_retune",
                    detail=f"{kind}={key} keep={keep} → {iid}",
                    instance_id=iid,
                    ok=bool(ret.get("ok")),
                    extra={kind: key, "keep": keep, "retune": ret},
                    root=root,
                )
            except Exception:
                pass

    actions: list[dict[str, Any]] = []
    already_retuned: set[str] = set()

    # Program dups first (same game across affiliates).
    for pk, iids in by_prog.items():
        before = len(actions)
        _retune_group(key=pk, kind="program_key", iids=iids, avoid_keys={pk})
        for a in actions[before:]:
            if a.get("action") in {"retune", "would_retune"}:
                already_retuned.add(str(a["instance_id"]))

    # Network dups (two ABCs with null program_key) — skip already-handled ids.
    for net, iids in by_net.items():
        remaining = [i for i in iids if i not in already_retuned]
        # If keep is in already_retuned, still need another survivor in this net group.
        if len(list(dict.fromkeys(iids))) < 2:
            continue
        # Re-include keep candidate so we don't retune everyone off the net.
        group = list(dict.fromkeys(iids))
        keep = _keep_instance_for_program(group, root=root)
        to_fix = [i for i in group if i != keep and i not in already_retuned]
        if not to_fix:
            continue
        before = len(actions)
        _retune_group(
            key=net,
            kind="network",
            iids=[keep] + to_fix,
            avoid_keys=set(by_prog.keys()),
        )
        for a in actions[before:]:
            if a.get("action") in {"retune", "would_retune"}:
                already_retuned.add(str(a["instance_id"]))

    prog_dups = sum(1 for v in by_prog.values() if len(set(v)) > 1)
    net_dups = sum(1 for v in by_net.values() if len(set(v)) > 1)
    write_board(root)
    return {
        "ok": True,
        "probes": probes,
        "programs": {k: v for k, v in by_prog.items()},
        "networks": {k: v for k, v in by_net.items()},
        "actions": actions,
        "duplicates_found": prog_dups + net_dups,
    }


def classify_root_cause(
    *,
    ok: bool | None = None,
    reason: str | None = None,
    via: str | None = None,
    selected_title: str | None = None,
    ui_kind: str | None = None,
    picture_state: str | None = None,
    audio_lagging: bool | None = None,
    open_error: str | None = None,
) -> str:
    """Map mixed probe/open signals → one root_cause class."""
    title = (selected_title or "").lower()
    err = f"{reason or ''} {open_error or ''}".lower()
    if "duplicate" in err:
        return "duplicate_stream"
    if any(bad in title for bad in ("pluto", "tubi", "roku", "freevee")) or "pluto" in err or "pack_epg" in err:
        return "pluto_or_pack_epg"
    if "wrong_channel" in err or "identity" in err or "rejected_bad" in err:
        return "wrong_channel"
    if open_error or "open_failed" in err or "section not in rail" in err or "calls_search_no" in err:
        return "open_failed"
    if audio_lagging or "audio_lag" in err:
        return "audio_lag"
    if "audio" in err and ("dead" in err or "progress" in err):
        return "audio_dead"
    pic = (picture_state or "").lower()
    if pic in {
        "blue_spinner",
        "cloud_network_error",
        "black_down",
        "error_overlay",
        "buffering",
        "flat_dark",
        "frozen_frames",
    } or "spinner" in err or "picture" in err:
        return "picture_bad"
    kind = (ui_kind or "").lower()
    if "guide" in kind or "guide_stuck" in err or "still_on_guide" in err:
        return "guide_stuck"
    if "streamers_down" in err or "522" in err or "cloudflare" in err:
        return "streamers_down"
    if "recover" in err and ("exhaust" in err or "failed" in err):
        return "recover_exhausted"
    if "stale" in err or "dead" in err or "broken_live" in err:
        return "capture_dead"
    if ok is True:
        return "ok"
    if ok is False:
        return "unknown"
    return "unknown"


def verify_local_identity(
    selected_title: str | None,
    *,
    network: str,
    calls: str,
    city: str | None = None,
    market: str | None = None,
) -> dict[str, Any]:
    """Post-open gate: title must be the intended affiliate, not Pluto/near-miss."""
    from .us_locals import parse_local_title

    title = (selected_title or "").strip()
    if not title:
        return {"ok": False, "error": "identity_empty_title", "root_cause": "wrong_channel"}
    tl = title.lower()
    if any(bad in tl for bad in ("pluto", "tubi", "roku", "freevee", "max sports")):
        return {
            "ok": False,
            "error": f"identity_bad_source:{title[:80]}",
            "root_cause": "pluto_or_pack_epg",
            "title": title,
        }
    net_u = network.upper().strip()
    calls_u = calls.upper().strip()
    parsed = parse_local_title(title)
    if parsed:
        if parsed.get("network") != net_u:
            return {
                "ok": False,
                "error": f"identity_network:{parsed.get('network')}!={net_u}",
                "root_cause": "wrong_channel",
                "title": title,
                "parsed": parsed,
            }
        if parsed.get("calls") != calls_u:
            return {
                "ok": False,
                "error": f"identity_calls:{parsed.get('calls')}!={calls_u}",
                "root_cause": "wrong_channel",
                "title": title,
                "parsed": parsed,
            }
        city_u = (city or market or "").upper()
        if city_u and parsed.get("city"):
            pc = str(parsed["city"]).upper()
            if city_u not in pc and pc not in city_u:
                # Soft warn — some titles omit city; calls+net already matched.
                pass
        return {
            "ok": True,
            "title": title,
            "parsed": parsed,
            "root_cause": "ok",
        }
    # Fallback: call token + network substring (WSB not WSBT).
    import re

    if not re.search(rf"(?<![A-Z]){re.escape(calls_u)}(?![A-Z])", title.upper()):
        return {
            "ok": False,
            "error": f"identity_no_calls:{calls_u}",
            "root_cause": "wrong_channel",
            "title": title,
        }
    if net_u not in title.upper():
        return {
            "ok": False,
            "error": f"identity_no_network:{net_u}",
            "root_cause": "wrong_channel",
            "title": title,
        }
    return {"ok": True, "title": title, "parsed": None, "root_cause": "ok"}


def record(
    instance_id: str,
    *,
    event: str,
    ok: bool | None = None,
    root_cause: str | None = None,
    detail: str = "",
    job_id: str | None = None,
    session_id: str | None = None,
    intended: dict[str, Any] | None = None,
    selected_title: str | None = None,
    via: str | None = None,
    ui_kind: str | None = None,
    picture_state: str | None = None,
    audio_peak: float | None = None,
    audio_lagging: bool | None = None,
    failover: bool | None = None,
    market: str | None = None,
    network: str | None = None,
    calls: str | None = None,
    channel_number: int | None = None,
    program_key: str | None = None,
    program_title: str | None = None,
    extra: dict[str, Any] | None = None,
    root: Path | None = None,
    emit_farm_run: bool = True,
) -> dict[str, Any]:
    """Update instance status + append farm_run event (never raises)."""
    root = ensure_data_layout(root)
    reason = detail
    rc = root_cause or classify_root_cause(
        ok=ok,
        reason=reason,
        via=via,
        selected_title=selected_title,
        ui_kind=ui_kind,
        picture_state=picture_state,
        audio_lagging=audio_lagging,
        open_error=detail if ok is False else None,
    )
    if rc not in ROOT_CAUSES:
        rc = "unknown"

    state = load_state(root)
    row = dict((state.get("instances") or {}).get(instance_id) or {})
    row["instance_id"] = instance_id
    row["updated_utc"] = _now_iso()
    row["last_event"] = event
    row["last_detail"] = detail
    row["root_cause"] = rc
    if ok is not None:
        row["up"] = bool(ok) and rc == "ok"
        row["ok"] = bool(ok)
    if job_id is not None:
        row["job_id"] = job_id
    if session_id is not None:
        row["session_id"] = session_id
    if intended:
        row["intended"] = intended
    if selected_title is not None:
        row["selected_title"] = selected_title
        row["last_open"] = {
            "utc": _now_iso(),
            "via": via,
            "selected_title": selected_title,
            "ok": ok,
            "root_cause": rc,
        }
        if program_key is None and ok is not False:
            program_key = normalize_program_key(selected_title)
    # Failed opens must not leave old channel/program as a live fleet identity.
    if ok is False and event in {
        "channel_open",
        "heartbeat_fix_failed",
        "retune_failed",
    }:
        row["identity_live"] = False
        row["channel_number"] = None
        row["program_key"] = None
        row["program_title"] = None
        # Keep last_failed_* for receipts; clear competing compare keys.
        row["last_failed_identity"] = {
            "utc": _now_iso(),
            "selected_title": selected_title or row.get("selected_title"),
            "calls": calls or row.get("calls"),
            "network": network or row.get("network"),
            "root_cause": rc,
            "detail": detail,
        }
    elif ok is True and event in {
        "channel_open",
        "heartbeat_ok",
        "heartbeat_fixed",
        "identity_probe",
        "identity_on_air_health",
    }:
        row["identity_live"] = True
        # Successful open must clear sticky guide_stuck so desk can restart ON_AIR.
        if event in {"channel_open", "heartbeat_ok", "heartbeat_fixed"}:
            try:
                from .heartbeat_fix import _load_state as _hb_load
                from .heartbeat_fix import _save_state as _hb_save

                hb = _hb_load(root)
                hb_row = dict((hb.get("instances") or {}).get(instance_id) or {})
                hb_row["post_fix_reset"] = _now_iso()
                hb_row.pop("stuck_reason", None)
                hb.setdefault("instances", {})[instance_id] = hb_row
                _hb_save(hb, root)
            except Exception:
                pass
    if via is not None:
        row["via"] = via
    if ui_kind is not None:
        row["ui_kind"] = ui_kind
    if picture_state is not None:
        row["picture_state"] = picture_state
    if audio_peak is not None:
        row["audio_peak"] = audio_peak
    if audio_lagging is not None:
        row["audio_lagging"] = bool(audio_lagging)
    if failover is not None:
        row["failover"] = bool(failover)
    if market is not None:
        row["market"] = market
    if network is not None and row.get("identity_live") is not False:
        row["network"] = network
    if calls is not None and row.get("identity_live") is not False:
        row["calls"] = calls
    if channel_number is not None and row.get("identity_live") is not False:
        row["channel_number"] = int(channel_number)
    if program_key is not None and row.get("identity_live") is not False:
        row["program_key"] = program_key
    if program_title is not None and row.get("identity_live") is not False:
        row["program_title"] = program_title
    if ok is False:
        row["last_fail"] = {
            "utc": _now_iso(),
            "event": event,
            "detail": detail,
            "root_cause": rc,
        }
        row["fail_count_session"] = int(row.get("fail_count_session") or 0) + 1
    if ok is True and event in {"channel_open", "heartbeat_ok", "heartbeat_fixed"}:
        row["up_since"] = row.get("up_since") or _now_iso()
        row["last_ok_utc"] = _now_iso()
    if ok is False:
        row.pop("up_since", None)

    state.setdefault("instances", {})[instance_id] = row
    tail = list(state.get("events_tail") or [])
    ev = {
        "utc": _now_iso(),
        "instance_id": instance_id,
        "event": event,
        "ok": ok,
        "root_cause": rc,
        "detail": detail,
        "selected_title": selected_title,
        "via": via,
        "market": market or row.get("market"),
        "network": network or row.get("network"),
    }
    if extra:
        ev["extra"] = extra
    tail.append(ev)
    state["events_tail"] = tail[-200:]
    save_state(state, root)

    if emit_farm_run:
        try:
            from .farm_ops import emit

            emit(
                event,
                detail=detail or rc,
                instance_id=instance_id,
                job_id=job_id,
                session_id=session_id,
                ok=ok,
                extra={
                    "root_cause": rc,
                    "via": via,
                    "selected_title": selected_title,
                    "market": market or row.get("market"),
                    "network": network or row.get("network"),
                    "calls": calls or row.get("calls"),
                    "failover": row.get("failover"),
                    "ui_kind": ui_kind or row.get("ui_kind"),
                    "picture_state": picture_state or row.get("picture_state"),
                    "audio_peak": audio_peak if audio_peak is not None else row.get("audio_peak"),
                    "audio_lagging": row.get("audio_lagging"),
                    "program_key": program_key or row.get("program_key"),
                    "channel_number": channel_number
                    if channel_number is not None
                    else row.get("channel_number"),
                    **(extra or {}),
                },
                root=root,
            )
        except Exception:
            pass

    # Policy failures → open-model queue (atomic receipt + work item).
    if ok is False and rc in {
        "duplicate_stream",
        "wrong_channel",
        "pluto_or_pack_epg",
        "audio_lag",
        "picture_bad",
        "guide_stuck",
        "streamers_down",
        "open_failed",
    }:
        try:
            from .open_model_todos import ingest_policy

            ingest_policy(
                rc,
                instance_id=instance_id,
                detail=detail or f"{event}:{rc}",
                meta={
                    "event": event,
                    "program_key": program_key or row.get("program_key"),
                    "calls": calls or row.get("calls"),
                    "network": network or row.get("network"),
                    "selected_title": selected_title or row.get("selected_title"),
                    "root_cause": rc,
                },
                root=root,
            )
        except Exception:
            pass

    return dict(row)


def refresh_from_live(
    *,
    root: Path | None = None,
    instances: list[str] | None = None,
    probe: bool = False,
) -> dict[str, Any]:
    """Merge locks + optional heartbeat probes into the status board."""
    root = ensure_data_layout(root)
    from .instances import list_instances
    from .locks import get_lock

    state = load_state(root)
    known = [str(r.get("id")) for r in list_instances(root) if r.get("id")]
    targets = instances or known
    for iid in targets:
        if not iid:
            continue
        row = dict((state.get("instances") or {}).get(iid) or {"instance_id": iid})
        lock = get_lock("streamers", iid, root=root)
        if lock:
            row["job_id"] = lock.get("job_id") or row.get("job_id")
            row["session_id"] = lock.get("session_id") or row.get("session_id")
            row["locked"] = True
        else:
            row["locked"] = False
        if probe:
            try:
                from .heartbeat_fix import probe_heartbeat

                hb = probe_heartbeat(iid, session_id=row.get("session_id"), root=root, save_shot=False)
                row["ui_kind"] = hb.get("ui_kind")
                row["ok"] = bool(hb.get("ok"))
                row["up"] = bool(hb.get("ok")) and not hb.get("failing")
                lag = hb.get("audio_lag") or {}
                if lag.get("peak") is not None:
                    row["audio_peak"] = lag.get("peak")
                if lag.get("lagging") is not None:
                    row["audio_lagging"] = bool(lag.get("lagging"))
                pic = ((hb.get("picture") or {}).get("frame_score") or {}).get("verdict")
                if pic:
                    row["picture_state"] = pic
                if hb.get("failing"):
                    row["root_cause"] = classify_root_cause(
                        ok=False,
                        reason=str(hb.get("reason") or ""),
                        ui_kind=str(hb.get("ui_kind") or ""),
                        picture_state=str(pic or ""),
                        audio_lagging=bool(lag.get("lagging")),
                    )
                    row["last_fail"] = {
                        "utc": _now_iso(),
                        "event": "heartbeat_probe",
                        "detail": hb.get("reason"),
                        "root_cause": row["root_cause"],
                    }
                else:
                    row["root_cause"] = "ok"
                    row["last_ok_utc"] = _now_iso()
                row["updated_utc"] = _now_iso()
            except Exception as exc:  # noqa: BLE001
                row["probe_error"] = str(exc)
                row["root_cause"] = row.get("root_cause") or "unknown"
        state.setdefault("instances", {})[iid] = row
    save_state(state, root)
    return write_board(root)


def write_board(root: Path | None = None) -> dict[str, Any]:
    """Write STREAM_STATUS.md + stream_status.json from state."""
    root = ensure_data_layout(root)
    state = load_state(root)
    instances = dict(state.get("instances") or {})
    rows = sorted(instances.values(), key=lambda r: str(r.get("instance_id") or ""))
    up_n = sum(1 for r in rows if r.get("up"))
    down_n = sum(1 for r in rows if r.get("up") is False)
    lines = [
        "# Stream status",
        "",
        f"Checked `{_now_iso()}` — **{up_n} up** / **{down_n} down** / {len(rows)} tracked",
        "",
        "Root causes: `" + "` · `".join(ROOT_CAUSES) + "`",
        "",
        "| Inst | Up | Root cause | Market | Net | Calls | Title | Via | UI | Lag | Job | Note |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        note = r.get("last_detail") or (r.get("last_fail") or {}).get("detail") or "—"
        if isinstance(note, str) and len(note) > 36:
            note = note[:36] + "…"
        title = str(r.get("selected_title") or "—")
        if len(title) > 28:
            title = title[:28] + "…"
        lag = "yes" if r.get("audio_lagging") else ("—" if r.get("audio_peak") is None else "no")
        lines.append(
            f"| `{r.get('instance_id')}` | "
            f"{'✅' if r.get('up') else ('❌' if r.get('up') is False else '·')} | "
            f"{r.get('root_cause') or '—'} | "
            f"{r.get('market') or '—'} | "
            f"{r.get('network') or '—'} | "
            f"{r.get('calls') or '—'} | "
            f"{title} | "
            f"{r.get('via') or '—'} | "
            f"{r.get('ui_kind') or r.get('picture_state') or '—'} | "
            f"{lag} | "
            f"{(str(r.get('job_id') or '—'))[:14]} | "
            f"{note} |"
        )
    lines.extend(
        [
            "",
            "## Recent events",
            "",
        ]
    )
    for ev in list(state.get("events_tail") or [])[-15:]:
        lines.append(
            f"- `{str(ev.get('utc') or '')[:19]}` `{ev.get('instance_id')}` "
            f"**{ev.get('event')}** rc={ev.get('root_cause')} "
            f"{'ok' if ev.get('ok') else 'FAIL'} — {ev.get('detail') or ev.get('selected_title') or ''}"
        )
    lines.extend(
        [
            "",
            "## Commands",
            "",
            "```powershell",
            "python -m tools.windows_lab streams board",
            "python -m tools.windows_lab streams board --probe",
            "python -m tools.windows_lab streams enforce-unique",
            "python -m tools.windows_lab ops log-tail -n 40",
            "```",
            "",
        ]
    )
    path = board_path(root)
    path.write_text("\n".join(lines), encoding="utf-8")
    payload = {
        "checked_utc": _now_iso(),
        "up": up_n,
        "down": down_n,
        "instances": instances,
        "events_tail": list(state.get("events_tail") or [])[-40:],
        "board": str(path),
        "state": str(state_path(root)),
    }
    board_json_path(root).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    payload["board_json"] = str(board_json_path(root))
    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Stream uptime / root-cause board")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("board", help="Write STREAM_STATUS.md")
    b.add_argument("--probe", action="store_true", help="Live heartbeat probe each instance")
    b.add_argument("--instances", default="", help="Comma instance ids (default: all known)")
    sub.add_parser("causes", help="List root_cause enum")
    u = sub.add_parser(
        "enforce-unique",
        help="Retune streams that share the same game (any affiliate)",
    )
    u.add_argument(
        "--dry-run",
        action="store_true",
        help="Probe + report only; do not retune",
    )
    u.add_argument("--instances", default="", help="Comma instance ids (default: hot fleet)")
    args = p.parse_args(argv)
    if args.cmd == "causes":
        print(json.dumps({"root_causes": list(ROOT_CAUSES)}, indent=2))
        return 0
    if args.cmd == "board":
        inst = [x.strip() for x in str(args.instances).split(",") if x.strip()] or None
        out = refresh_from_live(instances=inst, probe=bool(args.probe))
        print(json.dumps(out, indent=2)[:4000])
        return 0
    if args.cmd == "enforce-unique":
        inst = [x.strip() for x in str(args.instances).split(",") if x.strip()] or None
        out = enforce_unique_programs(
            instance_ids=inst,
            execute=not bool(args.dry_run),
        )
        print(json.dumps(out, indent=2)[:6000])
        return 0 if out.get("ok") else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
