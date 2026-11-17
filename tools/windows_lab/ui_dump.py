"""UI dump health contract — never silently invent an empty hierarchy.

Hard dumps raise on null-root / empty text. Soft dumps may return a tagged
``DUMP_FAILED`` hierarchy after emit + heal, never a blank player alias.

Events (farm_run.jsonl):
  ui_dump_ok | ui_dump_retry | ui_dump_fail | ui_dump_soft_empty
  | ui_dump_heal | ui_dump_circuit_open
"""

from __future__ import annotations

import json
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout

DUMP_FAILED_MARKER = "DUMP_FAILED"
STATE_NAME = "ui_dump_state.json"
CIRCUIT_OPEN_STREAK = 5
HEAL_CONNECT_STREAK = 3
HEAL_RECOVER_STREAK = 4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / STATE_NAME


def _load_state(root: Path | None = None) -> dict[str, Any]:
    path = _state_path(root)
    if not path.is_file():
        return {"instances": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"instances": {}}
    data.setdefault("instances", {})
    return data


def _save_state(state: dict[str, Any], root: Path | None = None) -> None:
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = dict(state)
    state["updated_utc"] = _now_iso()
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _instance_id(instance: dict[str, Any]) -> str:
    return str(instance.get("id") or instance.get("engine") or "unknown")


def _emit(
    event: str,
    *,
    instance: dict[str, Any],
    detail: str = "",
    ok: bool | None = None,
    extra: dict[str, Any] | None = None,
    root: Path | None = None,
) -> None:
    try:
        from .farm_ops import emit

        emit(
            event,
            detail=detail,
            instance_id=_instance_id(instance),
            ok=ok,
            extra=extra,
            root=root,
        )
    except Exception:
        pass


def classify_dump_error(exc: BaseException | str, *, adb_stdout: str = "") -> str:
    blob = f"{exc} {adb_stdout}".lower()
    if "null root" in blob:
        return "null_root"
    if "empty hierarchy" in blob:
        return "empty_hierarchy"
    if "timeout" in blob or "124" in blob:
        return "timeout"
    if "pull ui xml" in blob or "pull" in blob and "fail" in blob:
        return "pull_failed"
    if "dump failed" in blob:
        return "dump_failed"
    return "unknown"


def is_dump_failed_ui(root: ET.Element | None, texts: list[str] | None = None) -> bool:
    if root is not None and str(root.attrib.get("dump_ok") or "").lower() == "false":
        return True
    texts = texts or []
    for t in texts:
        if DUMP_FAILED_MARKER in str(t):
            return True
    if root is not None:
        for n in root.iter("node"):
            desc = str(n.attrib.get("content-desc") or "")
            if DUMP_FAILED_MARKER in desc:
                return True
    return False


def dump_meta_from_ui(root: ET.Element | None) -> dict[str, Any]:
    if root is None:
        return {"dump_ok": False, "dump_reason": "missing_root", "dump_fabricated": True}
    ok = str(root.attrib.get("dump_ok") or "true").lower() != "false"
    reason = root.attrib.get("dump_reason") or None
    fabricated = str(root.attrib.get("dump_fabricated") or "").lower() == "true"
    if not ok and not reason:
        reason = "dump_failed"
    return {
        "dump_ok": ok,
        "dump_reason": reason,
        "dump_fabricated": fabricated,
    }


