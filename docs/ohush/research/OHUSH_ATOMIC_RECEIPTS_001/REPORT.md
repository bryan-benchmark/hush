# Atomic receipts for the gate failures

The frozen acoustic head stays the champion. These receipts join what was already on disk: the probability stream, the reconstructed controller, the gold and reviewed boundaries, the ECAPA cache, and the saved transcripts. Nothing here trains or changes live volume.

Receipts live under `C:\OHushData\gpu_lab\audio_learn\atomic_receipts\`. Index: `index.json`. One file per focus span, every 0.25 s hop.

## What the raw files already contain

| Source | Fields | Gap |
| --- | --- | --- |
| `predictions/frozen/{session}.npz` | `t`, `p`, `label` | `label` is gold class for training, not the controller's belief. No action, no reason, no speaker, no transcript. |
| Controller | reconstructed from `p` with on 0.90 / off 0.50 / streaks 8 and 2 | Not written beside the hop when the stream was scored. |
| ECAPA protect cache | window start/end, per-name cosine | Separate file. Never joined to the mute decision. |
| Semantic probe rows | causal transcript, 14B action | Separate file. Probe times only, not every hop. |
| Live shadow receipts | richer reason strings | Not the research path that produced these Prime scores. |

So the research path is not a black box once joined, but it was a scattered box. A person had to rebuild the controller and stitch three stores to see one second of television.

## Confusion at the hop (inside each span)

Definitions for this table:

- TP = gold commercial (or reviewed spot), action cover
- FN = gold commercial, action play
- FP = gold program, action cover
- TN = gold program, action play

| Span | Gold | Model thinks (median p) | TP | FP | TN | FN | First cover |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Odell desk | program | commercial 0.98 | 0 | 241 | 0 | 0 | at start |
| Whitworth desk | program | commercial 0.94 | 0 | 117 | 0 | 0 | at start |
| Palmer report | program | commercial 0.99 | 0 | 108 | 1 | 0 | at start |
| Injury desk | program | commercial 0.91 | 0 | 77 | 0 | 0 | at start |
| Welcome back | program | lean commercial 0.87 | 0 | 23 | 0 | 0 | at start |
| Live play (ok) | program | program 0.001 | 0 | 0 | 32 | 0 | none |
| Chili's (reviewed) | commercial | commercial 0.98 | 125 | 0 | 0 | 21 | +5.4 s |
| Amex (reviewed) | commercial | commercial 0.97 | 197 | 0 | 0 | 14 | +3.7 s |

The studio failures are pure false positives at the hop. The controller is not inventing them. At Odell t=7035.0, `p=0.972`, action already `cover`, gold `program`. The same pattern holds through the middle of the minute. Live play is a pure true negative at `p≈0.001`.

The reviewed spots are mostly true positives. The FN hops are the opening delay while the on-streak fills (8 hops = 2.0 s) plus a little onset, not a belief that the spot is the show.

## Where the logic is lost

1. **Acoustic belief.** On the desks the stream says commercial at ~0.97 and stays there. Changing the on/off lines inside the declared grid cannot clear a minute that never falls to 0.50.
2. **Identity is available and unused.** During Odell, 39 voice windows clear 0.25 (Whitworth first at the open). During Whitworth, 27 clear. During Palmer, 25 clear as Clarissa Thompson, starting about 1.3 s into the report. During the injury desk, 0 clear. The mute decision never reads those numbers.
3. **Words are available late and unused by the volume path.** At Odell onset, 8 s of transcript is still `unknown` for 14B; 20 s becomes `play`. At the middle, 8 s is already `play`. Whitworth stays `unknown`. Injury stays `unknown`. Palmer's first 8 s are still IHOP (`mute`); the report itself is `play`. None of that is an input to the controller today.
4. **Label scrap is a different cell.** Chili's and Amex are TP under reviewed boundaries. Counting them as FP on the original gold hides a bookkeeping error as a model error.

## Rules that need adding, removing, or leaving alone

| Rule | Verdict | Why |
| --- | --- | --- |
| Cover when p stays ≥ 0.90 for 2.0 s | Keep for ads | Live play stays TN; Chili's/Amex become TP after the streak. |
| Return when p ≤ 0.50 for 0.5 s | Keep | Desks never reach 0.50, so this is not what holds them. |
| Lower the cover line to rescue desks | Do not | Desks sit near 1.00; ads would open with them. |
| Add more studio audio / longer acoustic window | Do not | Already measured; TV got worse. |
| Cast-wide voice veto on current window | Do not install | Measured; opens October ads. |
| Join voice and transcript into the receipt | Add | Required for any later rule that uses them; also required so the next failure is readable without stitching. |

## Logging that must exist going forward

Every scored hop should write one JSON object with at least:

```json
{
  "session": "hush_20260924_220624",
  "t": 7035.0,
  "evidence_through": 7035.0,
  "p_commercial": 0.972,
  "controller_state": "cover",
  "hot_streak": 8,
  "cold_streak": 0,
  "gold": "program",
  "cell": "FP",
  "voice_best": "Andrew Whitworth",
  "voice_cosine": 0.559,
  "voice_window_end": 7034.1,
  "transcript_causal": null,
  "semantic_action": null,
  "reason": ["p_ge_on", "on_streak_met"]
}
```

`reason` is a list of fired predicates, not a paragraph. Nulls are explicit: a missing voice or transcript is a fact, not an omission. Episode rolls should point at the first hop that entered cover and the last hop that left it.

Until that join is the default write path, keep building focus receipts the way this folder does. Do not treat a mute as explained until the receipt shows what the system believed, what gold says, and which optional signals were present and ignored.
