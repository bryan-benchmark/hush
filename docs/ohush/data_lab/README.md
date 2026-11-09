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

## Capture farm (Streamers + OTA)

Default media is **AV** (BlueStacks window + archival 48 kHz WAV). Pass `--media audio` for audio-only.

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

# Manual session
python -m tools.windows_lab session start --source streamers --instance Nougat32 --channel ESPN --minutes 180 --media av
python -m tools.windows_lab session start --source streamers --instance Nougat32 --channel ESPN --minutes 180 --media audio

# Schedule
python -m tools.windows_lab schedule add --source streamers --at 2026-11-09T20:00:00-05:00 --minutes 210 --instance Nougat32 --channel ESPN --media av
python -m tools.windows_lab schedule list
python -m tools.windows_lab schedule run-due
python -m tools.windows_lab schedule install-task
# then run the generated C:\OHushData\farm\register_capture_scheduler.ps1 once as admin/user

# Unlabeled index
python -m tools.windows_lab catalog list

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

Farm config lives under `C:\OHushData\farm\` (`instances.json`, `ota.json`, locks). Sessions land in `authorized_sources\<session_id>\` with `meta.json`, `audio_XXXX.wav`, and optional `video_XXXX.mp4`. The unlabeled queue is `indexes\capture_sessions.jsonl`.

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
