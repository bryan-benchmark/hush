"""Two predeclared holds on the frozen NBC AST head.

October 8 is development. The head is fit on the two NBC games only, the same
way SUPERVISED_HELDOUT_001 fit it. October does not move either line.

A cover starts after the logistic score has stayed at or above the published
NBC line for 10 seconds, or for 20 seconds. It returns after the score has
stayed at or below the NBC clear-program ceiling for 3 seconds. Scores between
those two lines hold the current state. Gold is read only after the decisions
exist, by the NFL75 scorer.

The live Machine is not retuned, and nothing here moves a speaker.
"""

from __future__ import annotations

import math

from experiments.measurement.metrics import Span

from experiments.nfl75.score import playback_from_covers

SESSION = "hush_20261008_205100"
PUBLISHED_START_LINE = 12.155325889587404
PERSIST_SECONDS = (10.0, 20.0)
RETURN_PERSIST_S = 3.0
HOLE_S = 2.0
_EPS = 1e-9


def covers_from_scores(
    times: list[float],
    scores: list[float],
    *,
    persist_s: float,
    start_line: float,
    return_line: float,
    return_persist_s: float = RETURN_PERSIST_S,
) -> list[tuple[float, float]]:
    """Cover intervals on the capture clock. A hole does not count as evidence."""
    if len(times) != len(scores):
        raise ValueError("each second needs one score")
    if return_line >= start_line:
        raise ValueError("the return line must sit below the start line")
    state = "play"
    hot = 0.0
    cold = 0.0
    last: float | None = None
    opened: float | None = None
    covers: list[tuple[float, float]] = []
    for moment, score in zip(times, scores):
        moment = float(moment)
        score = float(score)
        if last is None:
            dt = 1.0
        elif moment < last - _EPS:
            raise ValueError("score time moved backwards")
        else:
            dt = moment - last
            if dt > HOLE_S:
                hot = 0.0
                cold = 0.0
                dt = 1.0
        last = moment
        if score >= start_line:
            hot += dt
        else:
            hot = 0.0
        if score <= return_line:
            cold += dt
        else:
            cold = 0.0
        if state == "play" and hot + _EPS >= persist_s:
            state = "cover"
            opened = moment
            cold = 0.0
        elif state == "cover" and cold + _EPS >= return_persist_s:
            state = "play"
            covers.append((float(opened), moment))
            opened = None
            hot = 0.0
    if opened is not None and last is not None:
        covers.append((opened, last + 1.0))
    return covers


def playback(
    coverage: tuple[float, float],
    times: list[float],
    scores: list[float],
    *,
    persist_s: float,
    start_line: float,
    return_line: float,
) -> list[Span]:
    return playback_from_covers(
        coverage,
        covers_from_scores(
            times,
            scores,
            persist_s=persist_s,
            start_line=start_line,
            return_line=return_line,
        ),
    )


def sustained_runs(times: list[float], scores: list[float], line: float) -> list[dict]:
    """Runs of score >= line. Evaluation only. The decision function does not call this."""
    runs: list[dict] = []
    start = None
    count = 0
    previous = None
    for moment, score in zip(times, scores):
        moment = float(moment)
        broken = previous is not None and moment - previous > HOLE_S
        if score >= line and not broken:
            if start is None:
                start = moment
            count += 1
        else:
            if start is not None:
                runs.append({"start_s": start, "end_s": float(previous), "seconds": count})
            start = moment if score >= line else None
            count = 1 if score >= line else 0
        previous = moment
    if start is not None and previous is not None:
        runs.append({"start_s": start, "end_s": float(previous), "seconds": count})
    return runs


def pods_that_never_hold(
    commercials: list[tuple[float, float]],
    times: list[float],
    scores: list[float],
    *,
    line: float,
    persist_s: float,
) -> list[dict]:
    rows = []
    for index, (start, end) in enumerate(commercials, start=1):
        inside_t = []
        inside_s = []
        for moment, score in zip(times, scores):
            if start - _EPS <= float(moment) < end - _EPS:
                inside_t.append(float(moment))
                inside_s.append(float(score))
        longest = 0
        if inside_t:
            longest = max((row["seconds"] for row in sustained_runs(inside_t, inside_s, line)), default=0)
        rows.append(
            {
                "break": index,
                "start_s": start,
                "end_s": end,
                "longest_run_s": longest,
                "never_holds": longest + _EPS < persist_s,
            }
        )
    return rows


