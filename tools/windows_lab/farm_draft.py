"""High-accuracy farm drafts: full-take Whisper + still vision + honest evidence.

Rules:
- Never pretend aid captions are model evidence.
- Empty ASR + black/corrupt still → ask=skip (dead air; not /farm work).
- Empty ASR + no visual text but real picture → needs_human.
- Auto-accept only paid_ad with high confidence AND lexicon support AND non-empty evidence.
"""

from __future__ import annotations

import base64
import json
import re
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .config import data_root
from .coverage_farm import farm_label_dir
from .farm_label_audit import (
    MORNING_REVIEW_BUDGET,
    append_draft_events,
    apply_morning_batch,
    atomic_write_jsonl,
    review_priority,
    write_daily_digest,
)

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_PS_URL = "http://127.0.0.1:11434/api/ps"
OLLAMA_KEEP_ALIVE = "30m"  # keep qwen hot across tapes in a backfill pass
VISION_MODEL = "moondream"
DEFAULT_TEXT_MODEL = "qwen2.5:14b"
# Long edge for VL encode — full farm JPEGs are oversized for lexicon labeling.
VISION_MAX_EDGE = 1024
VISION_JPEG_QUALITY = 85
ASR_PAD_SEC = 1.0  # keep tight — wide pad bleeds prior ads into program windows
MIN_CLIP_ASR_SEC = 16.0
SPORTS_VISUAL = re.compile(
    r"\b("
    r"soccer|football|basketball|baseball|hockey|tennis|scorebug|scoreboard|"
    r"players? on the (field|court)|live game|stadium|referee|goalkeeper|"
    # Common spoken/on-screen sports without the sport name itself:
    r"lakers|celtics|warriors|knicks|nba|nfl|nhl|mlb|nwsl|mls|"
    r"assists?|rebounds?|touchdowns?|yardage|pitcher|home\s*run|"
    r"sports\s+broadcast|on\s+the\s+court|on\s+the\s+field"
    r")\b",
    re.I,
)
TRANSCRIPT_CACHE = "farm_transcript.json"

PROMPT = """You label TV segments for an ad-skip dataset.

Evidence (may be incomplete):
TRANSCRIPT:
<<TEXT>>

VISUAL (from a mid-clip still; may be empty):
<<VISUAL>>

Reply with one JSON object and no other text:
{"bucket":"paid_ad"|"program"|"show_promo"|"program_mention"|"uncertain","kind":"dry_vo"|"studio"|"news"|"sports"|"show_promo"|"in_show_sponsorship"|"unknown","confidence":"high"|"medium"|"low","why":"short reason"}

Rules:
- paid_ad = standalone commercial for a product/store/card/app/insurance.
- program = the show itself (news, sports desk, live game, talk).
- show_promo = promo for another show/network event.
- program_mention = show continues while naming a sponsor.
- uncertain = evidence is too weak (empty transcript AND vague visual, or conflict).
- Prefer paid_ad when visual clearly shows a product end-card / logo ad even if speech is thin.
- Prefer program when scorebug/desk/anchors/live play dominate.
- If you describe a live game, scoreboard, anchors, or sports desk in "why", bucket MUST be program (not uncertain).
- confidence=high only when evidence is clear; otherwise medium/low.
"""

AD_HINT = re.compile(
    r"\b("
    r"percent|apr|financing|limited time|order now|buy now|learn more|"
    r"available at|download the app|terms apply|geico|mcdonald|chili'?s|"
    r"draft\s*kings|fanduel|amex|american express|platinum|insurance|"
    r"credit card|outlander|hump day|mitsubishi|sapphire|paramount\+?"
    r")\b",
    re.I,
)
SHOW_HINT = re.compile(
    r"\b("
    r"touchdown|first down|yard line|quarterback|halftime|sideline|"
    r"breaking news|good evening|welcome back|from the desk|"
    r"final score|play[- ]by[- ]play|scorebug|kickoff|"
    r"first half|second half|third quarter|fourth quarter|mid\s+third|"
    r"step back|three[- ]pointer|free throw|full[- ]court"
    r")\b",
    re.I,
)
VISUAL_AD_HINT = re.compile(
    r"\b("
    r"logo|end[\s-]?card|commercial|advertisement|product shot|offer|"
    r"geico|mitsubishi|chase|sapphire|insurance|car ad|auto ad"
    r")\b",
    re.I,
)
# Streamers / EPG chrome — captions often say this clearly while class wrongly lands on "ad".
# Channel changes during capture leave these stills; keep the lexicon wide (phrasing varies).
GUIDE_CAPTION_HINT = re.compile(
    r"("
    r"tv guide(?:\s+interface)?|guide interface|"
    r"search bar|"
    r"list of channels|channel options(?:\s+listed)?|channels?\s+section|"
    r"channel listing|tv interface with a search|"
    r"under the ['\"]?channels['\"]? section|"
    r"channel menu|favorites.{0,40}(channels?|section)|"
    r"no information\.?|"
    r"\(max sports\)|"
    r"all channels|"
    r"sidebar with categor|"
    r"tv interface from a streaming|"
    r"streaming interface|"
    r"service called ['\"]?streamers|"
    r"text boxes? displayed|"
    r"(?:two|three|several) channels displayed|"
    r"channels displayed,\s*both labeled"
    r")",
    re.I,
)


