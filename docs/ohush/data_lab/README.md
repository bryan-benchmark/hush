# OHush Data Lab (Windows Node)

Independent acquisition/analysis workers. Node 01 lives on `ohush-win-01` (GAMINGPC).

## Paths

| Role | Path |
|------|------|
| Code checkout | `C:\Users\faceo\Projects\ohush` |
| Branch | `research/windows-lab-node-01` |
| Data root | `C:\OHushData` (`OHUSH_DATA_ROOT`) |

Large WAVs, APKs, indexes, and receipts stay under the data root — never in Git.

## Worker CLI

```powershell
cd C:\Users\faceo\Projects\ohush
.\.venv\Scripts\Activate.ps1
$env:OHUSH_DATA_ROOT = "C:\OHushData"

python -m tools.windows_lab inventory
python -m tools.windows_lab capture list-devices
python -m tools.windows_lab capture fixture --outfile C:\OHushData\work\capture\tone.wav --seconds 60
python -m tools.windows_lab capture record --device "Stereo Mix" --seconds 60 --source-label my_test --rights-status test_public
python -m tools.windows_lab ingest PATH.wav --source-label LABEL --source-type authorized_stream_reference --rights-status test_public
python -m tools.windows_lab analyze PATH.wav
python -m tools.windows_lab health
```

`rights_status=unknown` is rejected by ingest.

## Fire tablet line-in

One Fire tablet running Streamers. Its headphone output goes into the motherboard stereo line input, and this PC records that input locally.

This machine is an MSI PRO B650-VC WIFI with six rear audio jacks. The blue jack is the stereo line input, `Line In (Realtek HD Audio Line input)`. Windows hides that jack from OBS and from FFmpeg DirectShow until a plug is detected. The recorder below opens the line input directly.

1. Set the tablet next to this PC.
2. Connect the tablet headphone output to the rear blue Line In with a stereo 3.5 mm cable. If Windows asks what was plugged in, choose Line In.
3. Open Streamers and play the channel. Leave the tablet volume near three-quarters.
4. Confirm the level, then take five minutes:

```powershell
python -m tools.windows_lab capture tablet check
python -m tools.windows_lab capture tablet record --seconds 300 --analyze
```

`check` has to report `"level": "live"` before a long take. A silent check means the cable is out of the blue jack or Streamers is not playing. WAVs land in `C:\OHushData\work\capture\tablet\`. The `--analyze` flag runs the local QA pass on that WAV. Confirm the subscription allows the capture before keeping a long file.

One tablet is one channel. A second channel needs its own input.

## Salvation on BlueStacks

The full login is [`SALVATION_BLUESTACKS.md`](SALVATION_BLUESTACKS.md). One command, after the login file exists at `C:\OHushData\farm\salvation_login.json`:

```powershell
python -m tools.windows_lab salvation login --instance Nougat32
python -m tools.windows_lab salvation status --instance Nougat32
```

`screen` is `home` when Streamers is signed in. Channel changes and recording, after that home screen, are [`STREAMERS_CONTROLS.md`](STREAMERS_CONTROLS.md).

## Capture farm (Streamers + OTA)

Default media is **`av`**: archival 48 kHz WAV **plus sparse stills** (1 frame/sec by default) for labeling context. That is the long-term visual archive — not full game tapes.

| `--media` | Keeps |
|-----------|--------|
| `av` (default) | `audio_XXXX.wav` + `stills/still_tNNNN.N.jpg` |
| `av_full` | WAV + retained `video_XXXX.mp4` (rare; distill later) |
| `audio` | WAV only |

```powershell
# Instance registry / doctor
python -m tools.windows_lab instances list
python -m tools.windows_lab instances doctor
python -m tools.windows_lab instances discover
python -m tools.windows_lab instances launch --instance Nougat32

# Channel recipes (ADB steps for ar.tvplayer.tv / Streamers)
python -m tools.windows_lab channel save-example --channel-id ESPN
# edit C:\OHushData\channel_recipes\ESPN.json taps/keyevents, then:
python -m tools.windows_lab channel apply --source streamers --instance Nougat32 --channel ESPN --dry-run
python -m tools.windows_lab channel apply --source streamers --instance Nougat32 --channel ESPN