FIT = ("hush_20260909_213047", "hush_20260913_210542")
WINDOW_S = 5.0


def _lookback_commercial(moment: float, commercials: list[tuple[float, float]]) -> float:
    start = moment - WINDOW_S
    return sum(max(0.0, min(moment, stop) - max(start, begin)) for begin, stop in commercials)


def _fit_nbc():
    """Same two-game logistic as SUPERVISED_HELDOUT_001. October is not in the fit."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    from tools.gpu_lab.learning_net.data import load_cache
    from tools.gpu_lab.splits import HOLDOUTS

    if any(session in HOLDOUTS for session in FIT):
        raise RuntimeError("the fit list names a sealed holdout")
    vectors = []
    labels = []
    for session in FIT:
        cache = load_cache(session, WINDOW_S)
        keep = cache["label"] >= 0
        vectors.append(cache["emb"][keep])
        labels.append(cache["label"][keep])
    x = np.concatenate(vectors)
    y = np.concatenate(labels)
    head = LogisticRegression(max_iter=2000, class_weight="balanced")
    head.fit(x, y)
    receipt = {
        "sessions": list(FIT),
        "rows": int(len(y)),
        "commercial_rows": int((y == 1).sum()),
        "program_rows": int((y == 0).sum()),
        "train_accuracy": round(float(head.score(x, y)), 4),
    }
    return head, receipt


def _logits(head, session: str):
    import numpy as np

    from tools.gpu_lab.learning_net.data import load_cache
    from tools.gpu_lab.splits import HOLDOUTS

    if session in HOLDOUTS:
        raise RuntimeError(f"refusing sealed holdout {session}")
    cache = load_cache(session, WINDOW_S)
    scores = np.asarray(head.decision_function(cache["emb"]), dtype=np.float64)
    return cache["t"], scores, cache["label"]


def nbc_lines() -> dict:
    """Reproduce the published start line from the two NBC games. October is not read."""
    from tools.gpu_lab.ladder import pairs
    from tools.gpu_lab.learning_net.data import bridge_masks

    masks = bridge_masks()
    head, receipt = _fit_nbc()
    ceiling = None
    for session in FIT:
        times, scores, _labels = _logits(head, session)
        program = pairs(masks[session], "verified_program")
        for moment, score in zip(times, scores):
            end = float(moment) + 1.0
            if any(min(end, stop) - max(float(moment), start) > 1e-9 for start, stop in program):
                ceiling = float(score) if ceiling is None else max(ceiling, float(score))
    if ceiling is None:
        raise RuntimeError("the NBC games have no program-overlapping score")
    start_line = math.nextafter(ceiling, math.inf)
    clear = None
    setter = None
    for session in FIT:
        times, scores, labels = _logits(head, session)
        commercials = pairs(masks[session], "verified_commercial")
        for moment, score, label in zip(times, scores, labels):
            if int(label) != 0:
                continue
            if _lookback_commercial(float(moment), commercials) > 1e-9:
                continue
            if clear is None or float(score) > clear:
                clear = float(score)
                setter = {"session": session, "t": round(float(moment), 3), "score": float(score)}
    if clear is None or setter is None:
        raise RuntimeError("no clear program second on the NBC fit games")
    if not math.isclose(start_line, PUBLISHED_START_LINE, rel_tol=0.0, abs_tol=0.0):
        raise RuntimeError(
            f"reproduced start line {start_line!r} is not the published line {PUBLISHED_START_LINE!r}"
        )
    if not (clear < start_line):
        raise RuntimeError("the clear-program ceiling is not below the start line")
    return {
        "fit": receipt,
        "start_line": start_line,
        "return_line": clear,
        "return_setter": setter,
        "head": head,
    }
