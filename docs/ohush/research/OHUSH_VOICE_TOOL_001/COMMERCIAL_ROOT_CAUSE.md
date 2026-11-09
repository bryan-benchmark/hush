# Commercial vs booth — root cause

Path B cosine is the frozen ECAPA match to the enrolled cast on the owner box. Who is the latest owner label. Same-voice means the owner named an enrolled cast member reading the ad. False accept means a different or unknown person cleared as the cast.

## Ranked by cosine

| Clip | What | Who (owner) | Model | Cosine | Gap | Root cause |
| --- | --- | --- | --- | ---: | ---: | --- |
| fn0109 | DraftKings | Clarissa Thompson doing the ad | Clarissa Thompson | 0.493 | 0.413 | Same voice. Enrolled announcer reading an ad. |
| fn0118 | Wendy's | unknown female | Clarissa Thompson | 0.373 | 0.277 | False accept. |
| fn0110 | FanDuel | unknown male | Kirk Herbstreit | 0.321 | 0.216 | False accept. Not established as Fitzpatrick. |
| fn0113 | FanDuel | unknown male | Andrew Whitworth | 0.282 | 0.016 | Thin false accept. Gap under 0.15. |
| fn0119 | laundry / OxiClean | male football player, not booth | Tony Gonzalez | 0.253 | 0.021 | Thin false accept. Active player. |
| fn0101 | T-Mobile | Billy Bob Thornton | Al Michaels | 0.226 | 0.206 | Under 0.25 on the whole box. |
| fn0105 | T-Mobile | (ad only) | Kirk Herbstreit | 0.227 | 0.126 | Under 0.25. |
| fn0107 | Subway | Will Arnett | Andrew Whitworth | 0.216 | 0.003 | Under 0.25. |
| fn0114 | T-Mobile | Billy Bob Thornton | Al Michaels | 0.209 | 0.042 | Under 0.25. |
| fn0102 | Subway | Will Arnett | Kirk Herbstreit | 0.182 | 0.043 | Under 0.25. |
| fn0103 | Lowe's | Jordan Love | Al Michaels | 0.024 | 0.106 | Under 0.25. |

## Split

| Class | Clips | What it means for mute |
| --- | --- | --- |
| Same enrolled voice in an ad | DraftKings → Thompson | Speaker recognition can be right. Mute still needs commercial evidence. |
| False accept over 0.25 with a wide gap | Wendy's → Thompson, FanDuel → Herbstreit | Nearest-of-five names the wrong person confidently. |
| Thin accept near 0.25 | FanDuel/Whitworth, OxiClean/Gonzalez | Low gap. Margin 0.15 already blocks the three-name guard. |
| Named other people under 0.25 | Billy Bob, Will Arnett, Jordan Love | Whole-box Path B stays under the line. |

FanDuel is an unknown male on this tape. It is not the Fitzpatrick desk clip. Comparing those two boxes as the same person was the wrong premise.