def vision_caption_is_guide(text: str | None) -> bool:
    """True when the VL caption describes guide/UI chrome (not program, not an ad)."""
    return bool(text and GUIDE_CAPTION_HINT.search(str(text)))


def _trust_gate(root: Path | None = None) -> dict[str, Any]:
    path = farm_label_dir(root) / "trust_gate.json"
    if not path.is_file():
        return {"auto_paid_ad_enabled": False}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"auto_paid_ad_enabled": False}


def _auto_accept(
    draft: dict[str, Any],
    text: str,
    visual: str,
    *,
    stills_agree: bool,
    root: Path | None = None,
) -> bool:
    gate = _trust_gate(root)
    if not gate.get("auto_paid_ad_enabled"):
        return False
    if not stills_agree:
        return False
    if draft.get("bucket") != "paid_ad" or draft.get("confidence") != "high":
        return False
    blob = f"{text}\n{visual}".strip()
    if not blob:
        return False
    if SHOW_HINT.search(blob) and not AD_HINT.search(blob):
        return False
    # Require lexicon in speech OR clear visual ad cue — both sides agreeing stills.
    return bool(AD_HINT.search(text or "") or VISUAL_AD_HINT.search(visual or ""))


def _rescue_program(draft: dict[str, Any], text: str, visual: str) -> dict[str, Any]:
    """If the model hedges but sports cues are clear, prefer program.

    Never rewrite show_promo — that class needs packaging cues, not scorebugs.
    """
    bucket = str(draft.get("bucket") or "")
    if bucket == "show_promo":
        return draft
    if bucket not in {"uncertain", "program_mention"} and not (
        bucket == "program" and str(draft.get("confidence") or "") == "low"
    ):
        # Also lift uncertain-only; leave solid paid_ad alone.
        if bucket != "uncertain":
            return draft
    sports_vis = bool(SPORTS_VISUAL.search(visual or ""))
    sports_speech = bool(SHOW_HINT.search(text or "") or SPORTS_VISUAL.search(text or ""))
    if not (sports_vis or sports_speech):
        return draft
    # Don't override a clear paid-ad lexicon hit with no sports speech.
    if AD_HINT.search(text or "") and not sports_speech and not sports_vis:
        return draft
    if AD_HINT.search(text or "") and not sports_speech and sports_vis:
        # Mixed: keep uncertain rather than force program over a hard sell.
        if AD_HINT.search(text or "") and not SHOW_HINT.search(text or ""):
            return draft
    out = dict(draft)
    out["bucket"] = "program"
    out["kind"] = "sports" if out.get("kind") in {"unknown", "dry_vo", "live_game", "news"} else out.get("kind")
    conf = str(out.get("confidence") or "low")
    out["confidence"] = "medium" if conf == "low" else conf
    tag = "sports visual" if sports_vis else "sports speech"
    out["why"] = (out.get("why") or "")[:120] + f" | rescued: {tag}"
    return out


def _rescue_paid_ad(draft: dict[str, Any], text: str, visual: str) -> dict[str, Any]:
    """Clear ad lexicon + no sports show cues → paid_ad (common-sense lift)."""
    bucket = str(draft.get("bucket") or "")
    if bucket in {"show_promo", "program_mention"}:
        return draft
    if bucket not in {"uncertain", "paid_ad"} and not (
        bucket == "program" and str(draft.get("confidence") or "") == "low"
    ):
        return draft
    ad_speech = bool(AD_HINT.search(text or ""))
    ad_vis = bool(VISUAL_AD_HINT.search(visual or ""))
    if not (ad_speech or ad_vis):
        return draft
    if SHOW_HINT.search(text or "") or SPORTS_VISUAL.search(visual or ""):
        # Live game under a sponsor card — leave for human / program_mention.
        return draft
    out = dict(draft)
    out["bucket"] = "paid_ad"
    out["kind"] = "dry_vo" if out.get("kind") in {"unknown", "sports", "live_game"} else out.get("kind")
    conf = str(out.get("confidence") or "low")
    # Lexicon+visual agreement → medium; speech lexicon alone → medium; else keep.
    out["confidence"] = "high" if ad_speech and ad_vis else ("medium" if conf == "low" else conf)
    tag = "ad lexicon+visual" if ad_speech and ad_vis else ("ad lexicon" if ad_speech else "ad visual")
    out["why"] = (out.get("why") or "")[:120] + f" | rescued: {tag}"
    return out


