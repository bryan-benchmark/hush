# Optical pass-through

23 October 2026. This is the path already in the rack: television optical out, into the computer, out to headphones or a soundbar. The computer is beside the television speakers. It is not a relay in series with them.

## What the code does

Program mode copies the input block to the output. `tests/test_ohush_live_sports.py` `test_program_passthrough_after_prime` pushes a constant block and reads the same samples back after the prime.

The ring does not grow without a bound when the output runs slower than the input. `test_ring_does_not_grow_past_prime_slack`.

A quiet family reading, with auto off, leaves the gate on program. The shadow log may record a would-cover. It does not switch the speakers. That is `tests/test_ohush_live_shadow.py`.

If an automatic cover never lets go, the output clock returns the television at 180 seconds. `test_output_clock_restores_television_if_the_controller_stops`. A hand on Cover does not arm that clock.

## When the computer stops

The optical output of the television keeps running. The television's own speakers are the sound the room still has. This desk turns those speakers down while a person listens on the computer. If the computer loses power, those speakers are turned back up. There is no inline bypass switch in this build, and none is added here.

HDMI ARC, eARC, and multichannel are later compatibility tests. This qualification is stereo PCM through the gate the sports desk already uses.
