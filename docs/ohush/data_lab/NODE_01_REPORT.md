# NODE_01_REPORT — OHush Windows Data Lab

**Node:** `ohush-win-01` (hostname `GamingPC`)  
**Date:** 2026-10-15  
**Branch:** `research/windows-lab-node-01`  
**Starting commit:** `18c7179cfd0df1e4776f0d5b3bc25c30d25e8cff`  
**Decision:** `HOLD` for two-stream pilot — but **Android → Windows PCM → OHush is now proven** on one source

---

## 1. Hardware / OS inventory

| Item | Value |
|------|-------|
| OS | Windows 11 Home 24H2, build 26100, x64 |
| CPU | AMD Ryzen 7 7800X3D (8C/16T) |
| RAM | 31.12 GB |
| GPU | NVIDIA GeForce RTX 4070 SUPER, driver 560.94, 12282 MiB |
| Disk | C: 1862 GB total / ~1671 GB free after installs |
| Virtualization | Firmware AMD-V enabled; hypervisor present (VBS running) |
| BIOS / Hyper-V / Defender | **Not changed** (per approval) |

### Tooling

| Component | Version / path |
|-----------|----------------|
| Git | 2.46.0.windows.1 (existing) |
| Node | v20.11.0 (existing) |
| Python venv | 3.13.3 at `.venv` |
| BlueStacks 5 | 5.22.166.1003 — `C:\Program Files\BlueStacks_nxt\HD-Player.exe` |
| OBS Studio | 32.2.2 — installed |
| Android platform-tools | 37.0.1 (ADB) |
| Audacity | **Not installed** (optional; Python PCM path sufficient) |

### Paths

| Role | Path |
|------|------|
| Repo | `C:\Users\faceo\Projects\ohush` |
| Data | `C:\OHushData` (`OHUSH_DATA_ROOT`) |

---

## 2. Repo / branch

