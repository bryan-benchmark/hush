# Category policy

Version 1. 23 October 2026.

This note is the default for a new label and for a later user preference. It does not edit closed gold, `GOLD_DATASET_20261013`, the football KPI, or the live mute. A muted second of the game still breaks a run. That rule is `docs/ohush/research/ACCURACY_LADDER_001/KPI.md`. Holdouts `hush_20260917_205513` and `hush_20260920_200635` stay sealed.

The football tapes already marked stay binary: commercial or program. Unsure gold stays excluded. A promo that was marked inside the game column stays in the game column. The Giants–Rams promo on ESPN `hush_20260914_212529` at 5,788 seconds is the example. It is 4 seconds, peak voice 0.041, and it broke a run that treated it as an ad. The policy below is how the next mark is written. It is not a reason to move that one.

## Defaults

| Category | What it is | Default |
| --- | --- | --- |
| `paid_ad` | A clearly paid advertisement | Block, skip, or mute |
| `known_commercial` | Audio already confirmed as a commercial creative | Mute |
| `sponsored_post` | A sponsored unit in a feed. No web sensor is in this repo | Hide |
| `creator_sponsorship` | A creator reading a sponsor, identified with a second check | Skip |
| `show_promo` | A network or show promotion, including the Giants–Rams line and the hockey promo | Preference. The default preference is keep |
| `program_mention` | The program talking about a product. A booth call, a sideline interview, the Allstate halftime welcome | Keep |
| `uncertain` | The evidence does not name one of the rows above | Keep, and the person can flag it |

A person can opt into hearing a category the default would remove. They can opt into muting `show_promo`. Until they do, a promo stays on. Uncertainty stays on. A missing voice, a quiet stretch, or a gap in the booth is `uncertain`. It is not a `paid_ad`.

`known_commercial` still requires the published count-200 fingerprint, or a later rule that has passed the research contract on audio it was not fit on. This table does not lower that count and does not start a cover.

## What a score is allowed to claim

Commercial seconds held, program seconds covered, the worst interruption, and the start and return lags are the television numbers. They stay on the KPI clock. A window-accuracy figure from another paper is not one of those numbers.

A web count, when a web sensor exists, is suppressed ad units, broken pages, and whether the site still works. A blocked request is not a count of seconds returned.

A single global “ads removed” figure states the assumption that produced it. It is not a substitute for the television KPI.

## Receipt

The stretches that forced these rows apart are already written in `src/hush/voice_floor.py` and `docs/ohush/research/VOICE_FLOOR_001/`. This version adds no new measurement and changes no threshold. The 0.10 enrolled-show return stays a return.
