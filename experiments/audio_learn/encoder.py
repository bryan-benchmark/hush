"""PretrainedSED frame_mn10, loaded as a past-only frame encoder."""

from __future__ import annotations

import sys
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from experiments.audio_learn.splits import CHECKPOINT_NAME, CHECKPOINT_URL, MODEL_NAME
from experiments.ledger import sha256_file

REPO = Path(__file__).resolve().parents[2]
PRETRAINED_ROOT = REPO / "third_party" / "PretrainedSED"
DATA_ROOT = Path(r"C:\OHushData\gpu_lab\audio_learn")
WEIGHTS = DATA_ROOT / "weights" / f"{CHECKPOINT_NAME}.pt"


class _Null:
    def write(self, _text: str) -> int:
        return 0

    def flush(self) -> None:
        return None


def _import_pretrained():
    if not PRETRAINED_ROOT.is_dir():
        raise RuntimeError(f"PretrainedSED is not at {PRETRAINED_ROOT}")
    root = str(PRETRAINED_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from models.frame_mn.Frame_MN_wrapper import FrameMNWrapper
    from models.frame_mn.utils import NAME_TO_WIDTH
    from models.prediction_wrapper import PredictionsWrapper

    return FrameMNWrapper, NAME_TO_WIDTH, PredictionsWrapper


def _install_eval_mel_cache(mel: nn.Module) -> None:
    """Keep the published eval mel math and build the filterbank once."""
    import torchaudio

    cache: dict = {}

    def forward(x: torch.Tensor) -> torch.Tensor:
        if mel.training:
            raise RuntimeError("the cached mel path is eval-only")
        if mel.preamp:
            x = nn.functional.conv1d(x.unsqueeze(1), mel.preemphasis_coefficient)
        x = x.squeeze(1)
        mels = []
        for n_fft, win_length in zip(mel.n_fft, mel.win_length):
            spec = torch.stft(
                x,
                n_fft,
                hop_length=mel.hopsize,
                win_length=win_length,
                center=mel.padding == "center",
                normalized=False,
                window=getattr(mel, f"window_{win_length}"),
                return_complex=True,
            )
            power = spec.real.square() + spec.imag.square()
            key = (int(n_fft), str(power.device))
            basis = cache.get(key)
            if basis is None:
                banks, _ = torchaudio.compliance.kaldi.get_mel_banks(
                    mel.n_mels,
                    n_fft,
                    mel.sr,
                    mel.fmin,
                    mel.fmax,
                    vtln_low=100.0,
                    vtln_high=-500.0,
                    vtln_warp_factor=1.0,
                )
                basis = nn.functional.pad(banks, (0, 1)).to(device=power.device, dtype=torch.float32)
                cache[key] = basis
            filtered = torch.matmul(basis, power.float())
            mels.append(torch.log(torch.clamp(filtered, min=1e-7)))
        stacked = torch.stack(mels, dim=1)
        if mel.fast_norm:
            stacked = (stacked + 4.5) / 5.0
        return stacked

    mel.forward = forward


def download_checkpoint(path: Path = WEIGHTS) -> Path:
    if path.is_file() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.hub.download_url_to_file(CHECKPOINT_URL, str(path))
    return path


def load_encoder(device: torch.device, weights: Path | None = None) -> nn.Module:
    """AudioSet-strong frame_mn10. The AudioSet head is left off so frames are returned."""
    FrameMNWrapper, name_to_width, PredictionsWrapper = _import_pretrained()
    import models.prediction_wrapper as prediction_wrapper

    checkpoint = download_checkpoint()
    prediction_wrapper.RESOURCES_FOLDER = str(checkpoint.parent)
    width = name_to_width(MODEL_NAME)
    with redirect_stdout(_Null()):
        frame = FrameMNWrapper(width)
        embed_dim = int(frame.state_dict()["frame_mn.features.16.1.bias"].shape[0])
        model = PredictionsWrapper(
            frame,
            checkpoint=None if weights is not None else CHECKPOINT_NAME,
            embed_dim=embed_dim,
            seq_model_type=None,
            head_type=None,
        )
    if weights is not None:
        state = torch.load(weights, map_location="cpu", weights_only=True)
        model.load_state_dict(state)
    _install_eval_mel_cache(model.model.mel)
    model.to(device)
    model.eval()
    return model


def last_frame(model: nn.Module, waves: torch.Tensor) -> torch.Tensor:
    """Embedding at the final frame. `waves` must already end at the decision."""
    sequence = model(model.mel_forward(waves))
    if sequence.ndim != 3 or sequence.shape[1] < 1:
        raise RuntimeError(f"expected a frame sequence, got {tuple(sequence.shape)}")
    return sequence[:, -1, :]


def embed_numpy(model: nn.Module, device: torch.device, waves: np.ndarray) -> np.ndarray:
    tensor = torch.from_numpy(np.ascontiguousarray(waves)).to(device, non_blocking=True)
    with torch.inference_mode():
        frame = last_frame(model, tensor)
    return frame.float().cpu().numpy()


def trainable_tail(model: nn.Module) -> list[nn.Parameter]:
    """Last MobileNet stages. Batch-norm affine weights stay frozen."""
    chosen = []
    for name, parameter in model.named_parameters():
        parameter.requires_grad = False
        if ".bn" in name or "norm" in name:
            continue
        if any(f"frame_mn.features.{index}." in name for index in (12, 13, 14, 15, 16)):
            parameter.requires_grad = True
            chosen.append(parameter)
    if not chosen:
        raise RuntimeError("the frame_mn tail did not match features 12-16")
    return chosen


def checkpoint_sha(path: Path | None = None) -> str:
    target = download_checkpoint() if path is None else path
    return sha256_file(target)
