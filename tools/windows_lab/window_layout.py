"""Arrange BlueStacks HD-Player windows on the Windows work area.

Open-model / Cursor / desk use this when instances are off-screen, tiny, or
stacked — so operators and computer-use can see the picture. ADB capture does
not need the window visible; layout is for humans and desktop aiming.

```powershell
python -m tools.windows_lab windows list
python -m tools.windows_lab windows layout --mode auto
python -m tools.windows_lab windows layout --mode fill --instances "player 0"
python -m tools.windows_lab windows layout --mode split --instances "player 0" "player 1"
python -m tools.windows_lab windows layout --mode grid
```
"""

from __future__ import annotations

import json
import math
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

from .instances import get_instance, list_instances

user32 = ctypes.windll.user32
SW_RESTORE = 9
SW_SHOW = 5
SWP_NOZORDER = 0x0004
SWP_SHOWWINDOW = 0x0040
HWND_TOP = 0
# BlueStacks Android surface is 16:9 (1600x900). Fit that aspect inside each tile
# so the host chrome does not fight a portrait cell and jump back.
ASPECT = 16 / 9


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


@dataclass
class WorkArea:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass
class PlayerWindow:
    pid: int
    title: str
    hwnd: int
    instance_id: str | None
    left: int
    top: int
    width: int
    height: int