```powershell
cd C:\Users\faceo\Projects\ohush
git clone https://github.com/bryan-benchmark/hush.git .
git switch -c research/windows-lab-node-01
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**Not pushed. Not merged.** Mac checkout untouched.

### Files added on this branch (local, uncommitted)

- `tools/windows_lab/` — `inventory`, `capture`, `ingest`, `analyze`, `health`, CLI
- `tests/windows_lab/test_ingest_rights.py` — 4 passed
- `docs/ohush/data_lab/README.md`, `NODE_01_REPORT.md`
- `.env.example`, `.gitignore` tweak (`!.env.example`)

---

## 3. Android emulator

| Field | Result |
|-------|--------|
| Product | BlueStacks 5 (Nougat32 engine) |
| Android | 7.1.2 (`getprop` when ADB briefly worked) |
| Model reported | SM-G988N |
| Instance | **One** (default App Player) |
| Launch | `HD-Player.exe` — window title `BlueStacks App Player`, Responding=True |
| Idle footprint | ~1.85–2.5 GB Working Set; host CPU ~7% at idle snapshot; GPU util ~0% |
| ADB | Local ADB enabled in `bluestacks.conf` (`bst.enable_adb_access=1`, remote still `0`); `HD-Adb.exe` shell/push OK after restart |
| Playback proof | Gallery `MovieActivity` played local `test_public` MP4 (`ohush_public_test_60s.mp4`) |
| Streamers APK | **`not_run`** — not installed; no credentials; awaits separate approval |

Shared folder: `C:\ProgramData\BlueStacks_nxt\Engine\UserData\SharedFolder\` (also visible in-guest).

---

## 4. Audio routing evidence

### Finding (critical)

| Fact | Detail |
|------|--------|
| Default output | **AMD HDMI (MG248)** |
| Realtek Speakers | Present at WDM-KS but MMDevice state **Unplugged** (no jack) |
| Stereo Mix | Only hears Realtek Speakers — **not** HDMI |
| Working BlueStacks path | **WASAPI loopback of MG248 HDMI** via Python `soundcard` |

| Test | Peak | Result |
|------|------|--------|
| Host fixture → HDMI + Stereo Mix | ~0.0015 | FAIL |
| Host fixture → Realtek Speakers WDM-KS + Stereo Mix 60 s | ~0.115 | PASS (host-only path) |
| BlueStacks Gallery MP4 → HDMI WASAPI loopback 60 s | ~0.070 (−24.8 dBFS) | **PASS (closed loop)** |

**OBS** installed; multi-instance isolation **not** measured.

### Canonical BlueStacks 60 s capture (closed loop)

| Field | Value |
|-------|-------|
| File | `C:\OHushData\work\capture\bluestacks_gallery_hdmi_loopback_60s.wav` |
| Player | `com.android.gallery3d/.app.MovieActivity` |
| Source media | Local synthetic `test_public` MP4 (stereo tones + color field) |
| Capture | `soundcard` WASAPI loopback of `1 - MG248 (AMD High Definition Audio Device)` |
| Format | 48 000 Hz, 2 ch, 16-bit PCM WAV |
| Duration | 60.0 s; wall clock 60.052 s |
| SHA-256 | `5db390cbab18b8dd55bf5e553b22a3df321c306a12b471d457c9c3fa1be8f36e` |
| Rights / type | `test_public` / `authorized_stream_reference` |
| Silent-frame fraction | 0.38 (startup/lead-in; overall still PASS) |

Receipt: `C:\OHushData\receipts\20261015T192608Z-5a6f4b56.json`

### QA

- PASS: measurable signal, no clipping, DC OK, midband energy, 48 kHz archival  
- Peak −24.8 dBFS · RMS −34.2 dBFS  
- Features smoke (`exp001-features-v1`) OK  

**Universal optical baselines and holdouts were not opened or modified.**

---

## 5. Benchmarks (spot checks)

| Condition | CPU load | RAM used | GPU util / mem | Notes |
|-----------|----------|----------|----------------|-------|
| BlueStacks idle (window up) | ~7% | ~16.6 / 31.1 GB | 0% / ~481 MiB | HD-Player ~2 GB WS |
| 60 s Stereo Mix capture + playback | (not fully instrumented mid-run) | — | — | Capture completed without drop warnings |

Do **not** extrapolate to N concurrent streams from these numbers.

---

## 6. Cross-platform OHush status

| Item | Status |
|------|--------|
| `requirements.txt` on Python 3.13 Windows | Installed OK |
| `qa_audio.analyze` | Works on local WAV |
| `hush.features.mono_features` | Works (smoke) |
| `recorder.py --live` Mac mute path | **Not run** (by design) |
| Frozen Universal scores / gold / holdouts | **Untouched** |
| Unit tests `tests/windows_lab` | **4 passed** |

---

## 7. Problems encountered

1. `winget` without `--source winget` failed (msstore certificate mismatch) — fixed by `--source winget`.
2. BlueStacks installer ~3.47 GB — long download; succeeded.
3. Realtek Speakers MMDevice **Unplugged** — cannot be set as Windows default; Stereo Mix useless for BlueStacks-on-HDMI.
4. BlueStacks ADB was off (`bst.enable_adb_access=0`) → `error: closed`. Enabled **local** ADB only; careless UTF-8 rewrite briefly broke BS (“Cannot start”); restored from backup and re-patched safely.
5. Public GCS sample MP4 URL returned AccessDenied in Chrome; used locally generated `test_public` MP4 instead.
6. sounddevice lacks WASAPI loopback in this build — used `soundcard` loopback of HDMI.

---

## 8. Decision

**`HOLD` for two-stream pilot — single-source Android closed loop is green.**

Proven today:

- One Windows research worker + ingest/analyze  
- One BlueStacks instance playing video with audio  
- 60 s lossless PCM via HDMI loopback → QA PASS → features smoke  

Not yet:

- Multi-source / multi-instance isolation (crosstalk)  
- Physical Realtek jack / dedicated virtual cable per worker  
- Any authorized premium / Streamers source  

### Next recommended experiment

1. Install a virtual audio device (e.g. VB-Cable) **if approved**, or plug headphones so Realtek Speakers leave Unplugged — for cleaner per-app routing.  
2. Compare OBS Application Audio Capture on `HD-Player` vs HDMI loopback (routing check; PCM archive stays loopback/Stereo Mix).  
3. Run **two** concurrent authorized `test_public` players only after isolation plan is chosen; measure crosstalk and CPU/GPU.  

**Still requires explicit approval:** Streamers / TiviMate wrapper APK, premium credentials, multi-instance farm, virtual-cable install.

---

## 9. Commands cheat sheet

```powershell
cd C:\Users\faceo\Projects\ohush
.\.venv\Scripts\Activate.ps1
$env:OHUSH_DATA_ROOT = "C:\OHushData"

python -m tools.windows_lab inventory
python -m tools.windows_lab health
python -m tools.windows_lab capture list-devices
python -m pytest tests\windows_lab -q
```
