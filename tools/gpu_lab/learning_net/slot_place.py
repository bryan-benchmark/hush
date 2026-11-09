"""Put the already-logged feed disagreements on the recording clock.

The match window stays the one in the slot-align receipt. Unmarked long
slots are the feed events with no gold start within 180 seconds. A gold
start is after the game when its wall time is more than 180 seconds past
the feed's end of game. This probe does not edit the gold, choose a cutoff,
or mute, so it has no accuracy percent.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

from experiments.ledger import sha256_text
from tools.gpu_lab.ladder import pairs
from tools.gpu_lab.learning_net.data import BRIDGE, bridge_masks
from tools.gpu_lab.learning_net.log import finish_probe, open_probe
from tools.gpu_lab.learning_net.slot_align import MATCH_S, _load_chunks, _parse
from tools.gpu_lab.prepare import DATA_ROOT

MODULE = Path(__file__)
PROBE_ID = "slot_place"
QUESTION = "Where do unmarked feed slots sit on the recording, and which gold starts fall after the feed's end of game?"
ALIGN_FOLDER = "20261023T124044Z_slot_align"
ALIGN_SHA256 = "9f4d1ba8ccb1063e256aaf581d5d412e3633313861bbb405705019683125082a"
GAME_OVER_SPREAD_S = 2.0


def _cited(root: Path) -> dict:
    path = root / "learning_net" / "probes" / ALIGN_FOLDER / "result.json"
    text = path.read_text(encoding="utf-8")
    digest = sha256_text(text)
    if digest != ALIGN_SHA256:
        raise RuntimeError(f"{ALIGN_FOLDER} hash {digest} does not match {ALIGN_SHA256}")
    return json.loads(text)


def elapsed_at(chunks: list[dict], wall: datetime) -> dict:
    """Invert the chunk wall clock. A hole between chunks is not audio."""
    ordered = sorted(chunks, key=lambda row: float(row["start_elapsed_seconds"]))
    slack = timedelta(seconds=0.5)
    for index, chunk in enumerate(ordered):
        start_wall = _parse(chunk["started_at"])
        end_wall = _parse(chunk["ended_at"])
        if start_wall - slack <= wall <= end_wall + slack:
            elapsed = float(chunk["start_elapsed_seconds"]) + (wall - start_wall).total_seconds()
            return {"clock": "in_audio", "elapsed_s": round(elapsed, 3)}
        if index + 1 < len(ordered):
            next_wall = _parse(ordered[index + 1]["started_at"])
            if end_wall < wall < next_wall:
                return {"clock": "in_gap", "elapsed_s": None, "gap_after_elapsed_s": round(float(chunk["end_elapsed_seconds"]), 3)}
    return {"clock": "outside", "elapsed_s": None}


def _contains(elapsed_s: float, spans: list[tuple[float, float]]) -> bool:
    return any(start <= elapsed_s < end for start, end in spans)


def recover_game_over(breaks: list[dict]) -> dict | None:
    implied = []
    for row in breaks:
        if row.get("feed_kind") != "End of Game" or row.get("delta_s") is None:
            continue
        implied.append(_parse(row["wall"]) + timedelta(seconds=float(row["delta_s"])))
    if not implied:
        return None
    stamps = sorted(item.timestamp() for item in implied)
    spread = stamps[-1] - stamps[0]
    center = datetime.fromtimestamp(median(stamps), tz=implied[0].tzinfo)
    return {"wall": center, "n": len(implied), "spread_s": round(spread, 3), "usable": spread <= GAME_OVER_SPREAD_S}


def end_relation(seconds_after: float) -> str:
    if seconds_after > MATCH_S:
        return "after_game"
    if seconds_after >= 0:
        return "at_game_over"
    return "during_game"


def _place_session(row: dict, chunks: list[dict], programs: list[tuple[float, float]], commercials: list[tuple[float, float]]) -> dict:
    if row.get("feed_status") != "matched":
        return {
            "session": row["session"],
            "role": row["role"],
            "feed_status": row.get("feed_status"),
            "reason": row.get("reason"),
            "event_name": row.get("event_name"),
        }
    breaks = row["breaks"]
    if len(breaks) != len(commercials):
        raise RuntimeError(f"{row['session']} has {len(breaks)} aligned breaks and {len(commercials)} gold commercials")
    last_commercial_end = None if not commercials else max(end for _start, end in commercials)
    placed_slots = []
    for slot in row.get("unmarked_slots", []):
        clock = elapsed_at(chunks, _parse(slot["wall"]))
        elapsed = clock["elapsed_s"]
        if elapsed is None:
            where = clock["clock"]
        elif _contains(elapsed, commercials):
            where = "in_commercial"
        elif _contains(elapsed, programs):
            where = "in_program"
        else:
            where = "outside_spans"
        placed_slots.append(
            {
                "shape": slot["shape"],
                "kind": slot["kind"],
                "period": slot["period"],
                "clock": slot["clock"],
                "wall": slot["wall"],
                "elapsed_s": elapsed,
                "where": where,
                "seconds_after_last_commercial": None if elapsed is None or last_commercial_end is None else round(elapsed - last_commercial_end, 3),
            }
        )
    game_over = recover_game_over(breaks)
    after = []
    at_end = []
    if game_over is not None and game_over["usable"]:
        for brk in breaks:
            gold_wall = _parse(brk["wall"])
            seconds_after = (gold_wall - game_over["wall"]).total_seconds()
            relation = end_relation(seconds_after)
            item = {"start_s": brk["start_s"], "seconds_after_game_over": round(seconds_after, 3), "relation": relation}
            if relation == "after_game":
                after.append(item)
            elif relation == "at_game_over":
                at_end.append(item)
    in_program_after = [slot for slot in placed_slots if slot["where"] == "in_program" and slot["seconds_after_last_commercial"] is not None and slot["seconds_after_last_commercial"] > 0]
    return {
        "session": row["session"],
        "role": row["role"],
        "event_name": row.get("event_name"),
        "feed_status": "matched",
        "last_commercial_end_s": None if last_commercial_end is None else round(last_commercial_end, 3),
        "unmarked_n": len(placed_slots),
        "unmarked_in_program_after_last_commercial_n": len(in_program_after),
        "unmarked_slots": placed_slots,
        "game_over": None
        if game_over is None
        else {
            "n": game_over["n"],
            "spread_s": game_over["spread_s"],
            "usable": game_over["usable"],
            "elapsed_s": None if not game_over["usable"] else elapsed_at(chunks, game_over["wall"])["elapsed_s"],
        },
        "gold_at_game_over_n": len(at_end),
        "gold_after_game_over_n": len(after),
        "gold_after_game_over": after,
    }


def run(root: Path = DATA_ROOT) -> dict:
    parameters = {
        "align_folder": ALIGN_FOLDER,
        "align_result_sha256": ALIGN_SHA256,
        "match_s": MATCH_S,
        "game_over_spread_s": GAME_OVER_SPREAD_S,
        "october_may_choose_cutoff": False,
        "gold_edited": False,
        "live_mute_changed": False,
        "accuracy_percent": None,
        "accuracy_reason": "This probe does not mute. A run that hides the game has no accuracy.",
    }
    folder = open_probe(PROBE_ID, QUESTION, parameters, MODULE)
    cited = _cited(root)
    masks = bridge_masks()
    by_session = {row["session"]: row for row in cited["rows"]}
    rows = []
    for session in BRIDGE:
        chunks, _gaps = _load_chunks(session)
        mask = masks[session]
        rows.append(
            _place_session(
                by_session[session],
                chunks,
                pairs(mask, "verified_program"),
                pairs(mask, "verified_commercial"),
            )
        )
        summary = rows[-1]
        print(
            f"  {session} unmarked_after_last {summary.get('unmarked_in_program_after_last_commercial_n')} after_game {summary.get('gold_after_game_over_n')}",
            flush=True,
        )
    result = {
        "probe_id": PROBE_ID,
        "rows": rows,
        "gold_edited": False,
        "october_may_choose_cutoff": False,
        "live_mute_changed": False,
        "accuracy_percent": None,
        "align_result_sha256": ALIGN_SHA256,
    }
    finish_probe(folder, PROBE_ID, QUESTION, parameters, result, MODULE)
    return result