def work_area() -> WorkArea:
    """Primary monitor work area (excludes taskbar)."""
    rect = RECT()
    # SPI_GETWORKAREA = 0x0030
    if not user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
        # Fallback: full primary screen
        return WorkArea(0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    return WorkArea(rect.left, rect.top, rect.right, rect.bottom)


def _enum_hd_players() -> list[PlayerWindow]:
    """All HD-Player main windows with a title (one PowerShell pass)."""
    import subprocess

    title_to_id: dict[str, str] = {}
    for row in list_instances():
        t = str(row.get("window_title") or "").strip()
        if t:
            title_to_id[t] = str(row["id"])

    ps = r"""
Add-Type -ErrorAction SilentlyContinue @'
using System;
using System.Runtime.InteropServices;
public class OhushWin {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
}
'@
Get-Process HD-Player -ErrorAction SilentlyContinue |
  Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle } |
  ForEach-Object {
    $rr = New-Object OhushWin+RECT
    [void][OhushWin]::GetWindowRect($_.MainWindowHandle, [ref]$rr)
    '{0}|{1}|{2}|{3}|{4}|{5}|{6}' -f $_.Id, $_.MainWindowTitle, ([int64]$_.MainWindowHandle),
      $rr.L, $rr.T, ($rr.R-$rr.L), ($rr.B-$rr.T)
  }
"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=20,
        )
        raw = r.stdout or ""
    except Exception:  # noqa: BLE001
        raw = ""

    out: list[PlayerWindow] = []
    for line in raw.splitlines():
        parts = line.strip().split("|", 6)
        if len(parts) != 7:
            continue
        pid_s, title, hwnd_s, left_s, top_s, w_s, h_s = parts
        if not title.startswith("BlueStacks App Player"):
            continue
        try:
            out.append(
                PlayerWindow(
                    pid=int(pid_s),
                    title=title,
                    hwnd=int(hwnd_s),
                    instance_id=title_to_id.get(title),
                    left=int(left_s),
                    top=int(top_s),
                    width=int(w_s),
                    height=int(h_s),
                )
            )
        except ValueError:
            continue

    order = {str(row["id"]): i for i, row in enumerate(list_instances())}

    def _key(p: PlayerWindow) -> tuple:
        if p.instance_id and p.instance_id in order:
            return (0, order[p.instance_id], p.title)
        return (1, 999, p.title)

    out.sort(key=_key)
    return out


def list_player_windows() -> list[dict[str, Any]]:
    return [
        {
            "pid": p.pid,
            "title": p.title,
            "hwnd": p.hwnd,
            "instance_id": p.instance_id,
            "left": p.left,
            "top": p.top,
            "width": p.width,
            "height": p.height,
        }
        for p in _enum_hd_players()
    ]


def _even(n: int) -> int:
    """Even pixel size (gdigrab / x264 friendly)."""
    n = int(n)
    return n if n % 2 == 0 else n - 1


def _fit_16x9(x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
    """Largest 16:9 rect centered in the cell (covers display without portrait fight)."""
    w, h = max(320, _even(w)), max(180, _even(h))
    if w / h > ASPECT:
        # cell wider than 16:9 — letterbox horizontally
        nw = _even(int(h * ASPECT))
        nh = _even(h)
        return (x + (w - nw) // 2, y, nw, nh)
    # cell taller / equal — letterbox vertically
    nw = _even(w)
    nh = _even(int(w / ASPECT))
    return (x, y + (h - nh) // 2, nw, nh)


def _tile_rects(area: WorkArea, n: int, *, mode: str) -> list[tuple[int, int, int, int]]:
    """Return n (x, y, w, h) window rects covering the work area (16:9 fitted)."""
    if n <= 0:
        return []
    cells: list[tuple[int, int, int, int]] = []
    if mode == "fill" or n == 1:
        cells = [(area.left, area.top, area.width, area.height)]
    elif mode == "split" or (mode == "auto" and n == 2):
        if area.width >= area.height:
            w = area.width // 2
            cells = [
                (area.left, area.top, w, area.height),
                (area.left + w, area.top, area.width - w, area.height),
            ][:n]
        else:
            h = area.height // 2
            cells = [
                (area.left, area.top, area.width, h),
                (area.left, area.top + h, area.width, area.height - h),
            ][:n]
    else:
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        cell_w = area.width // cols
        cell_h = area.height // rows
        for i in range(n):
            c = i % cols
            r = i // cols
            x = area.left + c * cell_w
            y = area.top + r * cell_h
            w = cell_w if c < cols - 1 else (area.right - x)
            h = cell_h if r < rows - 1 else (area.bottom - y)
            cells.append((x, y, w, h))
    return [_fit_16x9(x, y, w, h) for x, y, w, h in cells]


def _resolve_players(instance_ids: list[str] | None) -> list[PlayerWindow]:
    players = _enum_hd_players()
    if not instance_ids:
        return players
    wanted: list[PlayerWindow] = []
    by_id = {p.instance_id: p for p in players if p.instance_id}
    by_title = {p.title: p for p in players}
    for iid in instance_ids:
        # Accept player 0 / player 1 aliases as well as engine ids.
        try:
            resolved = str(get_instance(iid).get("id") or iid)
        except KeyError:
            resolved = str(iid)
        if resolved in by_id:
            wanted.append(by_id[resolved])
            continue
        if iid in by_id:
            wanted.append(by_id[iid])
            continue
        # Allow raw window title or engine name → lookup registry title
        try:
            inst = get_instance(iid)
            title = str(inst.get("window_title") or "")
            if title in by_title:
                wanted.append(by_title[title])
                continue
        except KeyError:
            pass
        if iid in by_title:
            wanted.append(by_title[iid])
            continue
        raise RuntimeError(f"no HD-Player window for instance {iid!r}; live={[p.title for p in players]}")
    return wanted


def _move(hwnd: int, x: int, y: int, w: int, h: int) -> bool:
    import time

    # Strip maximized / minimized so SetWindowPos can stick on Qt HD-Player.
    user32.ShowWindow(hwnd, SW_RESTORE)
    time.sleep(0.05)
    GWL_STYLE = -16
    WS_MAXIMIZE = 0x01000000
    try:
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        if style & WS_MAXIMIZE:
            user32.SetWindowLongW(hwnd, GWL_STYLE, style & ~WS_MAXIMIZE)
            user32.ShowWindow(hwnd, SW_RESTORE)
    except Exception:
        pass

    def _at_target() -> bool:
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return (
            abs(rect.left - x) <= 12
            and abs(rect.top - y) <= 12
            and abs((rect.right - rect.left) - w) <= 24
            and abs((rect.bottom - rect.top) - h) <= 24
        )

    for attempt in range(5):
        user32.SetWindowPos(
            hwnd,
            HWND_TOP,
            int(x),
            int(y),
            int(w),
            int(h),
            SWP_SHOWWINDOW,
        )
        # MoveWindow is sometimes honored when SetWindowPos is not (Qt).
        try:
            user32.MoveWindow(hwnd, int(x), int(y), int(w), int(h), True)
        except Exception:
            pass
        time.sleep(0.12 + attempt * 0.05)
        if _at_target():
            return True
    return False


def _windows_overlap(a: dict[str, Any], b: dict[str, Any], *, min_overlap_px: int = 80) -> bool:
    """True if two placed/live window rects overlap enough to steal clicks."""
    ax1, ay1 = int(a.get("left") or a.get("x") or 0), int(a.get("top") or a.get("y") or 0)
    aw, ah = int(a.get("width") or a.get("w") or 0), int(a.get("height") or a.get("h") or 0)
    bx1, by1 = int(b.get("left") or b.get("x") or 0), int(b.get("top") or b.get("y") or 0)
    bw, bh = int(b.get("width") or b.get("w") or 0), int(b.get("height") or b.get("h") or 0)
    ax2, ay2, bx2, by2 = ax1 + aw, ay1 + ah, bx1 + bw, by1 + bh
    ox = max(0, min(ax2, bx2) - max(ax1, bx1))
    oy = max(0, min(ay2, by2) - max(ay1, by1))
    return (ox * oy) >= (min_overlap_px * min_overlap_px)


def _patch_gl_win(engine: str, x: int, y: int, h: int) -> None:
    """Persist geometry into bluestacks.conf so a relaunch opens on-tile."""
    from .config import DEFAULT_BLUESTACKS_CONF

    path = DEFAULT_BLUESTACKS_CONF
    text = path.read_text(encoding="utf-8", errors="replace")
    replacements = {
        f"bst.instance.{engine}.gl_win_x": str(int(x)),
        f"bst.instance.{engine}.gl_win_y": str(int(y)),
        f"bst.instance.{engine}.gl_win_height": str(int(h)),
    }
    lines = []
    seen: set[str] = set()
    for line in text.splitlines(keepends=True):
        raw = line.strip()
        if "=" in raw and not raw.startswith("#"):
            key, _, _val = raw.partition("=")
            key = key.strip()
            if key in replacements:
                nl = "\n" if line.endswith("\n") else ""
                lines.append(f'{key}="{replacements[key]}"{nl}')
                seen.add(key)
                continue
        lines.append(line)
    for key, val in replacements.items():
        if key not in seen:
            lines.append(f'{key}="{val}"\n')
    path.write_text("".join(lines), encoding="utf-8")


def _relaunch_at(instance_id: str, x: int, y: int, w: int, h: int) -> dict[str, Any]:
    """Stop → patch conf → launch. Qt BlueStacks often ignores live MoveWindow."""
    import time

    from .instances import get_instance, launch_bluestacks, stop_bluestacks, wait_for_adb

    inst = get_instance(instance_id)
    engine = str(inst.get("engine") or instance_id)
    stop = stop_bluestacks(instance_id, wait_sec=60)
    _patch_gl_win(engine, x, y, h)
    launch = launch_bluestacks(inst, launch_app=True)
    # Wait for window to appear, then nudge once more
    placed = False
    for _ in range(40):
        time.sleep(1.0)
        live = [p for p in _enum_hd_players() if p.instance_id == instance_id]
        if not live:
            continue
        placed = _move(live[0].hwnd, x, y, w, h)
        if placed:
            break
    try:
        wait_for_adb(inst, seconds=30)
    except Exception:  # noqa: BLE001
        pass
    return {
        "instance_id": instance_id,
        "stop_ok": bool(stop.get("ok")),
        "launch": launch,
        "moved": placed,
        "x": x,
        "y": y,
        "w": w,
        "h": h,
    }


def layout_windows(
    *,
    mode: str = "auto",
    instance_ids: list[str] | None = None,
    focus: str | None = None,
    relaunch_stuck: bool = False,
) -> dict[str, Any]:
    """Tile running BlueStacks windows over the primary work area.

    Modes:
      auto  — 1→fill, 2→split, 3+→grid
      fill  — one instance covers the display (16:9 fitted)
      split — two side-by-side
      grid  — equal cells

    Some Qt HD-Player windows ignore live MoveWindow. Pass relaunch_stuck=True
    to stop/patch bluestacks.conf/launch those so they open on-tile.
    """
    mode = (mode or "auto").lower().strip()
    if mode not in {"auto", "fill", "split", "grid"}:
        raise ValueError(f"bad mode {mode!r}; use auto|fill|split|grid")

    area = work_area()
    players = _resolve_players(instance_ids)
    if not players:
        return {
            "ok": False,
            "error": "no_hd_player_windows",
            "work_area": area.__dict__,
            "placed": [],
        }

    effective = mode
    if mode == "auto":
        n = len(players)
        effective = "fill" if n == 1 else ("split" if n == 2 else "grid")

    if effective == "fill" and len(players) > 1 and not focus:
        effective = "grid"

    if focus:
        focused = [p for p in players if p.instance_id == focus or p.title == focus]
        others = [p for p in players if p not in focused]
        if focused and effective == "fill":
            players = focused[:1]
        elif focused:
            players = focused + others

    tiles = _tile_rects(area, len(players), mode=effective)
    placed: list[dict[str, Any]] = []
    stuck: list[dict[str, Any]] = []
    relaunched: list[dict[str, Any]] = []
    for player, (x, y, w, h) in zip(players, tiles):
        ok_move = _move(player.hwnd, x, y, w, h)
        # Always stamp conf so the next launch opens on-tile even if live move fails.
        if player.instance_id:
            try:
                engine = str(get_instance(player.instance_id).get("engine") or player.instance_id)
                _patch_gl_win(engine, x, y, h)
            except Exception:
                pass
        row = {
            "instance_id": player.instance_id,
            "title": player.title,
            "pid": player.pid,
            "hwnd": player.hwnd,
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "moved": ok_move,
        }
        placed.append(row)
        if not ok_move:
            stuck.append(row)
            if relaunch_stuck and player.instance_id:
                relaunched.append(_relaunch_at(player.instance_id, x, y, w, h))
        if focus and (player.instance_id == focus or player.title == focus):
            user32.SetForegroundWindow(player.hwnd)

    # Detect remaining overlap from live geometry (move may lie / snap back).
    live = {p.instance_id: p for p in _enum_hd_players() if p.instance_id}
    overlapping: list[str] = []
    ids = [p.get("instance_id") for p in placed if p.get("instance_id")]
    for i, a_id in enumerate(ids):
        pa = live.get(a_id)
        if not pa:
            continue
        a_rect = {
            "left": pa.left,
            "top": pa.top,
            "width": pa.width,
            "height": pa.height,
        }
        for b_id in ids[i + 1 :]:
            pb = live.get(b_id)
            if not pb:
                continue
            b_rect = {
                "left": pb.left,
                "top": pb.top,
                "width": pb.width,
                "height": pb.height,
            }
            if _windows_overlap(a_rect, b_rect):
                overlapping.extend([a_id, b_id])
    overlapping = sorted(set(overlapping))

    ok = (not stuck and not overlapping) or (
        relaunch_stuck and bool(relaunched) and all(r.get("moved") for r in relaunched)
    )
    return {
        "ok": ok,
        "mode": mode,
        "effective_mode": effective,
        "work_area": {
            "left": area.left,
            "top": area.top,
            "right": area.right,
            "bottom": area.bottom,
            "width": area.width,
            "height": area.height,
        },
        "placed": placed,
        "stuck": stuck,
        "overlapping": overlapping,
        "relaunched": relaunched,
        "hint": (
            None
            if ok
            else "Qt HD-Player ignored MoveWindow — re-run with --relaunch-stuck "
            "(stop → patch gl_win_* → launch) or drag the BlueStacks top chrome."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="BlueStacks HD-Player window layout")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="List HD-Player windows + rects")
    lay = sub.add_parser("layout", help="Tile windows over the primary work area")
    lay.add_argument(
        "--mode",
        default="auto",
        choices=("auto", "fill", "split", "grid"),
        help="auto=1 fill / 2 split / 3+ grid",
    )
    lay.add_argument(
        "--instances",
        nargs="*",
        default=None,
        help="Instance ids (default: all running HD-Player titles we know)",
    )
    lay.add_argument(
        "--focus",
        default=None,
        help="Bring this instance to front (and fill-only target when --mode fill)",
    )
    lay.add_argument(
        "--relaunch-stuck",
        action="store_true",
        help="If Qt ignores MoveWindow: stop, patch bluestacks.conf gl_win_*, relaunch",
    )
    args = p.parse_args(argv)
    if args.cmd == "list":
        area = work_area()
        print(
            json.dumps(
                {
                    "work_area": area.__dict__,
                    "windows": list_player_windows(),
                },
                indent=2,
            )
        )
        return 0
    if args.cmd == "layout":
        report = layout_windows(
            mode=args.mode,
            instance_ids=args.instances or None,
            focus=args.focus,
            relaunch_stuck=bool(args.relaunch_stuck),
        )
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
