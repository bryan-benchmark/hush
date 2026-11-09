"""Write the evaluation report from measured rows. It does not choose a threshold."""

from __future__ import annotations

import json
from pathlib import Path

from experiments.audio_learn.evaluate import REPORT_DIR
from experiments.audio_learn.splits import (
    CALIBRATE,
    CONTEXT_S,
    EVAL,
    HOP_S,
    RESERVED,
    TRAIN,
    WINDOW_S,
)
from experiments.ledger import RECORDINGS, TRUTH_PATH, sha256_file
from experiments.nfl75.inventory import BROADCAST
from tools.gpu_lab.splits import HOLDOUTS


def _pct(value) -> str:
    if value is None:
        return "—"
    return f"{100.0 * float(value):.1f}%"


def _num(value, places: int = 2) -> str:
    if value is None:
        return "—"
    return f"{float(value):.{places}f}"


def _row(name: str, metrics: dict) -> str:
    return (
        f"| {name} | {_pct(metrics.get('commercial_coverage'))} | "
        f"{_num(metrics.get('false_mutes_per_hour'))} | "
        f"{_num(metrics.get('longest_false_mute_s'))} | "
        f"{_pct(metrics.get('recovery'))} | "
        f"{'pass' if metrics.get('assignment_pass') else 'fail'} |"
    )


def _names(sessions) -> list[str]:
    lines = []
    for session in sessions:
        broadcaster, show, day = BROADCAST.get(session, ("", "", ""))
        present = any(RECORDINGS.glob(f"*/{session}/session.json"))
        lines.append(f"| `{session}` | {day} | {broadcaster} | {show} | {'yes' if present else 'missing'} |")
    return lines


