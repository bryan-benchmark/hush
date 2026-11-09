"""Unified CLI: python -m tools.windows_lab <command>"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "usage: python -m tools.windows_lab "
            "{inventory|ingest|analyze|health|capture|instances|channel|"
            "session|schedule|catalog|ota|multi-instance} ..."
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
    elif cmd == "ota":
        from .ota import main as m
    elif cmd in ("multi-instance", "multi_instance"):
        from .multi_instance import main as m
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
