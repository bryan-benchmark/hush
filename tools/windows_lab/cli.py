"""Unified CLI: python -m tools.windows_lab <command>"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "usage: python -m tools.windows_lab "
            "{inventory|ingest|analyze|health|capture|instances|channel|"
            "session|schedule|catalog|archive|ota|multi-instance|salvation|"
            "farm|ops|streams|guide-catalog|desk|tnf|open|nav|olympics|todos|us-locals|notify|"
            "process-loopback|windows} ..."
        )
        return 0
    cmd, rest = argv[0], argv[1:]
    # Normalize source aliases in remaining argv for subcommands that take --source.
    rest = _normalize_source_alias(rest)

    if cmd == "inventory":
        from .inventory import main as m
    elif cmd == "ingest":
        from .ingest import main as m
    elif cmd == "analyze":
        from .analyze import main as m
    elif cmd == "health":
        from .health import main as m
    elif cmd == "capture":
        from .capture import main as m
    elif cmd == "instances":
        from .instances import main as m
    elif cmd == "channel":
        from .channel import main as m
    elif cmd in ("session", "sessions"):
        from .session_capture import main as m

        # session start ...  -> allow bare flags by injecting nothing; support "start" verb
        if rest and rest[0] == "start":
            rest = rest[1:]
        return m(rest)
    elif cmd == "schedule":
        from .scheduler import main as m
    elif cmd == "catalog":
        from .catalog import main as m
    elif cmd == "archive":
        from .visual_archive import main as m

        return m(rest)
    elif cmd == "ota":
        from .ota import main as m
    elif cmd in ("multi-instance", "multi_instance"):
        from .multi_instance import main as m
    elif cmd == "salvation":
        from .salvation import main as m
    elif cmd in ("ops", "farm-ops", "farm_ops"):
        from .farm_ops import main as m

        return m(rest)
    elif cmd in ("streams", "stream-status", "stream_status", "uptime"):
        from .stream_status import main as m

        return m(rest)
    elif cmd in ("guide-catalog", "guide_catalog", "channels-db", "guide-db"):
        from .guide_catalog import main as m

        return m(rest)
    elif cmd == "farm":
        # Three ops + worker helpers:
        #   record | label | human | status | orchestrate → farm_orchestrate
        #   loop → farm_loop (scheduled autonomy)
        #   tick | backlog → farm_worker
        #   cloud-sync → farm_cloud_sync (push help clips to ohush.co GCS)
        #   import → farm_import (authorized_sources → farm takes)
        #   plan | board | prepare | … → coverage_farm
        #   ops → farm_ops (run log / board / preflight / preempt)
        if rest and rest[0] in {"ops", "preflight"}:
            from .farm_ops import main as m

            # farm preflight → ops preflight; farm ops … → ops …
            if rest[0] == "preflight":
                return m(rest)
            return m(rest[1:])
        if not rest:
            from .farm_orchestrate import main as m

            return m(["status"])
        head = rest[0]
        if head in {"tick", "backlog"}:
            from .farm_worker import main as m

            return m(rest)
        if head in {"cloud-sync", "sync-cloud"}:
            from .farm_cloud_sync import main as m

            return m(rest[1:])
        if head == "import":
            from .farm_import import main as m

            return m(rest[1:])
        if head == "loop":
            from .farm_loop import main as m

            return m(rest[1:])
        if head in {"live-scorecard", "live_scorecard", "mute-scorecard"}:
            from .farm_live_scorecard import main as m

            return m(rest[1:])
        if head in {"timeline", "timelines"}:
            from .farm_timeline import main as m

            return m(rest[1:])
        if head in {"export-acoustic-gold", "export_acoustic_gold", "export-gold"}:
            from .export_farm_acoustic_gold import main as m

            return m(rest[1:])
        if head in {"vision-timeline", "vision_timeline"}:
            from .farm_vision_timeline import main as m

            return m(rest[1:])
        if head in {"embed-extract", "embed_extract", "farm-embed"}:
            from .farm_embed_extract import main as m

            return m(rest[1:])
        if head in {"atomic-audit", "atomic_audit", "audit"}:
            from .farm_atomic_audit import main as m

            return m(rest[1:])
        if head in {"episode-triage", "episode_triage"}:
            from .farm_episode_triage import main as m

            return m(rest[1:])
        if head in {"episode-viewer", "episode_viewer", "triage-ui"}:
            from .farm_episode_viewer import main as m

            return m(rest[1:])
        if head in {"streamers-alive", "alive"}:
            from .streamers_alive import main as m

            return m(rest[1:])
        if head in {"record", "label", "human", "status", "orchestrate"}:
            from .farm_orchestrate import main as m

            return m(rest)
        from .coverage_farm import main as m

        return m(rest)
    elif cmd == "tnf":
        from .tnf_thursday import main as m
    elif cmd == "open":
        from .streamers_open import main as m
    elif cmd in ("nav", "streamers-nav", "streamers_nav"):
        from .streamers_nav import main as m
    elif cmd in ("us-locals", "us_locals", "locals"):
        from .us_locals import main as m
    elif cmd in ("olympics", "channel-olympics", "channel_olympics"):
        from .channel_olympics import main as m
    elif cmd == "notify":
        from .notify import main as m
    elif cmd in ("todos", "todo", "open-model-todos", "hush-todos"):
        from .open_model_todos import main as m
    elif cmd in ("process-loopback", "process_loopback", "pid-loopback"):
        from .process_loopback import main as m
    elif cmd in ("capacity-probe-3", "capacity_probe_3", "probe-3"):
        from .capacity_probe_3 import main as m
    elif cmd in ("progressive-capacity", "progressive_capacity", "ramp-streams"):
        from .progressive_capacity import main as m
    elif cmd in ("recover", "streamers-recover", "streamers_recover"):
        from .streamers_recover import main as m
    elif cmd in ("heartbeat-fix", "heartbeat_fix", "hb-fix"):
        from .heartbeat_fix import main as m
    elif cmd in ("frame-watch", "frame_watch", "frames"):
        from .frame_watch import main as m
    elif cmd in ("desk", "desk-orchestrator", "orchestrator"):
        from .desk_orchestrator import main as m
    elif cmd in ("windows", "window", "layout", "window-layout"):
        from .window_layout import main as m

        if cmd == "layout" and (not rest or rest[0] not in ("list", "layout")):
            rest = ["layout", *rest]
        return m(rest)
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 2
    return m(rest)


def _normalize_source_alias(argv: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--source" and i + 1 < len(argv):
            val = argv[i + 1]
            if val in ("ota", "antenna"):
                val = "ota_antenna"
            out.extend(["--source", val])
            i += 2
            continue
        if arg.startswith("--source="):
            val = arg.split("=", 1)[1]
            if val in ("ota", "antenna"):
                val = "ota_antenna"
            out.append(f"--source={val}")
            i += 1
            continue
        out.append(arg)
        i += 1
    return out


if __name__ == "__main__":
    raise SystemExit(main())
