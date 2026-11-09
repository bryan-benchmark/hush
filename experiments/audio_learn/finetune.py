"""Partial fine-tune of the frame_mn10 tail on past-only windows from the training games."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from experiments.audio_learn.encoder import DATA_ROOT, last_frame, load_encoder, trainable_tail
from experiments.audio_learn.head import CausalHead
from experiments.audio_learn.splits import (
    CALIBRATE,
    CONTEXT_S,
    EVAL,
    HIDDEN,
    HOP_S,
    SEED,
    SR,
    TRAIN,
    WINDOW_S,
    assert_split,
)
from experiments.audio_learn.windows import pack_past_batch
from experiments.nfl75.inventory import coverage_by_session
from tools.gpu_lab.audio_load import load_coverage
from tools.gpu_lab.decisions import decision_times, label_action
from tools.gpu_lab.eligibility import build_masks
from tools.gpu_lab.splits import HOLDOUTS

STEPS_PER_GAME = 160
SEQUENCE = 4
ENCODER_LR = 3e-5
HEAD_LR = 1e-3


def _labeled_ends(times: list[float], labels: np.ndarray) -> tuple[list[int], list[int]]:
    commercial = []
    program = []
    for index in range(SEQUENCE - 1, len(times)):
        gaps = [times[index - step] - times[index - step - 1] for step in range(SEQUENCE - 1)]
        if any(abs(gap - HOP_S) > 1e-3 for gap in gaps):
            continue
        label = int(labels[index])
        if label == 1:
            commercial.append(index)
        elif label == 0:
            program.append(index)
    return commercial, program


def finetune(out: Path = DATA_ROOT / "checkpoints" / "finetuned_encoder.pt") -> dict:
    assert_split()
    if any(session in EVAL or session in CALIBRATE or session in HOLDOUTS for session in TRAIN):
        raise RuntimeError("fine-tuning was handed a calibration, Prime, or sealed game")
    if not torch.cuda.is_available():
        raise RuntimeError("fine-tuning needs the CUDA device")
    device = torch.device("cuda")
    model = load_encoder(device, None)
    tail = trainable_tail(model)
    probe = torch.zeros(1, int(CONTEXT_S * SR), device=device)
    with torch.no_grad():
        embed_dim = int(last_frame(model, probe).shape[-1])
    head = CausalHead(embed_dim, HIDDEN).to(device)
    head.sequence = SEQUENCE
    optimizer = torch.optim.AdamW(
        [
            {"params": tail, "lr": ENCODER_LR},
            {"params": head.parameters(), "lr": HEAD_LR},
        ],
        weight_decay=1e-4,
    )
    rng = np.random.default_rng(SEED)
    coverage = coverage_by_session()
    masks = {row["session"]: row for row in build_masks(list(TRAIN))}
    steps = 0
    losses: list[float] = []
    # BN and mel stay on the published eval path. Tail weights still receive gradients.
    model.eval()
    head.train()
    for session in TRAIN:
        span = coverage[session]
        times = decision_times(span[0], span[1], WINDOW_S, HOP_S)
        labels = np.asarray([label_action(masks[session], t, HOP_S) for t in times], dtype=np.int8)
        commercial, program = _labeled_ends(times, labels)
        if not commercial or not program:
            print(f"finetune skip {session}: a class is absent from the labeled hops", flush=True)
            continue
        print(f"finetune load {session}", flush=True)
        audio = load_coverage(session, span[0], span[1])
        for _step in range(STEPS_PER_GAME):
            take = 4
            ends = [int(rng.choice(commercial)) for _ in range(take // 2)]
            ends += [int(rng.choice(program)) for _ in range(take // 2)]
            chosen: list[float] = []
            target: list[int] = []
            for end in ends:
                for offset in range(SEQUENCE - 1, -1, -1):
                    chosen.append(times[end - offset])
                    target.append(int(labels[end - offset]))
            waves = pack_past_batch(audio, span[0], chosen, WINDOW_S, CONTEXT_S, SR)
            tensor = torch.from_numpy(np.ascontiguousarray(waves)).to(device)
            embedding = last_frame(model, tensor).view(take, SEQUENCE, embed_dim)
            logits = head(embedding)
            goal = torch.tensor(target, device=device, dtype=torch.float32).view(take, SEQUENCE)
            valid = goal >= 0
            if int(valid.sum()) == 0:
                continue
            loss = F.binary_cross_entropy_with_logits(logits[valid], goal[valid])
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(tail, 1.0)
            optimizer.step()
            steps += 1
            losses.append(float(loss.detach()))
        del audio
        torch.cuda.empty_cache()
        recent = losses[-STEPS_PER_GAME:]
        print(f"  {session} mean loss {float(np.mean(recent)):.4f}", flush=True)
    if steps == 0:
        raise RuntimeError("fine-tuning saw no labeled steps")
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out)
    return {
        "steps": steps,
        "steps_per_game": STEPS_PER_GAME,
        "sequence": SEQUENCE,
        "encoder_lr": ENCODER_LR,
        "tail_parameters": len(tail),
        "loss_first": losses[0] if losses else None,
        "loss_last": losses[-1] if losses else None,
        "checkpoint": str(out),
    }