def detect_av_content_desync(
    *,
    head_text: str,
    visual: str = "",
    tail_text: str = "",
    full_text: str = "",
    still_classes: list[str] | None = None,
    span_s: float,
) -> dict[str, Any] | None:
    """90/10 A/V content skew / mixed clip (not silence).

    Classic Streamers failure: picture already on the ad, loopback audio still on the
    previous segment for ~5–15s. Loud peak → audio_lag probe misses it.

    Triggers (any one):
      1) mid/end visual looks like ad AND early ASR still program
      2) early ASR program AND late ASR ad (or reverse) on a ≥10s clip —
         gold-poisoning mixed window even when start-still text is still “game”
    """
    if span_s < 8.0:
        return None
    head = (head_text or "").strip()
    tail = (tail_text or "").strip()
    full = (full_text or "").strip()
    vis = (visual or "").strip()
    if len(head) < 12 and len(full) < 20:
        return None
    if not tail and full and len(full) > len(head) + 20:
        # Fall back: treat last 45% of characters as tail when caller only has one blob.
        cut = max(len(head), int(len(full) * 0.55))
        tail = full[cut:]
    classes = {str(c) for c in (still_classes or []) if c}
    vis_ad = bool(VISUAL_AD_HINT.search(vis) or AD_HINT.search(vis) or ("ad" in classes))
    vis_prog = bool(
        SPORTS_VISUAL.search(vis) or SHOW_HINT.search(vis) or ("program" in classes)
    )
    head_ad = bool(AD_HINT.search(head))
    head_prog = bool(SHOW_HINT.search(head) or SPORTS_VISUAL.search(head)) and not head_ad
    tail_ad = bool(AD_HINT.search(tail))
    tail_prog = bool(SHOW_HINT.search(tail) or SPORTS_VISUAL.search(tail)) and not tail_ad

    # Picture ahead: ad still + program speech at open of clip.
    if vis_ad and head_prog and not vis_prog:
        return {
            "desync": True,
            "kind": "picture_ad_audio_program",
            "why": "skip_av_desync:picture_ad_early_program_asr",
        }
    # Less common: program still + clear ad speech at open.
    if vis_prog and head_ad and not vis_ad:
        return {
            "desync": True,
            "kind": "picture_program_audio_ad",
            "why": "skip_av_desync:picture_program_early_ad_asr",
        }
    # Mixed ASR arc on a long clip — do not gold-lock as one bucket (Popeyes case).
    if span_s >= 10.0 and head_prog and tail_ad:
        return {
            "desync": True,
            "kind": "asr_program_then_ad",
            "why": "skip_av_desync:early_program_late_ad_asr",
        }
    if span_s >= 10.0 and head_ad and tail_prog:
        return {
            "desync": True,
            "kind": "asr_ad_then_program",
            "why": "skip_av_desync:early_ad_late_program_asr",
        }
    return None


def apply_common_sense(draft: dict[str, Any], text: str, visual: str) -> dict[str, Any]:
    """Deterministic rescues after the model (or when stills disagree but ASR is clear).

    Always fold the model's own ``why`` into the visual blob. VL often writes
    ``bucket=uncertain`` while ``why`` says "basketball…scoreboard" — without
    that, sports rescue never fires (ASR play-by-play may not hit SHOW_HINT).
    """
    why = str(draft.get("why") or "")
    vis_blob = f"{visual or ''}\n{why}".strip()
    out = _rescue_paid_ad(draft, text, vis_blob)
    out = _rescue_program(out, text, vis_blob)
    return out


def _visual_class(text: str) -> str:
    t = text or ""
    # Guide chrome before ad lexicon — "Channels" / search UI must not train as mute.
    if vision_caption_is_guide(t):
        return "other"
    ad = bool(AD_HINT.search(t) or VISUAL_AD_HINT.search(t))
    prog = bool(SPORTS_VISUAL.search(t) or SHOW_HINT.search(t))
    if ad and prog:
        return "mixed"
    if ad:
        return "ad"
    if prog:
        return "program"
    return "other"


def _parse_label_payload(raw_text: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_text or "{}")
    except json.JSONDecodeError:
        payload = {}
    bucket = str(payload.get("bucket") or "uncertain").strip().lower()
    kind = str(payload.get("kind") or "unknown").strip().lower()
    confidence = str(payload.get("confidence") or "low").strip().lower()
    why = str(payload.get("why") or "").strip()[:200]
    if bucket not in {"paid_ad", "program", "show_promo", "program_mention", "uncertain"}:
        bucket = "uncertain"
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    return {"bucket": bucket, "kind": kind, "confidence": confidence, "why": why}


def _ask_ollama_text(model: str, text: str, visual: str) -> dict[str, Any]:
    prompt = (
        PROMPT.replace("<<TEXT>>", (text or "(no speech)").strip()[:1600])
        .replace("<<VISUAL>>", (visual or "(no visual note)").strip()[:800])
    )
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {"temperature": 0, "num_predict": 120},
        }
    ).encode()
    req = Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=180) as resp:
        raw = json.loads(resp.read().decode())
    return _parse_label_payload(raw.get("response") or "{}")


def is_black_or_corrupt_still(image_path: Path | None) -> str | None:
    """Cheap JPEG check: 'black' | 'green_corrupt' | None (usable picture).

    90/10: black+silent windows are dead air — skip labeling, don't flood /farm.
    """
    if image_path is None or not image_path.is_file():
        return "black"
    try:
        from PIL import Image
        import numpy as np

        im = Image.open(image_path).convert("RGB")
        # Downscale for speed
        im = im.resize((64, 36))
        a = np.asarray(im, dtype=np.float32)
        mean = float(a.mean())
        std = float(a.std())
        r, g, b = float(a[:, :, 0].mean()), float(a[:, :, 1].mean()), float(a[:, :, 2].mean())
        if mean < 8 and std < 8:
            return "black"
        if g > r + 25 and g > b + 25 and mean > 40:
            return "green_corrupt"
        return None
    except Exception:  # noqa: BLE001
        return None


def _still_jpeg_b64(image_path: Path, *, max_edge: int = VISION_MAX_EDGE) -> tuple[str, dict[str, Any]]:
    """Encode a downscaled JPEG for VL — same picture, less GPU/IO waste."""
    from io import BytesIO

    from PIL import Image

    im = Image.open(image_path).convert("RGB")
    w, h = im.size
    meta = {"src_w": w, "src_h": h, "max_edge": int(max_edge)}
    edge = max(w, h)
    if edge > max_edge > 0:
        scale = float(max_edge) / float(edge)
        resample = getattr(getattr(Image, "Resampling", Image), "BILINEAR", Image.BILINEAR)
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), resample)
    meta["out_w"], meta["out_h"] = im.size
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=VISION_JPEG_QUALITY, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii"), meta