# Manual session (stills archive)
python -m tools.windows_lab session start --source streamers --instance Nougat32 --channel ESPN --minutes 180 --media av
python -m tools.windows_lab session start --source streamers --instance Nougat32 --channel ESPN --minutes 180 --media av --still-interval 2
python -m tools.windows_lab session start --source streamers --instance Nougat32 --channel ESPN --minutes 180 --media av_full
python -m tools.windows_lab session start --source streamers --instance Nougat32 --channel ESPN --minutes 180 --media audio

# Distill an old full-video session into stills (deletes video_*.mp4 unless --keep-video)
python -m tools.windows_lab archive distill --session-dir C:\OHushData\authorized_sources\SESSION_ID
python -m tools.windows_lab archive info --session-dir C:\OHushData\authorized_sources\SESSION_ID

# Contested label edge: keep a short clip/still pack (±10s pad), not the whole show
python -m tools.windows_lab archive edge-clip --session-dir C:\OHushData\authorized_sources\SESSION_ID --start 3384.3 --end 3437.1 --label amex_spot

# Schedule
python -m tools.windows_lab schedule add --source streamers --at 2026-11-09T20:00:00-05:00 --minutes 210 --instance Nougat32 --channel ESPN --media av
python -m tools.windows_lab schedule list
python -m tools.windows_lab schedule run-due
python -m tools.windows_lab schedule install-task
# then run the generated C:\OHushData\farm\register_capture_scheduler.ps1 once as admin/user

# Unlabeled index
python -m tools.windows_lab catalog list

# Coverage farm — three ops + autonomous loop (ORCHESTRATION.md)
python -m tools.windows_lab farm status           # 1 record / 2 label / 3 human dashboard
python -m tools.windows_lab farm loop             # scheduled autonomy pass
python -m tools.windows_lab farm loop install-task --register
python -m tools.windows_lab farm record           # op1: hierarchy + guide priority
python -m tools.windows_lab farm label --tick     # op2: Ollama + how far behind
python -m tools.windows_lab farm human            # op3: /farm only if required
python -m tools.windows_lab farm plan
python -m tools.windows_lab farm board
python -m tools.windows_lab farm capacity
python -m tools.windows_lab farm dispatch --dry-run
# Doctrine: docs/ohush/research/COVERAGE_FARM_001/ORCHESTRATION.md

# Multi-instance isolation
python -m tools.windows_lab multi-instance report
python -m tools.windows_lab multi-instance write-checklist
python -m tools.windows_lab multi-instance sync-discovered
python -m tools.windows_lab instances crosstalk --a Nougat32 --b Nougat32_1

# OTA antenna (after USB ATSC tuner is attached to the HD 4-1)
python -m tools.windows_lab ota doctor
python -m tools.windows_lab ota scan
python -m tools.windows_lab ota set-tuner --dshow-video "TUNER NAME" --dshow-audio "TUNER AUDIO"
python -m tools.windows_lab ota upsert-channel --channel 7.1 --major 7 --minor 1 --label ABC
python -m tools.windows_lab schedule add --source ota --at ... --minutes 120 --channel 7.1 --media av
```

Farm config lives under `C:\OHushData\farm\` (`instances.json`, `ota.json`, locks). Sessions land in `authorized_sources\<session_id>\` with `meta.json`, `audio_XXXX.wav`, and (for default `av`) `stills\` plus optional `edge_clips\` for contested boundaries. Full `video_XXXX.mp4` only when `--media av_full` or distill has not run yet. The unlabeled queue is `indexes\capture_sessions.jsonl`.

## Source classes

- `optical` — Mac TV optical path only
- `authorized_stream_reference` — emulator / app / stream / OTA capture on Windows (not Universal optical)
- `test_public_fixture` — synthetic or licensed public test media

Session meta also carries `source_kind`: `streamers` or `ota_antenna`.

## Policy

- No automatic muting
- No credentials or stream URLs in receipts
- No merge into Universal optical gold / holdouts from this worker
- Parallel Streamers instances require distinct VB-Cable (or equivalent) loopbacks
