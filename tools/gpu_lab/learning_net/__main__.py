"""Run learning-net probes. Each probe commits before the next one starts."""

from __future__ import annotations

import sys

from tools.gpu_lab.learning_net.log import fail_probe

ORDER = ("ranking", "repeat_map", "failure_tags", "boundaries", "joint_rule")


def _run_one(name: str):
    if name == "ranking":
        from tools.gpu_lab.learning_net.ranking import QUESTION, run

        module = __import__("tools.gpu_lab.learning_net.ranking", fromlist=["MODULE"]).MODULE
    elif name == "repeat_map":
        from tools.gpu_lab.learning_net.repeat_map import QUESTION, run

        module = __import__("tools.gpu_lab.learning_net.repeat_map", fromlist=["MODULE"]).MODULE
    elif name == "failure_tags":
        from tools.gpu_lab.learning_net.tags import QUESTION, run

        module = __import__("tools.gpu_lab.learning_net.tags", fromlist=["MODULE"]).MODULE
    elif name == "boundaries":
        from tools.gpu_lab.learning_net.boundaries import QUESTION, run

        module = __import__("tools.gpu_lab.learning_net.boundaries", fromlist=["MODULE"]).MODULE
    elif name == "joint_rule":
        from tools.gpu_lab.learning_net.joint_rule import QUESTION, run

        module = __import__("tools.gpu_lab.learning_net.joint_rule", fromlist=["MODULE"]).MODULE
    elif name == "wave0_close":
        from tools.gpu_lab.learning_net.close import QUESTION, run

        module = __import__("tools.gpu_lab.learning_net.close", fromlist=["MODULE"]).MODULE
    elif name == "dasheng_ranking":
        from tools.gpu_lab.learning_net.dasheng_rank import QUESTION, run

        module = __import__("tools.gpu_lab.learning_net.dasheng_rank", fromlist=["MODULE"]).MODULE
    elif name == "dasheng_12b_ranking":
        from tools.gpu_lab.learning_net.dasheng_rank import LARGE_QUESTION as QUESTION
        from tools.gpu_lab.learning_net.dasheng_rank import run_12b as run

        module = __import__("tools.gpu_lab.learning_net.dasheng_rank", fromlist=["MODULE"]).MODULE
    elif name == "dasheng_scale_close":
        from tools.gpu_lab.learning_net.dasheng_close import QUESTION, run

        module = __import__("tools.gpu_lab.learning_net.dasheng_close", fromlist=["MODULE"]).MODULE
    elif name == "game_sounds":
        from tools.gpu_lab.learning_net.game_sounds import QUESTION, run

        module = __import__("tools.gpu_lab.learning_net.game_sounds", fromlist=["MODULE"]).MODULE
    elif name == "speech_rank":
        from tools.gpu_lab.learning_net.speech_rank import QUESTION, run

        module = __import__("tools.gpu_lab.learning_net.speech_rank", fromlist=["MODULE"]).MODULE
    elif name == "speech_rank_close":
        from tools.gpu_lab.learning_net.speech_close import QUESTION, run

        module = __import__("tools.gpu_lab.learning_net.speech_close", fromlist=["MODULE"]).MODULE
    elif name == "program_names":
        from tools.gpu_lab.learning_net.program_names import QUESTION, run

        module = __import__("tools.gpu_lab.learning_net.program_names", fromlist=["MODULE"]).MODULE
    elif name == "program_spread":
        from tools.gpu_lab.learning_net.program_spread import QUESTION, run

        module = __import__("tools.gpu_lab.learning_net.program_spread", fromlist=["MODULE"]).MODULE
    elif name == "joint_remainder":
        from tools.gpu_lab.learning_net.joint_remainder import QUESTION, run

        module = __import__("tools.gpu_lab.learning_net.joint_remainder", fromlist=["MODULE"]).MODULE
    elif name == "remainder_place":
        from tools.gpu_lab.learning_net.remainder_place import QUESTION, run

        module = __import__("tools.gpu_lab.learning_net.remainder_place", fromlist=["MODULE"]).MODULE
    elif name == "gold_shape":
        from tools.gpu_lab.learning_net.gold_shape import QUESTION, run

        module = __import__("tools.gpu_lab.learning_net.gold_shape", fromlist=["MODULE"]).MODULE
    elif name == "slot_align":
        from tools.gpu_lab.learning_net.slot_align import QUESTION, run

        module = __import__("tools.gpu_lab.learning_net.slot_align", fromlist=["MODULE"]).MODULE
    elif name == "slot_place":
        from tools.gpu_lab.learning_net.slot_place import QUESTION, run

        module = __import__("tools.gpu_lab.learning_net.slot_place", fromlist=["MODULE"]).MODULE
    else:
        raise SystemExit(
            f"unknown probe {name}. Use {', '.join(ORDER)}, wave0_close, dasheng_ranking, dasheng_12b_ranking, dasheng_scale_close, game_sounds, speech_rank, speech_rank_close, program_names, program_spread, joint_remainder, remainder_place, gold_shape, slot_align, slot_place, or all."
        )
    return QUESTION, module, run


def main(argv: list[str] | None = None) -> int:
    names = (argv if argv is not None else sys.argv[1:]) or ["all"]
    selected = list(ORDER) if names == ["all"] else names
    for name in selected:
        question, module, run = _run_one(name)
        folder_holder: dict[str, object] = {}
        try:
            run()
        except Exception as exc:
            from tools.gpu_lab.learning_net.log import NET_ROOT

            started = sorted((NET_ROOT / "probes").glob(f"*_{name}")) if (NET_ROOT / "probes").exists() else []
            if started:
                fail_probe(started[-1], name, question, {}, exc)
            raise
        del folder_holder, module
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