def describe_still(image_path: Path, *, model: str = VISION_MODEL) -> dict[str, Any]:
    """Short visual description via Ollama vision model.

    Use /api/generate — moondream's chat path often returns empty content on this box.
    qwen2.5vl: one prompt (second prompt doubled worst-case hangs without accuracy gain).
    Images are downscaled to VISION_MAX_EDGE before send.
    """
    if not image_path.is_file():
        return {"ok": False, "error": "missing_still"}
    dead = is_black_or_corrupt_still(image_path)
    if dead == "black":
        return {"ok": False, "error": "black_still", "still": str(image_path)}
    if dead == "green_corrupt":
        return {"ok": False, "error": "green_corrupt_still", "still": str(image_path)}
    try:
        b64, scale_meta = _still_jpeg_b64(image_path)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"still_encode:{exc}", "still": str(image_path)}
    # Keep wording plain — moondream returns empty on “labeling”/instruction-heavy prompts.
    primary = "Describe this TV frame. Name logos, products, scorebugs, anchors, or end-cards if visible."
    secondary = "What is on this TV screen? Mention any brand, logo, scorebug, or person."
    model_l = str(model or "").lower()
    # qwen is reliable enough that a 2nd full generate only burns wall clock.
    if "qwen" in model_l:
        prompts = (primary,)
    else:
        prompts = (primary, secondary)

    def _usable(text: str) -> bool:
        t = (text or "").strip()
        if len(t) < 12:
            return False
        # Reject bare detection boxes like "[0.0, 0.65, 0.99, 0.83]"
        if re.fullmatch(r"\[?\s*[\d\.,\s]+\]?", t):
            return False
        return True

    last_err = "empty_vision"
    try:
        for prompt in prompts:
            body = json.dumps(
                {
                    "model": model,
                    "prompt": prompt,
                    "images": [b64],
                    "stream": False,
                    "keep_alive": OLLAMA_KEEP_ALIVE,
                }
            ).encode()
            req = Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=180) as resp:
                raw = json.loads(resp.read().decode())
            msg = str(raw.get("response") or "").strip()
            if _usable(msg):
                return {
                    "ok": True,
                    "model": model,
                    "visual": msg[:500],
                    "still": str(image_path),
                    "encode": scale_meta,
                }
            last_err = "empty_or_unusable_vision"
        return {
            "ok": False,
            "error": last_err,
            "still": str(image_path),
            "model": model,
            "encode": scale_meta,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "still": str(image_path)}


def describe_clip_stills(session_dir: Path, t0: float, t1: float, *, model: str = VISION_MODEL) -> dict[str, Any]:
    """Describe start/mid/end stills. Disagreeing ad vs program stills → stills_agree=False."""
    times = sorted({round(t0, 1), round(0.5 * (t0 + t1), 1), round(max(t0, t1 - 0.5), 1)})
    parts: list[str] = []
    raw_visuals: list[str] = []
    classes: list[str] = []
    stills: list[str] = []
    errors: list[str] = []
    for t in times:
        path = nearest_still(session_dir, float(t))
        if path is None:
            errors.append(f"no_still@{t}")
            continue
        meta = describe_still(path, model=model)
        if meta.get("ok") and meta.get("visual"):
            vis = str(meta["visual"])
            parts.append(f"t={t:.1f}s: {vis}")
            raw_visuals.append(vis)
            classes.append(_visual_class(vis))
            stills.append(str(path))
        else:
            errors.append(str(meta.get("error") or "vision_fail"))
    if not parts:
        return {"ok": False, "error": ";".join(errors) or "no_visual", "stills": stills, "stills_agree": False}

    meaningful = {c for c in classes if c != "other"}
    disagree = ("ad" in meaningful and "program" in meaningful) or ("mixed" in meaningful)
    # When stills disagree, keep mid-only text so the model isn't fed a blended ad+program soup.
    if disagree and len(raw_visuals) >= 2:
        mid_i = len(raw_visuals) // 2
        visual = f"t=mid: {raw_visuals[mid_i]} | NOTE: start/mid/end stills disagree (possible boundary)"
    else:
        visual = " | ".join(parts)[:900]
    return {
        "ok": True,
        "model": model,
        "visual": visual[:900],
        "stills": stills,
        "stills_agree": not disagree,
        "still_classes": classes,
        "stills_disagree": disagree,
    }


