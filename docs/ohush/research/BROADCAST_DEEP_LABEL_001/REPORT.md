# BROADCAST_DEEP_LABEL_001

Deep labels so Prime desk vs dry commercial can be stratified.

## Open

http://127.0.0.1:3010/deep

(Requires `./scripts/desk ui` or the monitor app.)

## Fields

| field | why |
|---|---|
| bucket | broadcast / non_broadcast / unsure |
| kind | desk subtype or ad shape |
| phase | pregame / Q / half / post — your ear when ASR is silent |
| setting | studio / sideline / package / spot |
| speaker | who talks — especially enroll-cold desks |
| note | free text |

Agent drafts are in `key.jsonl` and show as hints. Saves go to `judgments.json`.

## Queue shape

1. Desk spans that need speaker/phase
2. Other Prime desk spans
3. Non-desk champion FPs (unlabeled / other)
4. Chili's + Amex dry VO contrast
