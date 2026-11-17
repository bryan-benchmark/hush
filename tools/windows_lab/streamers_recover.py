"""Autonomous Streamers unstick — classify UI, apply a fix, verify.

Goal: farm / open paths recover without a Cursor turn. Protocol is always
fresh uiautomator dump (+ optional screencap). No remembered tap coords.

This is a *rule* automaton over accessibility text (cheap, local). Optional
vision can be plugged later via ``vision_hint``; do not block on cloud models.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import ensure_data_layout
from .instances import adb, connect_adb, get_instance, launch_bluestacks, wait_for_adb
from .streamers_alive import ensure_streamers_alive
from .streamers_open import (
    DEFAULT_INSTANCE,
    _dump_ui,
    _tap_text,
    _texts,
    _type_search_query,
    _clear_search_field,
    _pick_channel_title,
    _open_search_via_longpress,
)

# Safe fallbacks when the guide is empty / black — Atlanta US locals only.
# Never Pluto / Max Sports / free-ad junk (wrong national inventory).
# FOX/CBS/NBC before ABC — hardcoded WSB-first kept putting both clones on ABC.
FALLBACK_QUERIES = (
    ("WAGA", "FOX"),  # Atlanta FOX
    ("WANF", "CBS"),  # Atlanta CBS
    ("WXIA", "NBC"),  # Atlanta NBC
    ("WSB", "ABC"),   # Atlanta ABC (last resort)
)

_FALLBACK_BY_NET = {
    "FOX": ("WAGA", "FOX"),
    "CBS": ("WANF", "CBS"),
    "NBC": ("WXIA", "NBC"),
    "ABC": ("WSB", "ABC"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / "streamers_recover.jsonl"


def _append_log(row: dict[str, Any], root: Path | None = None) -> None:
    path = log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def classify(texts: list[str], *, activity: str = "") -> str:
    """Map a fresh dump to a stuck / ready state."""
    from .ui_dump import DUMP_FAILED_MARKER

    if any(DUMP_FAILED_MARKER in str(t) for t in texts):
        return "dump_dead"
    low = " | ".join(t.lower() for t in texts)
    joined = low

    if any("popular games" in t.lower() or "search for games" in t.lower() for t in texts):
        return "bluestacks_home"
    if any("display over other apps" in t.lower() for t in texts):
        return "overlay_permission"
    if "add playlist" in joined and "username" not in joined:
        return "welcome_login"
    if "username" in joined and "password" in joined and "next" in joined:
        return "credentials_login"
    if "salvation" in joined and "cancel" in joined and "username" not in joined:
        return "service_list_login"
    if "playlist name" in joined and "done" in joined:
        return "playlist_name_login"
    if any("unrecognizedinputformatexception" in t.lower() for t in texts):
        return "player_decode_error"
    if any("error occurred" in t.lower() or "code 522" in t.lower() or "code 404" in t.lower() for t in texts):
        return "player_hard_error"
    # Long-press power / BlueStacks power sheet over Streamers.
    if "power off" in joined and "restart" in joined:
        return "power_dialog"
    if "block group" in joined or "hide group" in joined:
        return "group_settings_overlay"
    if "search history" in joined or (
        "channels" in joined and "programs" in joined and "search" in joined
    ):
        return "search_ui"
    if "search" in texts and "tv" in [t.lower() for t in texts] and "movies" in joined:
        # Left nav search hub — not the guide grid
        if not any(t.endswith("SECTION") or t.startswith("NFL") for t in texts):
            if not any(" | " in t for t in texts):
                return "search_hub"
    # Empty event farm (MAX-UK / FLSP / AMZN no event) with no live card
    no_event = sum(1 for t in texts if "no event available" in t.lower())
    liveish = any(
        re.search(r"\b(vs\.?|@)\b", t, re.I)
        or re.search(r"\d{1,2}:\d{2}\s*(AM|PM)\s*ET", t, re.I)
        for t in texts
        if "no event" not in t.lower()
    )
    if no_event >= 4 and not liveish:
        return "empty_event_guide"
    if any("fhd" in t.lower() or "stereo" in t.lower() or "fps" in t.lower() for t in texts):
        return "player_chrome"
    if any(t.endswith("SECTION") for t in texts) or "All channels" in texts or "Favorites" in texts:
        return "guide"
    if any(re.match(r"^(NFL|SN\+|ESPN|AMZN|FLSP)", t) or " | " in t for t in texts):
        return "guide"
    # Fullscreen player often dumps zero text while MainActivity still has picture.
    if len(texts) < 3 and "MainActivity" in activity:
        return "player_fullscreen"
    if len(texts) < 3:
        return "player_or_blank"
    if "MainActivity" in activity:
        return "guide_like"
    return "unknown"


def _activity(instance: dict[str, Any]) -> str:
    code, out = adb(instance, ["shell", "dumpsys", "window"], timeout=20)
    if code != 0:
        return ""
    for line in out.splitlines():
        if "mCurrentFocus=" in line:
            return line.strip()
    return ""


def _screencap(instance: dict[str, Any], dest: Path) -> Path | None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    adb(instance, ["shell", "screencap", "-p", "/sdcard/ohush_recover.png"], timeout=20)
    code, _ = adb(instance, ["pull", "/sdcard/ohush_recover.png", str(dest)], timeout=20)
    return dest if code == 0 and dest.is_file() else None


def snapshot(
    instance_id: str = DEFAULT_INSTANCE,
    *,
    root: Path | None = None,
    take_frame: bool = True,
) -> dict[str, Any]:
    root = ensure_data_layout(root)
    inst = get_instance(instance_id, root)
    connect_adb(inst)
    probe = root / "work" / "streamers_recover"
    probe.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    # Soft dump via contract — tagged DUMP_FAILED on exhaust (never silent empty).
    from .ui_dump import dump_meta_from_ui, is_dump_failed_ui

    try:
        from .streamers_nav import _dump_ui_soft

        ui = _dump_ui_soft(
            inst,
            probe / f"{instance_id}_{stamp}.xml",
            caller="recover_snapshot",
        )
    except Exception:
        ui = _dump_ui(inst, probe / f"{instance_id}_{stamp}.xml")
    texts = _texts(ui)
    meta = dump_meta_from_ui(ui)
    dump_ok = bool(meta.get("dump_ok")) and not is_dump_failed_ui(ui, texts)
    activity = _activity(inst)
    kind = classify(texts, activity=activity)
    if not dump_ok:
        kind = "dump_dead"
    frame = None
    frame_watch = None
    if take_frame:
        frame = _screencap(inst, probe / f"{instance_id}_{stamp}.png")
        if frame:
            try:
                from .frame_watch import analyze_frame

                frame_watch = analyze_frame(frame, use_vision=None, root=root)
                # Vision/heuristic can override dump-only misreads of fullscreen.
                v = frame_watch.get("verdict")
                loginish = kind.endswith("_login") or kind in {
                    "welcome_login",
                    "credentials_login",
                    "service_list_login",
                    "playlist_name_login",
                    "overlay_permission",
                }
                if kind == "dump_dead":
                    pass  # keep dump_dead — do not promote to player from vision alone
                elif kind in {"player_or_blank", "player_fullscreen", "unknown", "unknown_app"} and v == "likely_playing":
                    kind = "player_chrome"
                elif not loginish and v in {"black_down", "stuck_guide", "login", "error_overlay"}:
                    kind = {
                        "black_down": "player_or_blank",
                        "stuck_guide": "empty_event_guide" if kind == "guide" else "guide",
                        "login": "credentials_login",
                        "error_overlay": "player_hard_error",
                    }.get(str(v), kind)
            except Exception as e:  # noqa: BLE001
                frame_watch = {"ok": False, "error": str(e)}
    return {
        "instance_id": instance_id,
        "kind": kind,
        "activity": activity,
        "texts": texts[:40],
        "frame": str(frame) if frame else None,
        "frame_watch": frame_watch,
        "ui_path": str(probe / f"{instance_id}_{stamp}.xml"),
        "dump_ok": dump_ok,
        "dump_reason": meta.get("dump_reason"),
        "dump_fabricated": bool(meta.get("dump_fabricated")),
        "checked_utc": _now(),
    }


FixFn = Callable[[dict[str, Any], dict[str, Any], Path], dict[str, Any]]


def _fix_bluestacks_home(inst: dict[str, Any], snap: dict[str, Any], probe: Path) -> dict[str, Any]:
    launch_bluestacks(inst, launch_app=True)
    time.sleep(3.0)
    adb(
        inst,
        [
            "shell",
            "monkey",
            "-p",
            str(inst.get("package") or "ar.tvplayer.tv"),
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        ],
    )
    time.sleep(2.5)
    return {"action": "relaunch_streamers"}


def _fix_overlay(inst: dict[str, Any], snap: dict[str, Any], probe: Path) -> dict[str, Any]:
    adb(inst, ["shell", "appops", "set", "ar.tvplayer.tv", "SYSTEM_ALERT_WINDOW", "allow"])
    adb(inst, ["shell", "input", "keyevent", "4"])
    time.sleep(0.8)
    adb(inst, ["shell", "am", "force-stop", "ar.tvplayer.tv"])
    time.sleep(0.5)
    adb(
        inst,
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
    time.sleep(2.5)
    return {"action": "grant_overlay_relaunch"}


def _fix_login(inst: dict[str, Any], snap: dict[str, Any], probe: Path) -> dict[str, Any]:
    from .salvation import login

    iid = str(inst.get("id") or snap.get("instance_id") or DEFAULT_INSTANCE)
    result = login(iid, steps=14)
    return {"action": "salvation_login", "ok": bool(result.get("ok")), "screen": result.get("screen")}


def rematchimize_player(inst: dict[str, Any]) -> dict[str, Any]:
    """Long-press Back — fullscreen the channel already in the guide preview."""
    adb(inst, ["shell", "input", "keyevent", "--longpress", "4"])
    time.sleep(1.6)
    return {
        "action": "rematchimize_longpress_back",
        "ok": True,
        "lesson": "Hold Back rematchimizes the preview channel; short Back only leaves the player.",
    }


def _intended_guide_labels(tgt: dict[str, Any]) -> list[str]:
    """Guide row titles for a locked linear job (US: ESPN / US: ESPN 2)."""
    labels: list[str] = []
    try:
        from .streamers_nav import CHILD_US_ESPN, CHILD_US_ESPN2
        from .streamers_open import LINEAR_NAV_BY_SHORTCUT, nav_route_for_shortcut

        rid = str(tgt.get("nav_route") or "") or None
        if not rid:
            key = str(tgt.get("shortcut_id") or tgt.get("channel_id") or "").upper()
            rid = LINEAR_NAV_BY_SHORTCUT.get(key) or nav_route_for_shortcut(key, None)
        if rid == "ESPN_US":
            labels.append(CHILD_US_ESPN)
        elif rid == "ESPN2_US":
            labels.append(CHILD_US_ESPN2)
    except Exception:
        pass
    for k in ("label", "channel_id", "shortcut_id"):
        v = str(tgt.get(k) or "").strip()
        if v and v not in labels and "MNF" not in v.upper():
            labels.append(v)
    return labels


def _fix_pick_visible_or_rematchimize(
    inst: dict[str, Any],
    snap: dict[str, Any],
    probe: Path,
    *,
    tgt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """On guide with the channel already there — tap the row + open, else long-Back.

    Full US SPORTS nav is the slow path; this is the 'just pick it / rematchimize' path.
    """
    texts = list(snap.get("texts") or [])
    ui = None
    try:
        ui = _dump_ui(inst, probe / "pick_visible.xml")
        texts = _texts(ui) or texts
    except Exception:
        ui = None
    labels = _intended_guide_labels(tgt or {})
    for lab in labels:
        if not lab:
            continue
        hit = next((t for t in texts if t.strip().lower() == lab.lower()), None)
        if not hit:
            hit = next((t for t in texts if lab.lower() in t.lower() and "max" not in t.lower()), None)
        if not hit or ui is None:
            continue
        tapped = _tap_text(inst, ui, hit, contains=False) or _tap_text(inst, ui, hit, contains=True)
        if not tapped:
            continue
        time.sleep(0.5)
        adb(inst, ["shell", "input", "keyevent", "23"])
        time.sleep(1.4)
        after = snapshot(str(inst.get("id") or snap.get("instance_id") or ""), take_frame=False)
        if after.get("kind") in PICTURE_READY:
            return {
                "action": "pick_visible_channel",
                "ok": True,
                "chosen": hit,
                "after_kind": after.get("kind"),
            }
        rem = rematchimize_player(inst)
        after2 = snapshot(str(inst.get("id") or snap.get("instance_id") or ""), take_frame=False)
        return {
            "action": "pick_visible_then_rematchimize",
            "ok": after2.get("kind") in PICTURE_READY,
            "chosen": hit,
            "rematchimize": rem,
            "after_kind": after2.get("kind"),
        }
    # No matching row — do NOT rematchimize a random preview for locked linear
    # (that is how NFL A pack replaced US: ESPN). Unlabeled picture goals may.
    if labels:
        return {
            "action": "pick_visible_missed",
            "ok": False,
            "looked_for": labels,
            "lesson": (
                "Intended row not on this guide page — full nav required. "
                "Long-Back rematchimizes the *current* preview, which may be the wrong feed."
            ),
        }
    rem = rematchimize_player(inst)
    after = snapshot(str(inst.get("id") or snap.get("instance_id") or ""), take_frame=False)
    return {
        "action": "rematchimize_only",
        "ok": after.get("kind") in PICTURE_READY,
        "rematchimize": rem,
        "after_kind": after.get("kind"),
        "looked_for": labels,
    }


def _fix_back(inst: dict[str, Any], snap: dict[str, Any], probe: Path) -> dict[str, Any]:
    adb(inst, ["shell", "input", "keyevent", "4"])
    time.sleep(0.9)
    return {"action": "keyevent_back"}


def _fix_power_dialog(inst: dict[str, Any], snap: dict[str, Any], probe: Path) -> dict[str, Any]:
    # Dismiss BlueStacks / Android power sheet — never tap Power off.
    adb(inst, ["shell", "input", "keyevent", "4"])
    time.sleep(0.6)
    adb(inst, ["shell", "input", "keyevent", "4"])
    time.sleep(0.8)
    return {"action": "dismiss_power_dialog"}


def jiggle_stuck_player(inst: dict[str, Any]) -> dict[str, Any]:
    """One DPAD up + down to unstick decode without leaving the channel.

    Streamers often recovers a frozen/black linear feed after a neighbor nudge;
    retuning to NBC/FOX is the wrong first move when MNF/ESPN is already locked.
    """
    adb(inst, ["shell", "input", "keyevent", "19"])  # DPAD_UP
    time.sleep(1.1)
    adb(inst, ["shell", "input", "keyevent", "20"])  # DPAD_DOWN
    time.sleep(2.4)
    return {"action": "jiggle_up_down", "ok": True, "keys": [19, 20]}


def channel_hop_and_back(inst: dict[str, Any], *, dwell_s: float = 4.0) -> dict[str, Any]:
    """Zap CHANNEL_UP, dwell, CHANNEL_DOWN back — soft unstick without leaving the feed family.

    Safer than rematchimize for spinner/black: briefly leave the hung decode, then
    return. Works on ESPN and locals. Does **not** pick a different affiliate.
    """
    dwell = max(1.5, float(dwell_s))
    adb(inst, ["shell", "input", "keyevent", "166"])  # KEYCODE_CHANNEL_UP
    time.sleep(dwell)
    adb(inst, ["shell", "input", "keyevent", "167"])  # KEYCODE_CHANNEL_DOWN
    time.sleep(max(2.0, dwell * 0.6))
    return {
        "action": "channel_hop_and_back",
        "ok": True,
        "keys": [166, 167],
        "dwell_s": dwell,
    }


def _picture_looks_ok(instance_id: str, root: Path | None = None) -> dict[str, Any]:
    """Cheap post-jiggle picture check (no identity). Prefer ``jiggle_ok_for_intended`` for named locks."""
    try:
        snap = snapshot(instance_id, root=root, take_frame=True)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "root_cause": "snapshot_failed"}
    watch = snap.get("frame_watch") or {}
    heur = watch.get("heuristic") or {}
    verdict = str(heur.get("verdict") or watch.get("verdict") or "")
    kind = str(snap.get("kind") or "")
    playing = bool(heur.get("picture_ok")) or verdict in {
        "likely_playing",
        "picture_ok",
        "ok",
    }
    still_dead = verdict in {
        "black_down",
        "blue_spinner",
        "frames_frozen",
        "frozen_frames",
    } or kind in {"player_decode_error", "player_hard_error"}
    return {
        "ok": bool(playing and not still_dead),
        "kind": kind,
        "verdict": verdict,
        "snap": snap,
        "root_cause": "ok" if (playing and not still_dead) else "picture_still_bad",
    }


# Packs / parents that mean jiggle "restored" the wrong feed for ESPN linear.
_WRONG_PACK_FOR_LINEAR = (
    "NFL A",
    "NFL Y",
    "NFL T",
    "NFL TEAMS/CHANNELS",
    "US ENTERTAINMENT",
    "-------US ENTERTAINMENT-------",
    "MAX SPORTS",
    "AMAZON SPORTS",
)


def _is_linear_nav_intended(tgt: dict[str, Any] | None) -> bool:
    tgt = tgt or {}
    if tgt.get("nav_route") or str(tgt.get("open_via") or "") == "nav":
        return True
    try:
        from .streamers_open import LINEAR_NAV_BY_SHORTCUT, nav_route_for_shortcut

        key = str(tgt.get("shortcut_id") or tgt.get("channel_id") or "").upper()
        if LINEAR_NAV_BY_SHORTCUT.get(key):
            return True
        if nav_route_for_shortcut(key, None):
            return True
    except Exception:
        pass
    return False


def _nav_route_id(tgt: dict[str, Any] | None) -> str | None:
    tgt = tgt or {}
    rid = str(tgt.get("nav_route") or "") or None
    if rid:
        return rid
    try:
        from .streamers_open import LINEAR_NAV_BY_SHORTCUT, nav_route_for_shortcut

        key = str(tgt.get("shortcut_id") or tgt.get("channel_id") or "").upper()
        return LINEAR_NAV_BY_SHORTCUT.get(key) or nav_route_for_shortcut(key, None)
    except Exception:
        return None


def _linear_player_chrome_hit(texts: list[str], *, route_id: str | None) -> str | None:
    """Fullscreen player often omits ``US: ESPN`` — allow ESPN chrome without wrong pack.

    Still reject ESPNU / ESPN 2 when the lock is ESPN_US (and the reverse for ESPN2).
    """
    rid = str(route_id or "").upper()
    joined = " | ".join(texts)
    joined_u = joined.upper()
    if rid == "ESPN_US":
        # Exact child first.
        if any(t.strip() == "US: ESPN" for t in texts):
            return "US: ESPN"
        # Soft chrome: ESPN word, not ESPNU / ESPN 2 / Deportes.
        if re.search(r"\bESPNU\b|\bESPN\s*2\b|\bESPN2\b|DEPORTES", joined_u):
            return None
        if re.search(r"\bESPN\b", joined_u):
            return "espn_chrome"
        return None
    if rid == "ESPN2_US":
        for t in texts:
            if t.strip() in {"US: ESPN 2", "US: ESPN2"}:
                return "US: ESPN 2"
        if "US: ESPN 2" in joined:
            return "US: ESPN 2"
        if re.search(r"\bESPN\s*2\b|\bESPN2\b", joined_u) and "ESPNU" not in joined_u:
            return "espn2_chrome"
        return None
    return None


def evaluate_jiggle_intended(
    *,
    picture_ok: bool,
    kind: str | None = None,
    verdict: str | None = None,
    texts: list[str] | None = None,
    intended: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Pure gate used by ``jiggle_ok_for_intended`` (unit-testable, no ADB)."""
    texts = list(texts or [])
    out: dict[str, Any] = {
        "ok": False,
        "kind": kind,
        "verdict": verdict,
        "error": error,
        "texts_head": texts[:20],
        "intended_ok": False,
        "root_cause": "picture_still_bad" if not picture_ok else "unknown",
    }
    if error and not picture_ok:
        out["root_cause"] = "snapshot_failed"
        return out
    if not picture_ok:
        return out

    tgt = intended or {}
    if not _is_linear_nav_intended(tgt):
        out["ok"] = True
        out["intended_ok"] = True
        out["root_cause"] = "jiggle_picture_ok_unnamed"
        return out

    labels = _intended_guide_labels(tgt)
    route_id = _nav_route_id(tgt)
    joined_u = " | ".join(texts).upper()
    wrong = [w for w in _WRONG_PACK_FOR_LINEAR if w in texts or w.upper() in joined_u]

    hit_label = None
    for lab in labels:
        if not lab:
            continue
        # Prefer exact / bounded match so ``US: ESPN`` does not hit ``US: ESPN 2``.
        if any(t.strip().lower() == lab.lower() for t in texts):
            hit_label = lab
            break
        lab_l = lab.lower()
        if lab_l == "us: espn":
            if any(re.search(r"(?i)^us:\s*espn$", t.strip()) for t in texts):
                hit_label = lab
                break
            continue  # never substring-match into ESPN 2 / ESPNU
        if lab_l.startswith("us: espn 2") or lab_l.startswith("us: espn2"):
            if any(re.search(r"(?i)^us:\s*espn\s*2$", t.strip()) for t in texts):
                hit_label = lab
                break
            continue
        if any(lab_l in t.lower() for t in texts):
            hit_label = lab
            break
    if hit_label:
        out["ok"] = True
        out["intended_ok"] = True
        out["matched_label"] = hit_label
        out["root_cause"] = "jiggle_intended_identity_ok"
        return out

    if wrong:
        out["ok"] = False
        out["intended_ok"] = False
        out["wrong_pack"] = wrong
        out["root_cause"] = "jiggle_wrong_pack"
        out["looked_for"] = labels
        out["lesson"] = (
            f"Jiggle restored a playing frame under {wrong[0]} — not the locked linear. "
            "Refuse jiggle_restored; reopen intended (nav) required."
        )
        return out

    # Player chrome without guide row — allow ESPN*/ESPN2 soft markers only.
    playerish = str(kind or "") in {
        "player_chrome",
        "player_fullscreen",
        "player",
        "player_or_blank",
    } or str(verdict or "") in {"likely_playing", "picture_ok", "ok"}
    chrome_hit = _linear_player_chrome_hit(texts, route_id=route_id) if playerish else None
    if chrome_hit:
        out["ok"] = True
        out["intended_ok"] = True
        out["matched_label"] = chrome_hit
        out["root_cause"] = "jiggle_player_chrome_ok"
        return out

    out["ok"] = False
    out["intended_ok"] = False
    out["root_cause"] = "jiggle_picture_ok_identity_unknown"
    out["looked_for"] = labels
    out["lesson"] = (
        "Playing frame after jiggle but intended row/chrome not proven — "
        "will not log jiggle_restored for named linear."
    )
    return out


