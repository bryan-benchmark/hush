# LABEL_POLICY_V1

Truth event = an observed non-program segment or transition worth classifying. What aired and what OHush should do are separate fields.

Mark:

- IN = first audible moment the non-program segment begins.
- OUT = first audible moment normal program content resumes.

Do not infer boundaries from expected 15/30/60s lengths.
Listen and mark what actually aired. Do not nudge a boundary onto a neat number.

If a boundary cannot be determined confidently:

```text
confidence = unsure
```

Do not use detector markers, scores, suggested IN/OUT, fades, or the debug queue while creating truth. Overlay the detector only after the range is closed as fully annotated.

Once a range is closed, do not move these labels because the detector disagrees. A genuine labeling mistake can be superseded. Detector disagreement is not evidence that the truth should move.

```text
event_class:
commercial | network_promo | sponsorship | other | program

`program` names a stretch of the show itself (football, news, RedZone). IN is when that show starts, OUT is when it changes or the recording leaves it. `desired_action` is `play`. The name goes in `note`. A program mark is not a commercial, and a closed range can contain program marks and zero commercials.

desired_action:
mute | play | unsure
```

Network promos, sponsorship bumpers, and “brought to you by…” are not `commercial` unless that is what you heard. `desired_action` can change later without relabeling the audio.

Current scoring target:

```text
event_class = commercial
AND
desired_action = mute
AND
confidence != unsure
```

That target is what the audit counts. Other classes and actions stay in the ledger so a later product policy can be rescored without relabeling.