def write_report(inventory: dict, metrics: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    frozen = metrics["frozen"]
    tuned = metrics["finetuned"]
    baseline = metrics["baseline"]["aggregate"]
    always = metrics["always_play"]["aggregate"]
    boot_f = metrics["bootstrap"]["frozen_vs_baseline"]
    boot_t = metrics["bootstrap"]["finetuned_vs_baseline"]
    lines = [
        "# OHUSH_AUDIO_LEARNING_001",
        "",
        "Question: can PretrainedSED `frame_mn10`, trained on labeled football audio other than Prime, "
        "distinguish commercials from programming on the two labeled Prime games well enough to operate "
        "the volume better than the locked NBC logistic?",
        "",
        "The live television path was not changed. Sealed sessions were not opened. "
        "The historical logistic lines were not moved.",
        "",
        "## Split",
        "",
        "Every split is a whole game. Prime tapes are absent from the fit and from controller selection. "
        "ESPN selects the controller and is not part of the product claim. These Prime tapes were inspected "
        "by earlier experiments; this model did not train on them, and there is still no sealed Prime exam.",
        "",
        f"Truth ledger sha256 `{sha256_file(TRUTH_PATH)}`.",
        "",
        "Train:",
        "",
        "| Session | Day | Network | Show | Audio |",
        "| --- | --- | --- | --- | --- |",
        *_names(TRAIN),
        "",
        "Calibration (controller only):",
        "",
        "| Session | Day | Network | Show | Audio |",
        "| --- | --- | --- | --- | --- |",
        *_names(CALIBRATE),
        "",
        "Evaluation:",
        "",
        "| Session | Day | Network | Show | Audio |",
        "| --- | --- | --- | --- | --- |",
        *_names(EVAL),
        "",
        "Reserved, not used:",
        "",
        "| Session | Day | Network | Show | Audio |",
        "| --- | --- | --- | --- | --- |",
        *_names(RESERVED),
        "",
        "Sealed, not opened:",
        "",
    ]
    for session in sorted(HOLDOUTS):
        lines.append(f"- `{session}`")
    lines.extend(
        [
            "",
            "## Method",
            "",
            f"Encoder: PretrainedSED `{inventory['model']}`, AudioSet-strong checkpoint "
            f"`{inventory['checkpoint_sha256'][:12]}`.",
            f"Each decision at time t reads audio `[t-{WINDOW_S:.0f}, t)` right-aligned in a "
            f"{CONTEXT_S:.0f}-second buffer. The front of the buffer is silence. "
            f"Decisions land every {HOP_S:.2f}s.",
            "A GRU of 16 consecutive embeddings, hidden size 64, is the classification head. "
            "It is trained on the training games only. The calibration game chooses one setting from "
            "the predeclared hysteresis grid. Prime probabilities are scored after that choice.",
            "Fine-tuning updates MobileNet features 12–16 on the training games, then the same head "
            "procedure is repeated on the new embeddings. Batch-norm stays on the published eval statistics.",
            "Playback is `experiments.nfl75.score.playback_from_decisions`. "
            "The baseline is the published NBC logistic: cover after 10 seconds at or above the locked "
            "start line, return after 3 seconds at or below the locked clear-program line.",
            "",
            "Assignment gate, experimental: commercial coverage ≥ 75%, false-mute episodes < 1 per program hour, "
            "longest false mute < 10s, and every cover returns to the game before the tape ends. "
            "The NFL75 scorer also requires hidden program under 5 seconds per program hour. Both are reported. "
            "A pass here is not a live installation.",
            "",
            "## Are the probabilities separating the classes?",
            "",
            "| Model | ESPN AUROC | Prime AUROC |",
            "| --- | ---: | ---: |",
            f"| Frozen encoder | {_num(frozen['calibration_auroc'], 3)} | {_num(frozen['prime_auroc'], 3)} |",
            f"| Fine-tuned tail | {_num(tuned['calibration_auroc'], 3)} | {_num(tuned['prime_auroc'], 3)} |",
            "",
            "AUROC uses labeled hops only. It is not the volume gate, and it was not used to pick the controller.",
            "",
            "## Controller chosen on ESPN",
            "",
            "| Model | On | Off | On streak | Off streak | ESPN coverage | ESPN false mutes / hour |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            _controller_line("Frozen", frozen["controller"]),
            _controller_line("Fine-tuned", tuned["controller"]),
            "",
            "## Prime games, same playback scorer",
            "",
            "| Run | Ad coverage | False mutes / hour | Longest false mute | Recovery | Assignment gate |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
            _row("Always play", always),
            _row("Locked NBC logistic, 10s persist", baseline),
            _row("Frozen frame_mn10", frozen["aggregate"]),
            _row("Fine-tuned frame_mn10", tuned["aggregate"]),
            "",
        ]
    )
    for label, block in (("Frozen", frozen), ("Fine-tuned", tuned)):
        lines.append(f"### {label}")
        lines.append("")
        for session in EVAL:
            game = block["games"][session]
            lags = game["lags"]
            lines.append(
                f"- `{session}`: coverage {_pct(game['commercial_coverage'])}, "
                f"false mutes/hour {_num(game['false_mutes_per_hour'])}, "
                f"longest false mute {_num(game['longest_false_mute_s'])}s, "
                f"recovery {_pct(game['recovery'])}, "
                f"median start delay {_num(lags['median_start_delay_s'])}s, "
                f"median late return {_num(lags['median_late_return_s'])}s, "
                f"breaks never covered {lags['breaks_never_covered']} of {lags['breaks']}."
            )
        lines.append("")
    lines.extend(
        [
            "## Break bootstrap",
            "",
            "Commercial breaks are the resample unit. Hops inside one break are not independent trials. "
            "The interval is a 95% bootstrap of second-weighted coverage, 2000 resamples.",
            "",
            f"- Frozen minus locked logistic: {_fmt_ci(boot_f.get('coverage_minus_baseline_ci95'))} "
            f"on {boot_f.get('breaks', 0)} breaks. Frozen coverage {_fmt_ci(boot_f.get('coverage_ci95'))}.",
            f"- Fine-tuned minus locked logistic: {_fmt_ci(boot_t.get('coverage_minus_baseline_ci95'))} "
            f"on {boot_t.get('breaks', 0)} breaks. Fine-tuned coverage {_fmt_ci(boot_t.get('coverage_ci95'))}.",
            "",
            "## Plots and failure clips",
            "",
            "Full-game plots overlay P(commercial) on the gold commercial spans. "
            "Orange bands are commercials.",
            "",
        ]
    )
    for path in frozen["plots"] + tuned["plots"]:
        name = Path(path).name
        lines.append(f"- `{name}`")
    lines.extend(["", "Representative mistakes, with two seconds of context on either side:", ""])
    for clip in frozen["clips"] + tuned["clips"]:
        lines.append(
            f"- {clip['kind']} `{clip['session']}` {clip['start_s']:.1f}–{clip['end_s']:.1f}s "
            f"({clip['size_s']:.1f}s) `{clip['path']}`"
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            metrics["recommendation"],
            "",
            "Checkpoints:",
            "",
            f"- Frozen head: `{inventory['frozen_head']}`",
            f"- Fine-tuned encoder: `{inventory['finetuned_encoder']}`",
            f"- Fine-tuned head: `{inventory['finetuned_head']}`",
            "",
            "Labeled hop counts from the frozen extract:",
            "",
            "| Session | Commercial hops | Program hops | Excluded hops |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in inventory["caches"]:
        lines.append(
            f"| `{row['session']}` | {row['commercial_rows']} | {row['program_rows']} | {row['excluded_rows']} |"
        )
    lines.extend(
        [
            "",
            "Head fit loss by epoch, frozen then fine-tuned:",
            "",
            f"- Frozen: {inventory['frozen_train']['loss']}",
            f"- Fine-tuned encoder loss first/last: {inventory['finetune']['loss_first']} / {inventory['finetune']['loss_last']}",
            f"- Fine-tuned head: {inventory['tuned_train']['loss']}",
            "",
        ]
    )
    path = REPORT_DIR / "REPORT.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (REPORT_DIR / "inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    return path


def _controller_line(name: str, chosen: dict) -> str:
    return (
        f"| {name} | {chosen['on']:.2f} | {chosen['off']:.2f} | {chosen['on_streak']} | {chosen['off_streak']} | "
        f"{_pct(chosen.get('commercial_coverage'))} | {_num(chosen.get('false_mutes_per_hour'))} |"
    )


def _fmt_ci(interval) -> str:
    if not interval or len(interval) != 2:
        return "—"
    return f"[{100.0 * interval[0]:.1f}%, {100.0 * interval[1]:.1f}%]"
