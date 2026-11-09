# NFL75_BRIDGE_001

One decision step for replay and live shadow. No model was trained. Automatic mute stays off. The sports daemon was not restarted.

## Reused

The step is `ohush_live.state.Machine`. Thresholds stay the constants in `ohush_live.policy`: `AUDIO_STRONG` 0.22, `AUDIO_RETURN` 0.12, `SOLO_MUTE_PERSIST_S` 4.0, `SOLO_PLAY_PERSIST_S` 3.0, `MIN_MUTE_HOLD_S` 6.0, product `OHUSH_LIVE_V0`. The show floor is `hush.voice_floor.FLOOR`, 0.10. `ListenerGate.play_program(prompt=False)` still uses its 1.5-second automatic return fade. `tnf_lab.py` was left on its own observe path.

`Bridge.step` is the only new decision function. `replay()` and `Shadow.observe_evidence()` both call it. `SportsSession.tick` asks the shadow for that decision and writes every tick, including `NO_CHANGE`, to `bridge.jsonl`. `shadow.jsonl` stays transition-only, with `applied` false.

## Configuration

Identity `cea44a0e1f4db301`. Bridge `NFL75_BRIDGE_001`. Freshness window 15 seconds. `automatic_mute_enabled` is false on every decision. Raw departure and return scores are copied through. They are not treated as probabilities.

A reading is usable when it is a dict, `audio_end_s` and `available_at_s` are present, `audio_end_s` is at or before `available_at_s`, and `max(audio_end_s, available_at_s)` is at or before the decision time and no older than 15 seconds. Anything else is `missing`, `future_audio`, `not_yet_available`, or `stale`, and it does not enter `Machine.step`.

## Parity

Synthetic tape: seconds 0–59 departure 0.05, 60–179 departure 0.40, 180–240 departure 0.05. Speaker and semantic readings absent.

| Path | Cover | Return |
| --- | --- | --- |
| `replay()` | 63.0s `COVER` `solo_audio_depart` | 182.0s `PLAY` `solo_audio_return` |
| `live_shadow()` | same dicts | same dicts |

The cover is the fourth second of commercial-like audio, which is the existing 4-second solo persist. The return is the third second of program-like audio, which is the existing 3-second solo return. The 6-second minimum hold is already satisfied by then.

The same tape with each score delivered 8 seconds after the audio it describes covers at 71.0s and returns at 190.0s. A score whose `available_at_s` is still ahead of the decision clock stays `NO_CHANGE` with status `not_yet_available`.

A prefix ending at 100 seconds matches the full tape through 100 seconds. A reading at decision time 10 whose audio ends at 200 is status `future_audio` and does not change the actions through 60 seconds. A gold key, a label, or a clock that steps backwards raises `ValueError`.

Missing audio from 60 through 74, then a hot score at 75, does not cover before 75. After a cover, a 20-second-old score returns with `stale_fail_open`, and the next fresh hot second stays `NO_CHANGE`. A cover started with `manual(..., "mute")` stays up on that stale score, reason `human_cover_held`. `reset()` returns the machine to `PLAY` and clears the clock.

## Speakers

On the desk, four ticks of hot audio with Auto off log `NO_CHANGE`, `NO_CHANGE`, `NO_CHANGE`, `COVER`. Every row has `applied` false. `ListenerGate.mode` stays `program`.

`carry_out(..., enabled=False)` leaves the gate on program. `carry_out(..., enabled=True)` calls `play_replacement()` for `COVER` and `play_program(prompt=False)` for `PLAY`. The receipt's `return_fade_s` is 1.5. `SportsSession.tick` does not call `carry_out`.

When Auto is already on, the existing speaker path still calls `SportsSession.machine.step` and `begin_auto_cover`. That path is a second machine. It is the current living-room mute, and this ticket left it in place so existing auto tests keep their behavior. The bridge decision beside it is a log.

## Files

Changed: `ohush_live/bridge.py`, `ohush_live/shadow.py`, `ohush_live/sports_daemon.py`, `tests/test_nfl75_bridge.py`, `tests/test_ohush_live_sports.py` (the two fail-open tests now close `bridge.jsonl`).

Inspected and left as they were: `ohush_live/policy.py`, `ohush_live/state.py`, `ohush_live/gate.py`, `ohush_live/tnf_lab.py`.

## Command

```
python -m unittest tests.test_nfl75_bridge tests.test_ohush_live_shadow tests.test_ohush_live_state tests.test_ohush_live_sports tests.test_ohush_live_corrections -v
```

62 tests, OK.

## Blockers

The checkout has no game recordings, so this proof is the synthetic tape. A previously labeled game has not yet been walked through the adapter.

The fingerprint reader from NFL75_001 can still change a hash after later audio arrives. The bridge refuses an illegal stamp. It will accept a score that already folded future audio into a legal stamp.

The living-room speakers do not follow this step yet.