def write_dump_failed_xml(
    dest: Path,
    *,
    reason: str,
    error: str = "",
) -> ET.Element:
    """Tagged empty hierarchy — classify as dump_dead, never as player."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    safe_reason = "".join(c if c.isalnum() or c in "_-" else "_" for c in reason)[:64]
    err_tail = (error or "")[:180].replace('"', "'")
    dest.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<hierarchy dump_ok="false" dump_fabricated="true" dump_reason="{safe_reason}" '
        f'dump_error="{err_tail}">'
        f'<node text="{DUMP_FAILED_MARKER}" '
        f'content-desc="{DUMP_FAILED_MARKER}:{safe_reason}" '
        'bounds="[0,0][1600,900]"/></hierarchy>\n',
        encoding="utf-8",
    )
    return ET.parse(dest).getroot()


def _inst_row(root: Path | None, iid: str) -> dict[str, Any]:
    state = _load_state(root)
    return dict((state.get("instances") or {}).get(iid) or {})


def _set_inst_row(root: Path | None, iid: str, row: dict[str, Any]) -> None:
    state = _load_state(root)
    state.setdefault("instances", {})[iid] = row
    _save_state(state, root)


def get_circuit(instance: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    row = _inst_row(root, _instance_id(instance))
    return {
        "streak": int(row.get("streak") or 0),
        "circuit": str(row.get("circuit") or "closed"),
        "last_reason": row.get("last_reason"),
        "last_utc": row.get("last_utc"),
        "last_heal": row.get("last_heal"),
    }


def record_dump_success(instance: dict[str, Any], *, root: Path | None = None, ms: float | None = None) -> None:
    iid = _instance_id(instance)
    row = _inst_row(root, iid)
    was_open = str(row.get("circuit") or "") == "open"
    row.update(
        {
            "streak": 0,
            "circuit": "closed",
            "last_ok_utc": _now_iso(),
            "last_ms": ms,
        }
    )
    if was_open:
        row["circuit_closed_utc"] = _now_iso()
    _set_inst_row(root, iid, row)


def record_dump_failure(
    instance: dict[str, Any],
    *,
    reason: str,
    root: Path | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    iid = _instance_id(instance)
    row = _inst_row(root, iid)
    streak = int(row.get("streak") or 0) + 1
    circuit = "open" if streak >= CIRCUIT_OPEN_STREAK else str(row.get("circuit") or "closed")
    if circuit == "open" and str(row.get("circuit") or "") != "open":
        _emit(
            "ui_dump_circuit_open",
            instance=instance,
            detail=reason,
            ok=False,
            extra={"streak": streak, "error": (error or "")[:200]},
            root=root,
        )
    row.update(
        {
            "streak": streak,
            "circuit": circuit,
            "last_reason": reason,
            "last_utc": _now_iso(),
            "last_error": (error or "")[:300],
        }
    )
    _set_inst_row(root, iid, row)
    return {"streak": streak, "circuit": circuit, "reason": reason}


def heal_adb_for_dump(
    instance: dict[str, Any],
    *,
    root: Path | None = None,
    allow_recover_streamers: bool = True,
) -> dict[str, Any]:
    """Heal ladder: connect_adb → BACK to rail → optional recover_streamers.

    ``empty_hierarchy`` on a live fullscreen player is normal (nodes, no texts).
    Force-stopping Streamers for that is the wrong medicine — it thrashes opens
    and can surface BlueStacks power sheets. Prefer BACK to the parent guide.
    """
    from .instances import adb, connect_adb

    iid = _instance_id(instance)
    row = _inst_row(root, iid)
    streak = int(row.get("streak") or 0)
    last_reason = str(row.get("last_reason") or row.get("reason") or "")
    steps: list[dict[str, Any]] = []
    heal = "none"

    if streak >= HEAL_CONNECT_STREAK or str(row.get("circuit") or "") == "open":
        try:
            ok, out = connect_adb(instance)
            steps.append({"step": "connect_adb", "ok": bool(ok), "out": (out or "")[:120]})
            heal = "connect_adb"
        except Exception as exc:  # noqa: BLE001
            steps.append({"step": "connect_adb", "ok": False, "error": str(exc)})

    # Hard force-stop only for real device/ADB death — not empty player trees.
    hard_adb = last_reason in {
        "device_offline",
        "not_found",
        "pull_failed",
        "adb_not_ready",
        "protocol_fault",
    }
    # Soft surface chrome before any app kill — covers empty player dumps.
    emptyish = last_reason in {
        "empty_hierarchy",
        "soft_empty",
        "dump_failed",
        "unknown",
    }
    if emptyish or (streak >= HEAL_RECOVER_STREAK and not hard_adb):
        try:
            # One BACK surfaces player chrome / dismisses power sheet. Three BACKs
            # were dumping us on BlueStacks home (POPULAR GAMES) mid-olympics.
            adb(instance, ["shell", "input", "keyevent", "4"])
            time.sleep(0.4)
            steps.append({"step": "back_to_rail", "ok": True, "keys": [4]})
            heal = "back_to_rail"
        except Exception as exc:  # noqa: BLE001
            steps.append({"step": "back_to_rail", "ok": False, "error": str(exc)})

    if (
        allow_recover_streamers
        and streak >= HEAL_RECOVER_STREAK
        and hard_adb
    ):
        try:
            from .streamers_alive import recover_streamers

            hard = recover_streamers(iid, root=root, wait_s=8.0)
            steps.append(
                {
                    "step": "recover_streamers",
                    "ok": bool(hard.get("ok")),
                    "after": (hard.get("after") or {}).get("reason"),
                }
            )
            heal = "recover_streamers"
        except Exception as exc:  # noqa: BLE001
            steps.append({"step": "recover_streamers", "ok": False, "error": str(exc)})

    row["last_heal"] = heal
    row["last_heal_utc"] = _now_iso()
    row["last_heal_steps"] = steps
    _set_inst_row(root, iid, row)
    if heal != "none":
        _emit(
            "ui_dump_heal",
            instance=instance,
            detail=heal,
            ok=any(s.get("ok") for s in steps) if steps else False,
            extra={"streak": streak, "steps": steps, "last_reason": last_reason},
            root=root,
        )
    return {"heal": heal, "streak": streak, "steps": steps}


def circuit_is_open(instance: dict[str, Any], root: Path | None = None) -> bool:
    return str(get_circuit(instance, root).get("circuit") or "") == "open"


def _count_texts(root: ET.Element) -> tuple[int, int]:
    nodes = sum(1 for _ in root.iter("node"))
    texts = sum(1 for n in root.iter("node") if (n.attrib.get("text") or "").strip())
    return nodes, texts


def dump_ui_hard(
    instance: dict[str, Any],
    dest: Path,
    *,
    root: Path | None = None,
    caller: str = "hard",
    heal: bool = True,
) -> ET.Element:
    """Hard dump: raise on null-root / empty. Emit + heal + streak bookkeeping."""
    from .instances import adb

    dest.parent.mkdir(parents=True, exist_ok=True)
    data_root = root or ensure_data_layout()
    t0 = time.perf_counter()
    last = ""
    last_rc = -1
    for attempt in range(2):
        rc, out = adb(
            instance,
            ["shell", "uiautomator", "dump", "/sdcard/ohush_ui.xml"],
            timeout=12.0,
        )
        last_rc = int(rc)
        last = (out or "").strip()
        if rc == 0 and "null root" not in last.lower() and "error" not in last.lower():
            break
        reason = classify_dump_error(last or f"rc={last_rc}", adb_stdout=last)
        _emit(
            "ui_dump_retry",
            instance=instance,
            detail=reason,
            ok=False,
            extra={
                "caller": caller,
                "mode": "hard",
                "attempt": attempt + 1,
                "rc": last_rc,
                "adb_stdout_tail": last[:200],
                "dest": dest.name,
            },
            root=data_root,
        )
        time.sleep(0.35 + attempt * 0.25)
    else:
        why = last or "(empty adb stdout)"
        reason = classify_dump_error(why, adb_stdout=why)
        info = record_dump_failure(instance, reason=reason, root=data_root, error=why)
        if heal:
            heal_adb_for_dump(instance, root=data_root)
        _emit(
            "ui_dump_fail",
            instance=instance,
            detail=reason,
            ok=False,
            extra={
                "caller": caller,
                "mode": "hard",
                "rc": last_rc,
                "adb_stdout_tail": why[:200],
                "dest": dest.name,
                "streak": info.get("streak"),
                "circuit": info.get("circuit"),
                "ms": round((time.perf_counter() - t0) * 1000, 1),
            },
            root=data_root,
        )
        raise RuntimeError(
            f"uiautomator dump failed rc={last_rc} attempts=2 "
            f"dest={dest.name} adb={why!r}"
        )

    rc, out = adb(instance, ["pull", "/sdcard/ohush_ui.xml", str(dest)], timeout=12.0)
    if rc != 0:
        err = (out or "").strip()
        reason = "pull_failed"
        info = record_dump_failure(instance, reason=reason, root=data_root, error=err)
        if heal:
            heal_adb_for_dump(instance, root=data_root)
        _emit(
            "ui_dump_fail",
            instance=instance,
            detail=reason,
            ok=False,
            extra={
                "caller": caller,
                "mode": "hard",
                "dest": dest.name,
                "error": err[:200],
                "streak": info.get("streak"),
                "circuit": info.get("circuit"),
            },
            root=data_root,
        )
        raise RuntimeError(f"pull ui xml failed rc={rc} dest={dest.name}: {err!r}")

    tree = ET.parse(dest).getroot()
    nodes, n_texts = _count_texts(tree)
    if n_texts == 0:
        reason = "empty_hierarchy"
        info = record_dump_failure(
            instance,
            reason=reason,
            root=data_root,
            error=f"nodes={nodes}",
        )
        if heal:
            heal_adb_for_dump(instance, root=data_root)
            # BACK-to-rail only helps if we dump again — otherwise callers just see raise.
            time.sleep(0.45)
            rc2, out2 = adb(
                instance,
                ["shell", "uiautomator", "dump", "/sdcard/ohush_ui.xml"],
                timeout=12.0,
            )
            if rc2 == 0 and "null root" not in (out2 or "").lower():
                adb(instance, ["pull", "/sdcard/ohush_ui.xml", str(dest)], timeout=12.0)
                try:
                    tree2 = ET.parse(dest).getroot()
                    nodes2, n_texts2 = _count_texts(tree2)
                    if n_texts2 > 0:
                        ms = round((time.perf_counter() - t0) * 1000, 1)
                        record_dump_success(instance, root=data_root, ms=ms)
                        _emit(
                            "ui_dump_ok",
                            instance=instance,
                            detail="ok_after_back_to_rail",
                            ok=True,
                            extra={
                                "caller": caller,
                                "mode": "hard",
                                "dest": dest.name,
                                "nodes": nodes2,
                                "texts": n_texts2,
                                "ms": ms,
                            },
                            root=data_root,
                        )
                        return tree2
                except Exception:
                    pass
        _emit(
            "ui_dump_fail",
            instance=instance,
            detail=reason,
            ok=False,
            extra={
                "caller": caller,
                "mode": "hard",
                "dest": dest.name,
                "nodes": nodes,
                "texts": 0,
                "streak": info.get("streak"),
                "circuit": info.get("circuit"),
                "ms": round((time.perf_counter() - t0) * 1000, 1),
            },
            root=data_root,
        )
        raise RuntimeError(
            f"uiautomator dump empty hierarchy dest={dest.name} "
            f"nodes={nodes} bytes={dest.stat().st_size if dest.is_file() else 0}"
        )

    ms = round((time.perf_counter() - t0) * 1000, 1)
    record_dump_success(instance, root=data_root, ms=ms)
    # Sample oks lightly when env asks for verbose; always after heal/circuit.
    if os.environ.get("HUSH_UI_DUMP_LOG_OK", "").strip() in {"1", "true", "yes"}:
        _emit(
            "ui_dump_ok",
            instance=instance,
            detail="ok",
            ok=True,
            extra={
                "caller": caller,
                "mode": "hard",
                "dest": dest.name,
                "nodes": nodes,
                "texts": n_texts,
                "ms": ms,
            },
            root=data_root,
        )
    return tree


def dump_ui_soft(
    instance: dict[str, Any],
    dest: Path,
    *,
    tries: int = 3,
    root: Path | None = None,
    caller: str = "soft",
) -> ET.Element:
    """Soft dump: retry → heal once → one hard retry → tagged DUMP_FAILED (never silent empty)."""
    data_root = root or ensure_data_layout()
    last_exc = ""
    last_reason = "dump_failed"

    if circuit_is_open(instance, data_root):
        # Still allow one probe after heal so half-open recovery can succeed.
        heal_adb_for_dump(instance, root=data_root, allow_recover_streamers=True)

    for i in range(max(1, int(tries))):
        try:
            return dump_ui_hard(
                instance,
                dest,
                root=data_root,
                caller=caller,
                heal=False,
            )
        except Exception as e:  # noqa: BLE001
            last_exc = str(e)
            last_reason = classify_dump_error(e)
            _emit(
                "ui_dump_retry",
                instance=instance,
                detail=last_reason,
                ok=False,
                extra={
                    "caller": caller,
                    "mode": "soft",
                    "attempt": i + 1,
                    "tries": tries,
                    "error": last_exc[:200],
                    "dest": dest.name,
                },
                root=data_root,
            )
            time.sleep(0.8 + 0.4 * i)

    # Heal once, then one hard dump.
    info = record_dump_failure(
        instance, reason=last_reason, root=data_root, error=last_exc
    )
    heal_adb_for_dump(instance, root=data_root, allow_recover_streamers=True)
    try:
        return dump_ui_hard(
            instance,
            dest,
            root=data_root,
            caller=f"{caller}_after_heal",
            heal=False,
        )
    except Exception as e:  # noqa: BLE001
        last_exc = str(e)
        last_reason = classify_dump_error(e)
        info = record_dump_failure(
            instance, reason=last_reason, root=data_root, error=last_exc
        )

    _emit(
        "ui_dump_soft_empty",
        instance=instance,
        detail=last_reason,
        ok=False,
        extra={
            "caller": caller,
            "mode": "soft",
            "reason": last_reason,
            "error": last_exc[:200],
            "dest": dest.name,
            "streak": info.get("streak"),
            "circuit": info.get("circuit"),
            "fabricated": True,
        },
        root=data_root,
    )
    return write_dump_failed_xml(dest, reason=last_reason, error=last_exc)


def dump_health_summary(
    root: Path | None = None,
    *,
    hours: float = 24.0,
    max_lines: int = 8000,
) -> dict[str, Any]:
    """Roll up recent ui_dump_* events from farm_run.jsonl for boards."""
    from .farm_ops import run_log_path

    root = ensure_data_layout(root)
    path = run_log_path(root)
    cutoff = time.time() - max(1.0, hours) * 3600.0
    by_inst: dict[str, dict[str, Any]] = {}
    totals = {
        "ok": 0,
        "fail": 0,
        "soft_empty": 0,
        "heal": 0,
        "circuit_open": 0,
        "retry": 0,
    }
    last_events: list[dict[str, Any]] = []

    if path.is_file():
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]
        except OSError:
            lines = []
        for line in lines:
            if "ui_dump_" not in line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = str(row.get("event") or "")
            if not event.startswith("ui_dump_"):
                continue
            utc = str(row.get("utc") or "")
            try:
                ts = datetime.fromisoformat(utc.replace("Z", "+00:00")).timestamp()
            except Exception:
                ts = 0.0
            if ts and ts < cutoff:
                continue
            iid = str(row.get("instance_id") or "unknown")
            bucket = by_inst.setdefault(
                iid,
                {
                    "fail": 0,
                    "soft_empty": 0,
                    "heal": 0,
                    "circuit_open": 0,
                    "ok": 0,
                    "last_reason": None,
                    "last_utc": None,
                },
            )
            if event == "ui_dump_ok":
                totals["ok"] += 1
                bucket["ok"] += 1
            elif event == "ui_dump_fail":
                totals["fail"] += 1
                bucket["fail"] += 1
            elif event == "ui_dump_soft_empty":
                totals["soft_empty"] += 1
                bucket["soft_empty"] += 1
            elif event == "ui_dump_heal":
                totals["heal"] += 1
                bucket["heal"] += 1
            elif event == "ui_dump_circuit_open":
                totals["circuit_open"] += 1
                bucket["circuit_open"] += 1
            elif event == "ui_dump_retry":
                totals["retry"] += 1
            detail = str(row.get("detail") or "")
            bucket["last_reason"] = detail or (row.get("extra") or {}).get("reason")
            bucket["last_utc"] = utc
            last_events.append(
                {
                    "utc": utc,
                    "event": event,
                    "instance_id": iid,
                    "detail": detail,
                }
            )

    state = _load_state(root)
    circuits = {
        iid: {
            "streak": (row or {}).get("streak"),
            "circuit": (row or {}).get("circuit"),
            "last_reason": (row or {}).get("last_reason"),
        }
        for iid, row in (state.get("instances") or {}).items()
    }
    sick = [
        iid
        for iid, b in by_inst.items()
        if int(b.get("soft_empty") or 0) + int(b.get("fail") or 0) >= 3
        or int(b.get("circuit_open") or 0) > 0
    ]
    for iid, c in circuits.items():
        if str(c.get("circuit") or "") == "open" and iid not in sick:
            sick.append(iid)

    return {
        "hours": hours,
        "totals": totals,
        "by_instance": by_inst,
        "circuits": circuits,
        "sick_instances": sick,
        "last_events": last_events[-12:],
        "ok": len(sick) == 0,
    }


def dump_health_board_md(summary: dict[str, Any] | None = None, root: Path | None = None) -> str:
    summary = summary or dump_health_summary(root)
    lines = [
        "## Dump health (uiautomator)",
        "",
        f"Window **{summary.get('hours')}h** · "
        f"fail **{(summary.get('totals') or {}).get('fail', 0)}** · "
        f"soft_empty **{(summary.get('totals') or {}).get('soft_empty', 0)}** · "
        f"heal **{(summary.get('totals') or {}).get('heal', 0)}** · "
        f"circuit_open **{(summary.get('totals') or {}).get('circuit_open', 0)}**",
        "",
    ]
    sick = summary.get("sick_instances") or []
    if sick:
        lines.append(f"Sick: `{', '.join(sick)}`")
        lines.append("")
    by_inst = summary.get("by_instance") or {}
    if by_inst:
        lines.append("| Instance | Fail | Soft empty | Heal | Circuit events | Last reason |")
        lines.append("|---|---:|---:|---:|---:|---|")
        for iid, b in sorted(by_inst.items()):
            lines.append(
                f"| {iid} | {b.get('fail', 0)} | {b.get('soft_empty', 0)} | "
                f"{b.get('heal', 0)} | {b.get('circuit_open', 0)} | "
                f"{b.get('last_reason') or '—'} |"
            )
        lines.append("")
    circuits = summary.get("circuits") or {}
    open_c = {k: v for k, v in circuits.items() if str((v or {}).get("circuit")) == "open"}
    if open_c:
        lines.append("Open circuits: " + ", ".join(f"`{k}` streak={v.get('streak')}" for k, v in open_c.items()))
        lines.append("")
    lines.append("Events: `ui_dump_*` in `work/logs/farm_run.jsonl`.")
    lines.append("")
    return "\n".join(lines)