def jiggle_ok_for_intended(
    instance_id: str,
    *,
    intended: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Post-jiggle gate for named locks: playing frame AND intended identity.

    Bare ``likely_playing`` is not enough — that is how NFL A / wrong feed got
    logged as ``jiggle_restored`` while MNF/ESPN was locked.
    """
    pic = _picture_looks_ok(instance_id, root=root)
    snap = pic.get("snap") or {}
    texts = list(snap.get("texts") or [])
    out = evaluate_jiggle_intended(
        picture_ok=bool(pic.get("ok")),
        kind=str(pic.get("kind") or "") or None,
        verdict=str(pic.get("verdict") or "") or None,
        texts=texts,
        intended=intended,
        error=str(pic.get("error") or "") or None,
    )
    out["snap"] = snap
    return out


def _fix_player_error(inst: dict[str, Any], snap: dict[str, Any], probe: Path) -> dict[str, Any]:
    """Stuck player: jiggle first, re-open intended, only then US local filler."""
    iid = str(inst.get("id") or snap.get("instance_id") or DEFAULT_INSTANCE)
    jig = jiggle_stuck_player(inst)
    # Prefer intended identity when a locked schedule target exists.
    intended_tgt: dict[str, Any] | None = None
    try:
        from .recovery_target import _job_for_lock

        locked = _job_for_lock(iid, None)
        if locked:
            intended_tgt = {
                "nav_route": locked.get("nav_route"),
                "open_via": locked.get("open_via"),
                "shortcut_id": locked.get("shortcut_id"),
                "channel_id": locked.get("channel_id"),
                "label": locked.get("label"),
            }
    except Exception:
        intended_tgt = None
    if intended_tgt and _is_linear_nav_intended(intended_tgt):
        check = jiggle_ok_for_intended(iid, intended=intended_tgt)
    else:
        check = _picture_looks_ok(iid)
    if check.get("ok"):
        return {
            "action": "player_error_jiggle",
            "ok": True,
            "jiggle": jig,
            "after": {k: check.get(k) for k in ("kind", "verdict", "root_cause", "intended_ok")},
            "root_cause": check.get("root_cause"),
        }

    # Locked/scheduled channel (ESPN_US / MNF_…) — put *that* back, not WXIA.
    try:
        from .recovery_target import open_recovery_target

        intended = open_recovery_target(iid, failover=False)
        if intended.get("ok") and intended.get("via") == "schedule":
            return {
                "action": "player_error_reopen_intended",
                "ok": True,
                "jiggle": jig,
                "jiggle_after": {
                    k: check.get(k) for k in ("kind", "verdict", "root_cause", "wrong_pack")
                },
                "root_cause": "reopened_intended_after_jiggle_miss",
                **{k: intended.get(k) for k in ("via", "target", "network", "selected_title")},
            }
    except Exception as exc:  # noqa: BLE001
        intended = {"ok": False, "error": str(exc)}

    # Last resort: force-stop + hierarchy local (FOX/CBS/NBC…) for bare filler boxes.
    try:
        from .streamers_alive import recover_streamers

        hard = recover_streamers(iid, wait_s=10.0)
    except Exception as exc:  # noqa: BLE001
        hard = {"ok": False, "error": str(exc)}
    adb(inst, ["shell", "input", "keyevent", "4"])
    time.sleep(0.8)
    opened = _fix_open_fallback(inst, snap, probe)
    return {
        "action": "player_error_relaunch_local",
        "jiggle": jig,
        "jiggle_after": {k: check.get(k) for k in ("kind", "verdict")},
        "intended": {k: intended.get(k) for k in ("ok", "via", "error") if isinstance(intended, dict)},
        "recover": {"ok": hard.get("ok"), "error": hard.get("error")},
        **{k: opened.get(k) for k in ("ok", "network", "title", "via", "home_local_error", "last")},
    }


def _fix_open_fallback(inst: dict[str, Any], snap: dict[str, Any], probe: Path) -> dict[str, Any]:
    """Restore what the schedule/hierarchy wants — never bare Atlanta ABC/WSB.

    Uses ``open_recovery_target`` (due jobs + live_preempt + fill_order). Call-letter
    search is last resort only. If a *named* job is locked (MNF_ESPN…), do not
    substitute FOX/NBC when nav fails — return the failure so the desk can retry.
    """
    iid = str(inst.get("id") or snap.get("instance_id") or DEFAULT_INSTANCE)
    home_err = None
    try:
        from .recovery_target import open_recovery_target, resolve_recovery_target

        want = resolve_recovery_target(iid)
        sched = open_recovery_target(iid, failover=False)
        if sched.get("ok"):
            return {
                "action": "fallback_schedule_hierarchy",
                "ok": True,
                "network": sched.get("network"),
                "market": (sched.get("pick") or {}).get("market"),
                "title": sched.get("selected_title") or sched.get("channel_title"),
                "via": sched.get("via"),
                "target": sched.get("target") or want,
            }
        # Locked linear / named capture — refuse local substitute.
        if str(want.get("kind") or "") == "scheduled_job":
            return {
                "action": "fallback_schedule_refused_local",
                "ok": False,
                "error": sched.get("error") or "scheduled_open_failed",
                "via": sched.get("via"),
                "target": want,
                "steps": sched.get("steps"),
                "lesson": (
                    f"Intended {want.get('channel_id') or want.get('shortcut_id')} "
                    f"(nav={want.get('nav_route')}) failed — will not open FOX/NBC filler."
                ),
            }
        home_err = sched.get("error") or "schedule_open_failed"
        net = str((sched.get("target") or {}).get("network") or sched.get("network") or "")
    except Exception as exc:  # noqa: BLE001
        home_err = str(exc)
        net = ""
    if not net:
        try:
            from .stream_status import pick_filler_network

            net = pick_filler_network(iid)
        except Exception:
            net = "FOX"
    try:
        from .us_locals import open_home_local

        out = open_home_local(net, failover=False, instance_id=iid, open_player=True, save=True)
        if out.get("ok"):
            return {
                "action": "fallback_home_local",
                "ok": True,
                "network": net,
                "market": (out.get("pick") or {}).get("market"),
                "title": out.get("selected_title") or out.get("channel_title"),
                "via": out.get("via"),
                "home_local_error": home_err,
            }
        home_err = out.get("error") or home_err
    except Exception as exc:  # noqa: BLE001
        home_err = str(exc)

    # Last resort: call-letter search — preferred net first, ABC/WSB last.
    prefer = _FALLBACK_BY_NET.get(str(net).upper())
    query_order = (
        ((prefer,) + tuple(q for q in FALLBACK_QUERIES if q != prefer))
        if prefer
        else FALLBACK_QUERIES
    )
    ui = _dump_ui(inst, probe / "fallback_home.xml")
    texts = _texts(ui)
    if "All channels" in texts:
        _tap_text(inst, ui, "All channels")
        time.sleep(0.8)
        ui = _dump_ui(inst, probe / "fallback_all.xml")
    opened = _open_search_via_longpress(inst, ui, probe)
    if not opened.get("ok"):
        return {
            "action": "fallback_search",
            "ok": False,
            "longpress": opened,
            "home_local_error": home_err,
        }
    ui = opened["ui"]
    last_err = None
    for query, title_contains in query_order:
        _clear_search_field(inst, ui)
        ui = _dump_ui(inst, probe / "fallback_search.xml")
        _clear_search_field(inst, ui)
        _type_search_query(inst, query)
        adb(inst, ["shell", "input", "keyevent", "66"])
        time.sleep(2.2)
        ui = _dump_ui(inst, probe / "fallback_results.xml")
        titles = _texts(ui)
        if "Channels" in titles:
            _tap_text(inst, ui, "Channels")
            time.sleep(0.9)
            ui = _dump_ui(inst, probe / "fallback_channels.xml")
            titles = _texts(ui)
        pick = None
        if title_contains:
            for t in titles:
                tl = t.lower()
                if any(bad in tl for bad in ("pluto", "tubi", "roku")):
                    continue
                if title_contains in t and "ESPN2" not in t and "ESPNU" not in t:
                    pick = t
                    break
        if not pick:
            pick = _pick_channel_title(titles, query=query)
        if not pick:
            last_err = {"query": query, "titles": titles[:20]}
            continue
        _tap_text(inst, ui, pick, contains=True)
        time.sleep(0.5)
        adb(inst, ["shell", "input", "keyevent", "23"])
        time.sleep(2.5)
        return {
            "action": "fallback_open",
            "ok": True,
            "query": query,
            "title": pick,
            "home_local_error": home_err,
        }
    return {
        "action": "fallback_search",
        "ok": False,
        "last": last_err,
        "home_local_error": home_err,
    }


def _fix_dump_dead(inst: dict[str, Any], snap: dict[str, Any], probe: Path) -> dict[str, Any]:
    """Dump circuit open / soft-empty — heal ADB once; do not swipe or rematchimize."""
    from .ui_dump import heal_adb_for_dump

    heal = heal_adb_for_dump(inst, root=None, allow_recover_streamers=True)
    time.sleep(2.0)
    return {
        "action": "dump_dead_heal",
        "ok": False,
        "heal": heal.get("heal"),
        "streak": heal.get("streak"),
        "lesson": "uiautomator dump dead — healed ADB; refuse blind rail hunt.",
        "dump_reason": snap.get("dump_reason"),
    }


FIXES: dict[str, FixFn] = {
    "bluestacks_home": _fix_bluestacks_home,
    "overlay_permission": _fix_overlay,
    "welcome_login": _fix_login,
    "credentials_login": _fix_login,
    "service_list_login": _fix_login,
    "playlist_name_login": _fix_login,
    "player_decode_error": _fix_player_error,
    "player_hard_error": _fix_player_error,
    "power_dialog": _fix_power_dialog,
    "group_settings_overlay": _fix_back,
    "player_or_blank": _fix_back,
    "player_fullscreen": _fix_back,  # only when goal=guide; picture treats as ready
    "search_hub": _fix_back,
    "empty_event_guide": _fix_open_fallback,
    "search_ui": _fix_back,
    "guide_like": _fix_open_fallback,  # has rows but may be empty — try US local
    "dump_dead": _fix_dump_dead,
}


READY_KINDS = frozenset({"guide", "player_chrome", "guide_like", "section_grid"})
PICTURE_READY = frozenset({"player_chrome", "player_fullscreen"})
GUIDE_SURFACE = frozenset({"guide", "guide_like", "empty_event_guide", "section_grid"})


def recover_loop(
    instance_id: str = DEFAULT_INSTANCE,
    *,
    goal: str = "guide",  # guide | picture
    max_steps: int = 8,
    root: Path | None = None,
) -> dict[str, Any]:
    """Classify → fix → re-dump until ready or steps exhausted."""
    root = ensure_data_layout(root)
    probe = root / "work" / "streamers_recover"
    probe.mkdir(parents=True, exist_ok=True)
    inst = get_instance(instance_id, root)
    launch_bluestacks(inst, launch_app=True)
    connect_adb(inst)
    if not wait_for_adb(inst, seconds=45):
        row = {"ok": False, "error": "adb_not_ready", "instance_id": instance_id}
        _append_log(row, root)
        return row

    # Hard-down (522) first — existing module.
    alive = ensure_streamers_alive(instance_id, root=root, recover=True)

    # Resolve intended once — locked MNF/ESPN must pick a channel, not sit on guide.
    tgt: dict[str, Any] = {}
    locked_named = False
    try:
        from .recovery_target import resolve_recovery_target

        tgt = resolve_recovery_target(instance_id, root=root)
        locked_named = str(tgt.get("kind") or "") == "scheduled_job"
    except Exception:
        tgt = {}
        locked_named = False

    trace: list[dict[str, Any]] = []
    opened_intended = False
    for step in range(max_steps):
        snap = snapshot(instance_id, root=root, take_frame=True)
        kind = snap["kind"]
        entry: dict[str, Any] = {"step": step, "kind": kind, "frame": snap.get("frame")}

        # Dump dead: heal only — never rematchimize / open fallback on invented UI.
        if kind == "dump_dead":
            fix = _fix_dump_dead(inst, snap, probe)
            entry["fix"] = fix
            entry["lesson"] = fix.get("lesson")
            entry["dump_ok"] = False
            trace.append(entry)
            continue

        # Locked capture on guide/section: pick the channel — do not stop at "guide ready".
        if locked_named and kind in GUIDE_SURFACE and not opened_intended:
            quick = _fix_pick_visible_or_rematchimize(inst, snap, probe, tgt=tgt)
            entry["fix"] = quick
            if quick.get("ok"):
                opened_intended = True
                entry["lesson"] = (
                    f"On guide with locked {tgt.get('channel_id') or tgt.get('label')} — "
                    f"picked visible / rematchimized ({quick.get('action')})."
                )
                trace.append(entry)
                continue
            fix = _fix_open_fallback(inst, snap, probe)
            opened_intended = bool(fix.get("ok"))
            entry["fix"] = {"quick": quick, "fallback": fix}
            entry["lesson"] = (
                f"On guide with locked {tgt.get('channel_id') or tgt.get('label')} — "
                "open that channel instead of treating guide as done."
            )
            trace.append(entry)
            if opened_intended:
                continue
            # Fall through only if open refused; do not claim guide success.
            if goal == "guide":
                continue

        if goal == "guide" and kind in READY_KINDS and not (
            locked_named and kind in GUIDE_SURFACE
        ):
            entry["result"] = "ready"
            trace.append(entry)
            out = {
                "ok": True,
                "instance_id": instance_id,
                "goal": goal,
                "final_kind": kind,
                "steps": step,
                "trace": trace,
                "alive": alive,
                "checked_utc": _now(),
            }
            _append_log(out, root)
            return out
        if goal == "picture" and kind in PICTURE_READY:
            entry["result"] = "ready_picture"
            trace.append(entry)
            out = {
                "ok": True,
                "instance_id": instance_id,
                "goal": goal,
                "final_kind": kind,
                "steps": step,
                "trace": trace,
                "alive": alive,
                "checked_utc": _now(),
            }
            _append_log(out, root)
            return out
        if goal == "picture" and kind in GUIDE_SURFACE:
            # On guide but need picture — rematchimize / pick visible first, then full open.
            if not opened_intended:
                quick = _fix_pick_visible_or_rematchimize(inst, snap, probe, tgt=tgt)
                if quick.get("ok"):
                    opened_intended = True
                    entry["fix"] = quick
                    trace.append(entry)
                    continue
                fix = _fix_open_fallback(inst, snap, probe)
                opened_intended = bool(fix.get("ok"))
                entry["fix"] = {"quick": quick, "fallback": fix}
                trace.append(entry)
            else:
                # Already opened once; center, then long-Back rematchimize.
                adb(inst, ["shell", "input", "keyevent", "23"])
                time.sleep(1.0)
                rem = rematchimize_player(inst)
                entry["fix"] = {"action": "keyevent_then_rematchimize", "ok": True, **rem}
                trace.append(entry)
            continue
        # Picture goal: don't Back out of a working fullscreen player.
        if goal == "picture" and kind == "player_fullscreen":
            entry["result"] = "ready_picture"
            trace.append(entry)
            out = {
                "ok": True,
                "instance_id": instance_id,
                "goal": goal,
                "final_kind": kind,
                "steps": step,
                "trace": trace,
                "alive": alive,
                "checked_utc": _now(),
            }
            _append_log(out, root)
            return out

        fix_fn = FIXES.get(kind)
        # Locked MNF/ESPN capture: never Back out of a live player to "make guide".
        if goal == "guide" and kind in {"player_fullscreen", "player_chrome"} and locked_named:
            entry["result"] = "ready_locked_player"
            entry["lesson"] = (
                f"Locked job {tgt.get('channel_id') or tgt.get('label')} — "
                "leave player alone (no Back to guide)."
            )
            trace.append(entry)
            out = {
                "ok": True,
                "instance_id": instance_id,
                "goal": goal,
                "final_kind": kind,
                "steps": step,
                "trace": trace,
                "alive": alive,
                "checked_utc": _now(),
                "locked_job": {
                    k: tgt.get(k)
                    for k in ("channel_id", "shortcut_id", "nav_route", "label", "why")
                },
            }
            _append_log(out, root)
            return out
        if goal == "guide" and kind == "player_fullscreen" and not locked_named:
            fix_fn = _fix_back
        if not fix_fn:
            # Unknown: one Back, then maybe relaunch
            if step < 2:
                fix = _fix_back(inst, snap, probe)
            else:
                fix = _fix_bluestacks_home(inst, snap, probe)
            entry["fix"] = {**fix, "note": f"no_specific_fix_for_{kind}"}
            trace.append(entry)
            continue

        try:
            fix = fix_fn(inst, snap, probe)
        except Exception as e:  # noqa: BLE001
            fix = {"action": "exception", "error": str(e)}
        entry["fix"] = fix
        trace.append(entry)
        time.sleep(0.6)

    final = snapshot(instance_id, root=root, take_frame=True)
    if goal == "picture":
        picture_ok = final["kind"] in PICTURE_READY
        err = None if picture_ok else "exhausted_steps_no_picture"
    else:
        picture_ok = final["kind"] in READY_KINDS
        err = None if picture_ok else "exhausted_steps"
    out = {
        "ok": picture_ok,
        "instance_id": instance_id,
        "goal": goal,
        "final_kind": final["kind"],
        "final_frame": final.get("frame"),
        "steps": max_steps,
        "trace": trace,
        "alive": alive,
        "checked_utc": _now(),
        "error": err,
    }
    _append_log(out, root)
    return out


def ensure_ready_for_open(
    instance_id: str = DEFAULT_INSTANCE,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Call before search/local open — leave instance on a usable guide."""
    return recover_loop(instance_id, goal="guide", max_steps=6, root=root)


def ensure_picture(
    instance_id: str = DEFAULT_INSTANCE,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Leave instance playing a fallback live card (ESPN…)."""
    return recover_loop(instance_id, goal="picture", max_steps=8, root=root)


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Autonomous Streamers recover")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snap", help="Classify current screen + save frame")
    s.add_argument("--instance", default=DEFAULT_INSTANCE)
    r = sub.add_parser("recover", help="Unstick until guide/picture")
    r.add_argument("--instance", default=DEFAULT_INSTANCE)
    r.add_argument("--goal", choices=["guide", "picture"], default="guide")
    r.add_argument("--steps", type=int, default=8)
    e = sub.add_parser("ensure-picture", help="Recover + open fallback live card")
    e.add_argument("--instance", default=DEFAULT_INSTANCE)
    args = p.parse_args(argv)

    if args.cmd == "snap":
        print(json.dumps(snapshot(args.instance), indent=2))
        return 0
    if args.cmd == "recover":
        print(json.dumps(recover_loop(args.instance, goal=args.goal, max_steps=args.steps), indent=2))
        return 0
    if args.cmd == "ensure-picture":
        print(json.dumps(ensure_picture(args.instance), indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