def unload_ollama_model(model: str) -> dict[str, Any]:
    import shutil
    import subprocess

    if shutil.which("ollama") is None:
        try:
            body = json.dumps({"model": model, "keep_alive": 0, "prompt": ""}).encode()
            req = Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=30) as resp:
                resp.read()
            return {"ok": True, "method": "api_keep_alive_0", "model": model}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "model": model}
    try:
        proc = subprocess.run(
            ["ollama", "stop", model],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return {
            "ok": proc.returncode == 0,
            "method": "ollama_stop",
            "model": model,
            "stdout": (proc.stdout or "").strip()[-200:],
            "stderr": (proc.stderr or "").strip()[-200:],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "model": model}


def ollama_loaded_models() -> list[str]:
    try:
        with urlopen(OLLAMA_PS_URL, timeout=3) as resp:
            raw = json.loads(resp.read().decode())
        return [str(m.get("name") or m.get("model") or "") for m in (raw.get("models") or []) if m]
    except Exception:  # noqa: BLE001
        return []


def prepare_vision_gpu(keep_model: str) -> dict[str, Any]:
    """Free VRAM of other VL models so qwen can run alone (common-sense max for one stream)."""
    keep = str(keep_model or "").strip()
    keep_base = keep.split(":", 1)[0].lower()
    unloaded: list[dict[str, Any]] = []
    kept: list[str] = []
    for name in ollama_loaded_models():
        if not name:
            continue
        base = name.split(":", 1)[0].lower()
        if base == keep_base or name == keep:
            kept.append(name)
            continue
        # Only stop other vision / caption models — leave text LLMs alone.
        if any(tok in base for tok in ("moondream", "llava", "minicpm", "vl", "vision", "bakllava")):
            unloaded.append(unload_ollama_model(name))
        else:
            kept.append(name)
    return {"ok": True, "keep": keep, "kept": kept, "unloaded": unloaded}


def _resample_mono_to_16k(audio: Any, rate: int) -> tuple[Any, int]:
    """Whisper expects 16 kHz float32 mono. Capture wav is often 48 kHz."""
    import numpy as np

    if rate == 16000:
        return audio.astype(np.float32, copy=False), 16000
    if rate <= 0 or audio.size == 0:
        return audio.astype(np.float32, copy=False), rate
    duration = audio.size / float(rate)
    new_len = max(1, int(round(duration * 16000)))
    x_old = np.linspace(0.0, 1.0, num=audio.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
    out = np.interp(x_new, x_old, audio.astype(np.float64)).astype(np.float32)
    return out, 16000


def _read_wav_mono16(path: Path, t0: float, t1: float) -> tuple[Any, int]:
    import numpy as np

    with wave.open(str(path), "rb") as wf:
        rate = wf.getframerate()
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        if sw != 2:
            raise RuntimeError(f"expected 16-bit wav, got sampwidth={sw}")
        start = max(0, int(t0 * rate))
        n = max(1, int((t1 - t0) * rate))
        wf.setpos(start)
        raw = wf.readframes(n)
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        audio = audio.reshape(-1, ch).mean(axis=1)
    return _resample_mono_to_16k(audio, rate)


def _wav_duration_sec(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())


def ensure_take_transcript(
    session_dir: Path,
    *,
    whisper_model=None,
    force: bool = False,
) -> dict[str, Any]:
    """Transcribe whole take once (vad off) and cache segments for clip lookup."""
    session_dir = Path(session_dir)
    cache = session_dir / TRANSCRIPT_CACHE
    wav = session_dir / "audio.wav"
    if cache.is_file() and not force:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        # Drop pre-resample hallucination caches (48 kHz fed as 16 kHz).
        if "pcm16k" in str(cached.get("engine") or ""):
            return cached
    if not wav.is_file():
        return {"ok": False, "error": "missing audio.wav", "segments": []}
    if whisper_model is None:
        from faster_whisper import WhisperModel

        whisper_model = WhisperModel("base.en", device="cpu", compute_type="int8", cpu_threads=4)

    # Load PCM ourselves — avoids PyAV metadata_errors incompat on this box.
    duration_s = _wav_duration_sec(wav)
    audio, rate = _read_wav_mono16(wav, 0.0, duration_s)
    # Full take — VAD off so music beds / soft VO in ads are not dropped.
    segments, info = whisper_model.transcribe(
        audio,
        language="en",
        vad_filter=False,
        beam_size=1,
    )
    rows = []
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        rows.append(
            {
                "start": float(seg.start),
                "end": float(seg.end),
                "text": text,
            }
        )
    out = {
        "ok": True,
        "session_dir": str(session_dir),
        "language": getattr(info, "language", "en"),
        "duration_s": duration_s,
        "sample_rate": rate,
        "segments": rows,
        "engine": "faster-whisper base.en int8 vad_filter=false pcm16k",
    }
    cache.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def transcript_for_window(transcript: dict[str, Any], t0: float, t1: float, *, pad: float = ASR_PAD_SEC) -> str:
    a = max(0.0, t0 - pad)
    b = t1 + pad
    bits = []
    for seg in transcript.get("segments") or []:
        if float(seg["end"]) < a or float(seg["start"]) > b:
            continue
        bits.append(str(seg["text"]).strip())
    return " ".join(bits).strip()


def nearest_still(session_dir: Path, t_sec: float) -> Path | None:
    stills = session_dir / "stills"
    if not stills.is_dir():
        return None
    # Prefer exact still_t naming used by archive.
    exact = stills / f"still_t{t_sec:07.1f}.jpg"
    if exact.is_file():
        return exact
    best = None
    best_dist = 1e9
    for path in stills.glob("still_t*.jpg"):
        try:
            # still_t00012.0.jpg
            num = path.stem.replace("still_t", "")
            tt = float(num)
        except ValueError:
            continue
        d = abs(tt - t_sec)
        if d < best_dist:
            best_dist = d
            best = path
    return best if best is not None and best_dist <= 2.5 else best


def _whisper_window(wav_path: Path, t0: float, t1: float, model) -> str:
    """Legacy window ASR (kept for tests); prefer full-take cache in draft_queue."""
    # Expand short windows so VAD/music beds have a chance.
    mid = 0.5 * (t0 + t1)
    half = max((t1 - t0) * 0.5, MIN_CLIP_ASR_SEC * 0.5)
    a = max(0.0, mid - half)
    b = a + max(t1 - t0, MIN_CLIP_ASR_SEC)
    audio, _rate = _read_wav_mono16(wav_path, a, b)
    segments, _info = model.transcribe(audio, language="en", vad_filter=False, beam_size=1)
    return " ".join(seg.text.strip() for seg in segments if seg.text.strip())


def draft_queue(
    *,
    model: str = DEFAULT_TEXT_MODEL,
    vision_model: str = VISION_MODEL,
    use_whisper: bool = True,
    use_vision: bool = True,
    root: Path | None = None,
    limit: int | None = None,
    only_unscored: bool = True,
) -> dict[str, Any]:
    root = root or data_root()
    label_dir = farm_label_dir(root)
    queue_path = label_dir / "queue.jsonl"
    if not queue_path.is_file():
        raise FileNotFoundError(f"missing queue: {queue_path} — run: python -m tools.windows_lab farm seed-queue")

    rows = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    key_path = label_dir / "key.jsonl"
    existing: dict[str, dict[str, Any]] = {}
    if key_path.is_file():
        for line in key_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("clip"):
                existing[row["clip"]] = row

    # Never re-draft clips the human already locked in take_judgments.json.
    judged: set[str] = set()
    judgments_path = label_dir / "take_judgments.json"
    if judgments_path.is_file():
        try:
            judgments = json.loads(judgments_path.read_text(encoding="utf-8"))
            for cid, j in judgments.items():
                if (j.get("regions") or []):
                    judged.add(str(cid))
        except json.JSONDecodeError:
            judged = set()

    if only_unscored:
        unscored = [
            r
            for r in rows
            if r["clip"] not in judged and not (existing.get(r["clip"]) or {}).get("model")
        ]
        scored_weak = [
            r
            for r in rows
            if r["clip"] not in judged
            and (existing.get(r["clip"]) or {}).get("model")
            and (existing.get(r["clip"]) or {}).get("bucket") == "uncertain"
            and (existing.get(r["clip"]) or {}).get("confidence") == "low"
            and (existing.get(r["clip"]) or {}).get("ask") != "locked"
            and (existing.get(r["clip"]) or {}).get("source") not in {"gold", "human"}
        ]

        def _rank(r: dict[str, Any]) -> tuple:
            # Accuracy probes and high-priority first; then newest session id.
            src = 0 if r.get("source") == "accuracy_probe" else 1
            pri = int(r.get("priority") or 99)
            sess = str(r.get("session") or r.get("clip") or "")
            return (src, pri, sess)

        unscored = sorted(unscored, key=_rank)
        scored_weak = sorted(scored_weak, key=_rank)
        rows = unscored + scored_weak

    if limit is not None:
        rows = rows[:limit]

    whisper_model = None
    if use_whisper:
        from faster_whisper import WhisperModel

        whisper_model = WhisperModel("base.en", device="cpu", compute_type="int8", cpu_threads=4)

    transcript_cache: dict[str, dict[str, Any]] = {}
    auto_path = label_dir / "auto_labels.jsonl"
    auto_rows: list[dict[str, Any]] = []
    audit_events: list[dict[str, Any]] = []
    tick_id = datetime.now(timezone.utc).isoformat()
    drafted = 0
    asr_empty_n = 0
    vision_n = 0
    skipped_no_evidence = 0

    for row in rows:
        clip = row["clip"]
        session_dir = Path(row["session_dir"])
        t0 = float(row["t0"])
        t1 = float(row["t1"])
        prior = existing.get(clip) or {}
        # Never overwrite gold / human locks.
        if prior.get("gold") or prior.get("source") in {"gold", "human"} or prior.get("ask") == "locked":
            continue
        aid_note = prior.get("note") if not prior.get("model") else None
        human_note = prior.get("human_note") or (prior.get("note") if prior.get("source") == "human" else None)

        text = ""
        text_source = "no_whisper"
        if use_whisper:
            key_dir = str(session_dir)
            if key_dir not in transcript_cache:
                transcript_cache[key_dir] = ensure_take_transcript(session_dir, whisper_model=whisper_model)
            tr = transcript_cache[key_dir]
            if tr.get("ok"):
                text = transcript_for_window(tr, t0, t1)
                text_source = "farm_transcript_full_take"
            else:
                wav = session_dir / str(row.get("audio_rel") or "audio.wav")
                if wav.is_file() and whisper_model is not None:
                    try:
                        text = _whisper_window(wav, t0, t1, whisper_model)
                        text_source = "whisper_window_fallback"
                    except Exception as exc:  # noqa: BLE001
                        text = ""
                        text_source = f"whisper_failed:{exc}"

        visual = ""
        visual_meta: dict[str, Any] = {"ok": False}
        still = nearest_still(session_dir, 0.5 * (t0 + t1))
        stills_agree = True
        if use_vision:
            visual_meta = describe_clip_stills(session_dir, t0, t1, model=vision_model)
            if visual_meta.get("ok"):
                visual = str(visual_meta.get("visual") or "")
                vision_n += 1
                stills_agree = bool(visual_meta.get("stills_agree", True))
                if visual_meta.get("stills"):
                    still = Path(visual_meta["stills"][len(visual_meta["stills"]) // 2])

        asr_empty = not bool(text.strip())
        visual_empty = not bool(visual.strip())
        if asr_empty:
            asr_empty_n += 1

        # 90/10: black / green-corrupt still + no speech → skip (not human work).
        mid_still = still if isinstance(still, Path) else nearest_still(session_dir, 0.5 * (t0 + t1))
        dead_frame = is_black_or_corrupt_still(mid_still) if asr_empty else None
        # Early-ASR scrap for content desync (picture ad / audio still program).
        head_text = ""
        if tr and tr.get("ok") and (t1 - t0) >= 8.0:
            head_end = t0 + min(10.0, (t1 - t0) * 0.45)
            head_text = transcript_for_window(tr, t0, head_end, pad=0.0)
        desync = detect_av_content_desync(
            head_text=head_text or text,
            visual=visual,
            still_classes=list(visual_meta.get("still_classes") or []),
            span_s=float(t1 - t0),
        )
        if asr_empty and dead_frame in {"black", "green_corrupt"}:
            skipped_no_evidence += 1
            draft = {
                "bucket": "uncertain",
                "kind": "unknown",
                "confidence": "low",
                "why": f"skip_{dead_frame}_silent",
            }
            model_used = None
            ask = "skip"
            text_source = f"{text_source}|{dead_frame}_silent"
        elif desync:
            # Loud but wrong speech for the picture — not gold, not morning-batch work.
            skipped_no_evidence += 1
            draft = {
                "bucket": "uncertain",
                "kind": "unknown",
                "confidence": "low",
                "why": desync["why"],
            }
            model_used = None
            ask = "skip"
            text_source = f"{text_source}|av_desync:{desync.get('kind')}"
        elif asr_empty and visual_empty:
            # No speech/vision text, but frame isn't obviously black — rare; park for human.
            skipped_no_evidence += 1
            draft = {
                "bucket": "uncertain",
                "kind": "unknown",
                "confidence": "low",
                "why": "no_transcript_and_no_visual",
            }
            model_used = None
            ask = "needs_human"
        elif visual_meta.get("stills_disagree") and asr_empty:
            # Boundary + no speech — human later; don't invent.
            draft = {
                "bucket": "uncertain",
                "kind": "unknown",
                "confidence": "low",
                "why": "stills_disagree_possible_boundary",
            }
            model_used = None
            ask = "needs_human"
            text_source = f"{text_source}|stills_disagree"
        else:
            # 90/10: boundary WITH speech (or agreeing stills) → draft normally.
            # Mid-only visual is already selected when stills disagree.
            boundary = bool(visual_meta.get("stills_disagree"))
            try:
                draft = _ask_ollama_text(model, text, visual)
                draft = apply_common_sense(draft, text, visual)
                model_used = model
            except Exception as exc:  # noqa: BLE001
                draft = {
                    "bucket": "uncertain",
                    "kind": "unknown",
                    "confidence": "low",
                    "why": f"ollama_failed:{exc}",
                }
                draft = apply_common_sense(draft, text, visual)
                model_used = model
                text_source = f"{text_source}|ollama_failed"
            if boundary:
                text_source = f"{text_source}|stills_disagree_drafted"
                draft["why"] = (str(draft.get("why") or "")[:100] + " | boundary_stills").strip(" |")
            # While building trust: even high-confidence non-auto stays in review.
            ask = "review"
            if model_used and _auto_accept(
                draft, text, visual, stills_agree=stills_agree and not boundary, root=root
            ):
                ask = "optional_confirm"

        key = {
            "clip": clip,
            "session": row.get("session"),
            "t0": t0,
            "t1": t1,
            "bucket": draft["bucket"],
            "kind": draft["kind"],
            "confidence": draft["confidence"],
            "ask": ask,
            "why": draft.get("why"),
            "whisper_text": text[:500],
            "visual_text": visual[:500],
            "still": str(still) if still else None,
            "note": (text[:120] if text else (visual[:120] if visual else "")),
            "human_note": human_note,
            "aid_note_ignored_for_model": (aid_note[:120] if aid_note else None),
            "text_source": text_source,
            "vision_source": visual_meta.get("model") if visual_meta.get("ok") else visual_meta.get("error"),
            "asr_empty": asr_empty,
            "stills_agree": stills_agree,
            "still_classes": visual_meta.get("still_classes"),
            "model": model_used,
            "slot": row.get("slot"),
            "drafted_utc": tick_id,
            "tick_id": tick_id,
            "evidence": {
                "has_asr": not asr_empty,
                "has_visual": not visual_empty,
                "stills_agree": stills_agree,
            },
        }

        if ask == "optional_confirm" and model_used:
            auto_rows.append(
                {
                    **key,
                    "auto": True,
                    "auto_rule": "paid_ad+high+lexicon_or_visual",
                }
            )

        audit_events.append(
            {
                "utc": tick_id,
                "clip": clip,
                "session": row.get("session"),
                "t0": t0,
                "t1": t1,
                "ask": ask,
                "bucket": draft["bucket"],
                "kind": draft["kind"],
                "confidence": draft["confidence"],
                "why": draft.get("why"),
                "model": model_used,
                "vision_source": key.get("vision_source"),
                "text_source": text_source,
                "asr_empty": asr_empty,
                "stills_agree": stills_agree,
                "prior_ask": prior.get("ask"),
                "prior_bucket": prior.get("bucket"),
            }
        )
        existing[clip] = key
        drafted += 1

    atomic_write_jsonl(key_path, list(existing.values()))
    atomic_write_jsonl(auto_path, auto_rows)
    audit_path = None
    if audit_events:
        audit_path = append_draft_events(audit_events, root=root, tick_id=tick_id)

    unloaded = {
        "text": unload_ollama_model(model),
        "vision": unload_ollama_model(vision_model) if use_vision else None,
    }
    help_queue = promote_help_queue(root)
    digest = write_daily_digest(root)
    try:
        from .farm_ops import emit

        emit(
            "label_tick",
            detail=f"drafted={drafted} auto={len(auto_rows)} help={help_queue.get('needs_human', 0)}+{help_queue.get('review', 0)}",
            ok=True,
            extra={
                "drafted": drafted,
                "auto_accepted": len(auto_rows),
                "skipped_no_evidence": skipped_no_evidence,
                "tick_id": tick_id,
                "audit_path": str(audit_path) if audit_path else None,
                "morning_batch": (help_queue or {}).get("morning_batch"),
                "model": model,
            },
            root=root,
        )
    except Exception:  # noqa: BLE001
        pass
    return {
        "drafted": drafted,
        "auto_accepted": len(auto_rows),
        "asr_empty": asr_empty_n,
        "vision_ok": vision_n,
        "skipped_no_evidence": skipped_no_evidence,
        "key_path": str(key_path),
        "auto_path": str(auto_path),
        "audit_path": str(audit_path) if audit_path else None,
        "tick_id": tick_id,
        "model": model,
        "vision_model": vision_model if use_vision else None,
        "review_url": "http://127.0.0.1:3010/farm",
        "ollama_unloaded": unloaded,
        "only_unscored": only_unscored,
        "help_queue": help_queue,
        "daily": digest,
    }


def promote_help_queue(root: Path | None = None) -> dict[str, Any]:
    """Keep /farm fed: prioritize clips where the open-source draft needs a human.

    - needs_human → priority 10
    - review (not auto) → priority 20
    - optional_confirm / locked / gold → leave or demote (priority ≥ 90)
    Attaches ask/why onto queue rows for the UI.
    """
    label_dir = farm_label_dir(root)
    queue_path = label_dir / "queue.jsonl"
    key_path = label_dir / "key.jsonl"
    if not queue_path.is_file():
        return {"ok": False, "error": "missing queue", "needs_human": 0, "review": 0}

    keys: dict[str, dict[str, Any]] = {}
    if key_path.is_file():
        for line in key_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            clip = row.get("clip")
            if clip:
                keys[str(clip)] = row

    queue_rows = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    needs_n = 0
    review_n = 0
    updated = 0
    for row in queue_rows:
        clip = str(row.get("clip") or "")
        key = keys.get(clip) or {}
        ask = str(key.get("ask") or "")
        # Gold / locked / human locks stay available for confirm but not "help" priority.
        if key.get("gold") or ask == "locked" or key.get("source") in {"gold", "human"}:
            if "ask" not in row and ask:
                row["ask"] = ask
            continue
        pri = review_priority(key)
        if pri is not None:
            row["priority"] = pri
            updated += 1
            if ask == "needs_human":
                needs_n += 1
            elif ask == "review":
                review_n += 1
            elif ask == "skip":
                row["review_batch"] = "skip"
        elif str(row.get("source") or "") in {"transcript_boundary", "fallback_tile"} and ask not in {
            "needs_human",
            "review",
            "skip",
        }:
            # Undrafted transcript chops are weak — park them until the model asks.
            row["priority"] = max(int(row.get("priority") or 99), 80)
            updated += 1
        if ask:
            row["ask"] = ask
        why = key.get("why") or key.get("note")
        if why:
            row["why"] = str(why)[:240]
            if not row.get("caption"):
                row["caption"] = str(why)[:120]
        if key.get("bucket"):
            row["draft_bucket"] = key.get("bucket")
        if key.get("confidence"):
            row["draft_confidence"] = key.get("confidence")

    morning = apply_morning_batch(queue_rows, budget=MORNING_REVIEW_BUDGET)
    queue_rows.sort(
        key=lambda r: (
            0 if r.get("review_batch") == "active" else 1,
            int(r.get("priority") or 99),
            str(r.get("session") or ""),
            float(r.get("t0") or 0),
        )
    )
    atomic_write_jsonl(queue_path, queue_rows)

    return {
        "ok": True,
        "queue_path": str(queue_path),
        "needs_human": needs_n,
        "review": review_n,
        "updated": updated,
        "queue_n": len(queue_rows),
        "morning_batch": morning,
        "review_url": "http://127.0.0.1:3010/farm",
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="High-accuracy farm drafts (Whisper + stills + Ollama)")
    p.add_argument("--model", default=DEFAULT_TEXT_MODEL)
    p.add_argument("--vision-model", default=VISION_MODEL)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--no-whisper", action="store_true")
    p.add_argument("--no-vision", action="store_true")
    p.add_argument("--all", action="store_true", help="Include already-scored clips")
    args = p.parse_args(argv)
    out = draft_queue(
        model=args.model,
        vision_model=args.vision_model,
        use_whisper=not args.no_whisper,
        use_vision=not args.no_vision,
        limit=args.limit,
        only_unscored=not args.all,
    )
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
