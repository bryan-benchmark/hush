"""Channel Olympics — timed parent→child open accuracy drill.

Goal: open N wanted channels correctly within a wall-clock budget (default
100 targets / 100 minutes on two BlueStacks instances).

Wanted list priority:
1. All FLAGSHIPS (ABC/CBS/NBC/FOX × big DMAs) — section-child alphabet hunt
2. Sports linear ESPN_US / ESPN2_US — nav routes
3. Fill from guide_catalog US * SECTION affiliates (unique call letters)

Success = open ok + identity match (locals: calls/network; linear: selected title).
"""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout
from .us_locals import (
    FLAGSHIPS,
    NETWORKS,
    SECTION_FOR,
    ensure_market_local_shortcuts,
    market_token,
    open_local,
    parse_local_title,
)

DEFAULT_INSTANCES = ("Nougat32", "Nougat32_1")
LINEAR_TARGETS = (
    {"id": "ESPN_US", "kind": "sports_linear", "nav_route": "ESPN_US", "want_title": "US: ESPN"},
    {"id": "ESPN2_US", "kind": "sports_linear", "nav_route": "ESPN2_US", "want_title": "US: ESPN 2"},
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def olympics_dir(root: Path | None = None) -> Path:
    d = ensure_data_layout(root) / "indexes" / "channel_olympics"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _flagship_targets() -> list[dict[str, Any]]:
    """Round-robin networks so a short smoke list is not ABC-only."""
    by_net: dict[str, list[dict[str, Any]]] = {net: [] for net in NETWORKS}
    for net in NETWORKS:
        for row in FLAGSHIPS[net]:
            tok = market_token(row["market"]) or row["calls"]
            by_net[net].append(
                {
                    "id": f"{net}_{tok}",
                    "kind": "local",
                    "network": net,
                    "market": row["market"],
                    "calls": row["calls"],
                    "state": row["state"],
                    "city": row["city"],
                    "section": SECTION_FOR[net],
                    "source": "flagship",
                }
            )
    out: list[dict[str, Any]] = []
    max_len = max(len(v) for v in by_net.values())
    for i in range(max_len):
        for net in NETWORKS:
            if i < len(by_net[net]):
                out.append(by_net[net][i])
    return out


def _catalog_fill(n_needed: int, *, seen_calls: set[str], root: Path | None) -> list[dict[str, Any]]:
    """Extra US * SECTION affiliates from the guide DB (not already in flagships)."""
    if n_needed <= 0:
        return []
    try:
        from .guide_catalog import lookup
    except Exception:
        return []

    # Prefer mid/large markets: skip obvious tiny/remote when we have plenty.
    demote_city = re.compile(
        r"anchorage|fairbanks|juneau|honolulu|guam|saipan|virgin island",
        re.I,
    )
    # Ranked queues per network, then round-robin so fill is not ABC-only.
    queues: dict[str, list[dict[str, Any]]] = {net: [] for net in NETWORKS}
    for net in NETWORKS:
        # Guide DB often mis-tags group_name (everything under US ABC SECTION).
        # Trust network + title/calls; open still uses the correct SECTION_FOR parent.
        rows = lookup(network=net, limit=160, root=root, prefer_home=False)
        ranked: list[tuple[int, dict[str, Any]]] = []
        for r in rows:
            calls = str(r.get("calls") or "").upper().strip()
            if not calls or calls in seen_calls:
                continue
            title = str(r.get("title") or "")
            city = str(r.get("city") or r.get("market") or "")
            if demote_city.search(city) or demote_city.search(title):
                continue
            parsed = parse_local_title(title) or {}
            score = 0
            if not r.get("demoted"):
                score += 50
            if parsed.get("state"):
                score += 20
            if " | " in title:
                score += 10
            ranked.append((score, r))
        ranked.sort(key=lambda x: (-x[0], int(x[1].get("number") or 99999)))
        queues[net] = [r for _sc, r in ranked]

    filled: list[dict[str, Any]] = []
    idxs = {net: 0 for net in NETWORKS}
    while len(filled) < n_needed:
        progressed = False
        for net in NETWORKS:
            if len(filled) >= n_needed:
                break
            q = queues[net]
            i = idxs[net]
            while i < len(q):
                r = q[i]
                i += 1
                calls = str(r.get("calls") or "").upper().strip()
                if not calls or calls in seen_calls:
                    continue
                title = str(r.get("title") or "")
                parsed = parse_local_title(title) or {}
                city = str(parsed.get("city") or r.get("city") or r.get("market") or calls)
                state = str(parsed.get("state") or "")
                seen_calls.add(calls)
                filled.append(
                    {
                        "id": f"{net}_{calls}",
                        "kind": "local",
                        "network": net,
                        "market": city,
                        "calls": calls,
                        "state": state,
                        "city": city,
                        "section": SECTION_FOR[net],
                        "channel_number": r.get("number"),
                        "channel_title": title,
                        "source": "catalog",
                        "pick_override": True,
                    }
                )
                progressed = True
                break
            idxs[net] = i
        if not progressed:
            break
    return filled


def build_wanted(
    n: int = 100,
    *,
    include_linear: bool = True,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Build the olympics target list (stable order)."""
    root = ensure_data_layout(root)
    wanted: list[dict[str, Any]] = []
    seen_calls: set[str] = set()
    seen_ids: set[str] = set()

    # Put linear early so smoke (n≈12) exercises nav + locals.
    if include_linear:
        for t in LINEAR_TARGETS:
            if t["id"] in seen_ids:
                continue
            seen_ids.add(t["id"])
            wanted.append(dict(t))

    for t in _flagship_targets():
        if len(wanted) >= n:
            break
        if t["id"] in seen_ids:
            continue
        seen_ids.add(t["id"])
        seen_calls.add(str(t["calls"]).upper())
        wanted.append(t)

    # Trim if linear pushed past n (keep linear + fill locals).
    if len(wanted) > n:
        linear = [t for t in wanted if t.get("kind") == "sports_linear"]
        locals_ = [t for t in wanted if t.get("kind") != "sports_linear"]
        wanted = linear + locals_
        wanted = wanted[:n]

    if len(wanted) < n:
        for t in _catalog_fill(n - len(wanted), seen_calls=seen_calls, root=root):
            if t["id"] in seen_ids:
                continue
            seen_ids.add(t["id"])
            wanted.append(t)
            if len(wanted) >= n:
                break

    return wanted[:n]


def _open_one(target: dict[str, Any], *, instance_id: str, root: Path) -> dict[str, Any]:
    """Open one target; return score row."""
    t0 = time.perf_counter()
    kind = str(target.get("kind") or "local")
    tid = str(target.get("id") or "")
    row: dict[str, Any] = {
        "id": tid,
        "kind": kind,
        "instance_id": instance_id,
        "want_calls": target.get("calls"),
        "want_network": target.get("network"),
        "want_title": target.get("want_title") or target.get("channel_title"),
        "section": target.get("section"),
        "source": target.get("source"),
    }
    try:
        if kind == "sports_linear":
            from .streamers_nav import run_route

            out = run_route(
                str(target["nav_route"]),
                instance_id=instance_id,
                root=root,
                open_player=True,
                save_as=tid,
            )
            selected = str(out.get("selected_title") or "")
            if not selected:
                for step in reversed(out.get("atoms") or []):
                    chosen = (step.get("result") or {}).get("chosen") or step.get("chosen")
                    if chosen:
                        selected = str(chosen)
                        break
            want = str(target.get("want_title") or "")
            title_ok = bool(selected) and (
                not want
                or want.lower() in selected.lower()
                or selected.lower() in want.lower()
            )
            # Identity on the rail/row wins even when post-open dump is empty
            # (fullscreen player → empty_hierarchy → nav raw_ok false).
            ok = title_ok
            err = None
            if not ok:
                err = out.get("error") or f"title_mismatch want={want!r} got={selected!r}"
            elif not out.get("ok"):
                err = None  # scored ok on identity; raw open may still be dump-soft
            row.update(
                {
                    "ok": ok,
                    "open_via": "nav",
                    "selected_title": selected,
                    "error": err,
                    "raw_ok": bool(out.get("ok")),
                }
            )
        else:
            # Locals: parent section → alphabetical child.
            out = open_local(
                str(target["network"]),
                market=str(target.get("market")),
                shortcut_id=tid,
                instance_id=instance_id,
                open_player=True,
                save=True,
                root=root,
            )
            selected = str(out.get("selected_title") or out.get("channel_title") or "")
            got_calls = None
            ident = out.get("identity") if isinstance(out.get("identity"), dict) else {}
            got_calls = ident.get("calls") or (out.get("pick") or {}).get("calls")
            parsed = parse_local_title(selected) if selected else None
            if parsed and not got_calls:
                got_calls = parsed.get("calls")
            want_calls = str(target.get("calls") or "").upper()
            ok = bool(out.get("ok"))
            if ok and want_calls and got_calls and str(got_calls).upper() != want_calls:
                ok = False
                err = f"calls_mismatch want={want_calls} got={got_calls}"
            else:
                err = None if ok else str(out.get("error") or "open_failed")
            row.update(
                {
                    "ok": ok,
                    "open_via": out.get("open_via") or out.get("via") or "section_child",
                    "selected_title": selected,
                    "got_calls": got_calls,
                    "error": err,
                    "raw_ok": bool(out.get("ok")),
                }
            )
    except Exception as exc:  # noqa: BLE001
        row.update(
            {
                "ok": False,
                "open_via": None,
                "selected_title": None,
                "error": f"{type(exc).__name__}:{exc}",
                "raw_ok": False,
            }
        )
    row["elapsed_s"] = round(time.perf_counter() - t0, 2)
    row["utc"] = _now_iso()
    return row


def _open_one_safe(target: dict[str, Any], *, instance_id: str, root: Path) -> dict[str, Any]:
    """Locals not in FLAGSHIPS use an explicit section-child pick."""
    if target.get("kind") == "local" and target.get("pick_override"):
        t0 = time.perf_counter()
        tid = str(target.get("id") or "")
        pick = {
            "network": target["network"],
            "section": target.get("section") or SECTION_FOR[str(target["network"])],
            "market": target.get("market") or target.get("city") or target.get("calls"),
            "calls": target["calls"],
            "state": target.get("state") or "",
            "city": target.get("city") or target.get("market") or "",
            "shortcut_id": tid,
            "why": "olympics_catalog",
        }
        try:
            out = open_local(
                str(pick["network"]),
                pick=pick,
                shortcut_id=tid,
                instance_id=instance_id,
                open_player=True,
                save=True,
                root=root,
            )
            selected = str(out.get("selected_title") or "")
            parsed = parse_local_title(selected) if selected else None
            got = (parsed or {}).get("calls") or (out.get("pick") or {}).get("calls")
            want = str(target.get("calls") or "").upper()
            ok = bool(out.get("ok")) and (not want or str(got or "").upper() == want)
            return {
                "id": tid,
                "kind": "local",
                "instance_id": instance_id,
                "want_calls": want,
                "want_network": target.get("network"),
                "want_title": target.get("channel_title"),
                "section": pick["section"],
                "source": "catalog",
                "ok": ok,
                "open_via": out.get("via") or "section_child",
                "selected_title": selected,
                "got_calls": got,
                "error": None if ok else str(out.get("error") or "calls_mismatch"),
                "raw_ok": bool(out.get("ok")),
                "elapsed_s": round(time.perf_counter() - t0, 2),
                "utc": _now_iso(),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "id": tid,
                "kind": "local",
                "instance_id": instance_id,
                "ok": False,
                "error": f"{type(exc).__name__}:{exc}",
                "elapsed_s": round(time.perf_counter() - t0, 2),
                "utc": _now_iso(),
                "source": "catalog",
            }
    return _open_one(target, instance_id=instance_id, root=root)


def run_olympics(
    *,
    n: int = 100,
    budget_min: float = 100.0,
    instances: tuple[str, ...] | list[str] = DEFAULT_INSTANCES,
    include_linear: bool = True,
    recover_first: bool = True,
    root: Path | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Run the timed drill. Stops when list done or budget exhausted."""
    root = ensure_data_layout(root)
    ensure_market_local_shortcuts(root=root)
    wanted = build_wanted(n, include_linear=include_linear, root=root)
    instances = tuple(instances) or DEFAULT_INSTANCES
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    label = label or f"n{len(wanted)}_{int(budget_min)}m"
    out_dir = olympics_dir(root) / f"{run_id}_{label}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "wanted.json").write_text(json.dumps(wanted, indent=2) + "\n", encoding="utf-8")

    if recover_first:
        from .streamers_recover import ensure_ready_for_open

        for iid in instances:
            try:
                ensure_ready_for_open(iid, root=root)
            except Exception:
                pass

    budget_s = float(budget_min) * 60.0
    t_start = time.perf_counter()
    deadline = t_start + budget_s
    results: list[dict[str, Any]] = []
    lock = threading.Lock()
    stop = threading.Event()

    # Split targets across instances (round-robin).
    queues: dict[str, list[dict[str, Any]]] = {iid: [] for iid in instances}
    for i, t in enumerate(wanted):
        queues[instances[i % len(instances)]].append(t)

    def worker(iid: str, targets: list[dict[str, Any]]) -> None:
        for target in targets:
            if stop.is_set() or time.perf_counter() >= deadline:
                stop.set()
                break
            row = _open_one_safe(target, instance_id=iid, root=root)
            row["budget_left_s"] = round(max(0.0, deadline - time.perf_counter()), 1)
            with lock:
                results.append(row)
                with (out_dir / "results.jsonl").open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            if not row.get("ok"):
                # Light unstick only — full ensure_ready_for_open storms on
                # fullscreen empty dumps and burns the wall-clock budget.
                try:
                    from .instances import get_instance, adb, connect_adb

                    inst = get_instance(iid, root)
                    connect_adb(inst)
                    for _ in range(2):
                        adb(inst, ["shell", "input", "keyevent", "4"])
                        time.sleep(0.35)
                except Exception:
                    pass

    with ThreadPoolExecutor(max_workers=len(instances)) as pool:
        futs = [pool.submit(worker, iid, queues[iid]) for iid in instances]
        for fut in as_completed(futs):
            try:
                fut.result()
            except Exception:
                pass

    elapsed = time.perf_counter() - t_start
    attempted = list(results)
    ok_n = sum(1 for r in attempted if r.get("ok"))
    fail = [r for r in attempted if not r.get("ok")]
    times = [float(r.get("elapsed_s") or 0) for r in attempted if r.get("elapsed_s") is not None]
    times_sorted = sorted(times)
    summary = {
        "ok": True,
        "run_id": run_id,
        "label": label,
        "out_dir": str(out_dir),
        "wanted_n": len(wanted),
        "attempted_n": len(attempted),
        "ok_n": ok_n,
        "fail_n": len(fail),
        "perfect": ok_n == len(wanted) and len(attempted) == len(wanted),
        "pass_rate": round(ok_n / len(attempted), 4) if attempted else 0.0,
        "elapsed_s": round(elapsed, 1),
        "budget_min": budget_min,
        "budget_exhausted": elapsed >= budget_s - 1.0 or stop.is_set() and len(attempted) < len(wanted),
        "instances": list(instances),
        "elapsed_p50_s": times_sorted[len(times_sorted) // 2] if times_sorted else None,
        "elapsed_p95_s": times_sorted[int(len(times_sorted) * 0.95)] if times_sorted else None,
        "elapsed_max_s": max(times_sorted) if times_sorted else None,
        "failures": [
            {"id": r.get("id"), "error": r.get("error"), "elapsed_s": r.get("elapsed_s"), "instance_id": r.get("instance_id")}
            for r in fail[:40]
        ],
        "utc": _now_iso(),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    board = [
        f"# Channel Olympics — {run_id}",
        "",
        f"- wanted: **{len(wanted)}** | attempted: **{len(attempted)}** | ok: **{ok_n}** | fail: **{len(fail)}**",
        f"- pass rate: **{summary['pass_rate']:.1%}** | perfect: **{summary['perfect']}**",
        f"- wall: **{summary['elapsed_s']}s** / budget {budget_min}m",
        f"- open latency p50/p95/max: {summary['elapsed_p50_s']} / {summary['elapsed_p95_s']} / {summary['elapsed_max_s']} s",
        f"- instances: {', '.join(instances)}",
        "",
        "## Failures",
        "",
    ]
    if not fail:
        board.append("_none_")
    else:
        board.append("| id | instance | s | error |")
        board.append("|---|---|---|---|")
        for r in fail[:40]:
            board.append(
                f"| `{r.get('id')}` | {r.get('instance_id')} | {r.get('elapsed_s')} | "
                f"{str(r.get('error') or '')[:80]} |"
            )
    (out_dir / "SCOREBOARD.md").write_text("\n".join(board) + "\n", encoding="utf-8")
    latest = olympics_dir(root) / "LATEST.md"
    latest.write_text("\n".join(board) + f"\n\nDir: `{out_dir}`\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Channel Olympics — timed open accuracy drill")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="Print / write wanted list (no opens)")
    p_list.add_argument("--n", type=int, default=100)
    p_list.add_argument("--no-linear", action="store_true")
    p_list.add_argument("--json", action="store_true")

    p_smoke = sub.add_parser("smoke", help="Short drill: 12 targets / 20 min")
    p_smoke.add_argument("--n", type=int, default=12)
    p_smoke.add_argument("--budget-min", type=float, default=20.0)
    p_smoke.add_argument("--instances", default="Nougat32,Nougat32_1")
    p_smoke.add_argument("--no-recover", action="store_true")

    p_run = sub.add_parser("run", help="Full drill: N targets / budget minutes")
    p_run.add_argument("--n", type=int, default=100)
    p_run.add_argument("--budget-min", type=float, default=100.0)
    p_run.add_argument("--instances", default="Nougat32,Nougat32_1")
    p_run.add_argument("--no-linear", action="store_true")
    p_run.add_argument("--no-recover", action="store_true")
    p_run.add_argument("--label", default=None)

    args = p.parse_args(argv)
    root = ensure_data_layout()

    if args.cmd == "list":
        wanted = build_wanted(args.n, include_linear=not args.no_linear, root=root)
        path = olympics_dir(root) / f"wanted_n{len(wanted)}.json"
        path.write_text(json.dumps(wanted, indent=2) + "\n", encoding="utf-8")
        if args.json:
            print(json.dumps({"ok": True, "n": len(wanted), "path": str(path), "wanted": wanted}, indent=2))
        else:
            print(f"wanted={len(wanted)} → {path}")
            for t in wanted:
                print(
                    f"  {t.get('id'):<14} {t.get('kind'):<14} "
                    f"{t.get('section') or t.get('nav_route') or ''} "
                    f"{t.get('calls') or t.get('want_title') or ''}"
                )
        return 0

    if args.cmd in ("smoke", "run"):
        instances = tuple(x.strip() for x in str(args.instances).split(",") if x.strip())
        summary = run_olympics(
            n=int(args.n),
            budget_min=float(args.budget_min),
            instances=instances,
            include_linear=not getattr(args, "no_linear", False),
            recover_first=not args.no_recover,
            root=root,
            label=getattr(args, "label", None) or ("smoke" if args.cmd == "smoke" else "full"),
        )
        print(json.dumps(summary, indent=2))
        return 0 if summary.get("perfect") else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
