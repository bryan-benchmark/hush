# Streamers controls

Atomic operations for `ar.tvplayer.tv` 5.1.0 on BlueStacks `Nougat32`. Login is [`SALVATION_BLUESTACKS.md`](SALVATION_BLUESTACKS.md). This file is what to do after the home screen is up, and how to record it.

Every tap target comes from a fresh UI dump. A coordinate from an earlier dump is stale. The guide reflows, and the player chrome hides itself.

The password stays in `C:\OHushData\farm\salvation_login.json`. Do not print it, and do not put it in a log, a screenshot name, or git.

## Machines and limits

This PC is a Ryzen 7 7800X3D, 32 GB RAM, RTX 4070 Super. One instance is assigned 2 cores and 4 GB and uses about 2.4 GB. With that instance running, free RAM was about 3.5 GB.

Two instances is the number that can record cleanly, after the heavy apps are closed and each instance has its own virtual audio cable. Three is `max_concurrent_streamers` in the instance registry. A third instance on this box will lag. The app already lags on one.

Each clone is about 6 GB. The C: drive has the space. Disk is not the limit.

One Windows playback device is one recording. The live default is `Speakers (MZ-631M USB Speaker Bar)`. Its loopback heard the emulator. The monitor loopback `1 - MG248` was silent, because the instance is not playing through the monitor. A second instance on the same speaker bar mixes both programs into one file. Give the second instance its own cable and set that cable as its `loopback_device` before any parallel take.

`salvation record-add` stores a channel name and a clock time. It does not open the channel and it does not start ffmpeg.

`session start` without `--no-channel-apply` runs the channel recipe. The example recipe sends keyevent 82 and a note that says to replace the steps. That menu key was never confirmed in Streamers. Do not apply an example recipe.

`session start --no-channel-apply` still starts the player with `launchApp`. That can leave the channel you just opened. For a take of a channel that is already on screen, use the probe atoms below. Use `session start` only after a recipe of confirmed steps opens that same channel.

Farm sessions default to `--media av`: full archival WAV plus one still per second under `stills/`. That is the labeling archive. Pass `--media av_full` only when you need retained `video_*.mp4`. Contested boundaries go to `archive edge-clip`, not a second full tape. Probe atoms O–P below stay short device/window takes for confirming the picture; they are not the long-term library.

## Atoms

Serial for `Nougat32` is `127.0.0.1:5555`. Screen is 1600x900. Window title is `BlueStacks App Player`. ADB is `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe`. The lab prefers `C:\Program Files\BlueStacks_nxt\HD-Adb.exe` when that file exists. Commands below say `adb` for the one that is connected.

### A. Connect

```powershell
adb connect 127.0.0.1:5555
adb devices -l
```

The line must be `127.0.0.1:5555    device`. `offline` means the instance is still booting. A client/server version mismatch kills the daemon. Connect again after it restarts, then read the focus before the next tap.

### B. Focus

```powershell
adb -s 127.0.0.1:5555 shell dumpsys window | Select-String "mCurrentFocus"
```

Logged-in Streamers is `ar.tvplayer.tv/.ui.MainActivity`. The wizard is `PlaylistWizardActivity`. The splash is `com.andyhax.haxsplash.LaunchActivity`.

### C. Dump the UI

```powershell
adb -s 127.0.0.1:5555 shell uiautomator dump /sdcard/ohush_ui.xml
adb -s 127.0.0.1:5555 pull /sdcard/ohush_ui.xml $env:TEMP\ohush_ui.xml
adb -s 127.0.0.1:5555 shell rm /sdcard/ohush_ui.xml
```

Read the texts and the clickable bounds from that file. Tap the center of the bounds you just read. Delete the temp file when you are done with it. A dump during a transition is a different screen from the dump a second later.

### D. Screenshot

PowerShell `>` corrupts `screencap`. Write the bytes from Python:

```powershell
.\.venv\Scripts\python.exe -c @"
import subprocess
from io import BytesIO
from pathlib import Path
from PIL import Image
adb = r'$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe'
raw = subprocess.check_output([adb, '-s', '127.0.0.1:5555', 'exec-out', 'screencap', '-p'])
Path(r'$env:TEMP\ohush_screen.png').write_bytes(raw)
im = Image.open(BytesIO(raw))
im.thumbnail((900, 520))
im.convert('RGB').save(r'$env:TEMP\ohush_screen_sm.jpg', quality=70)
print(im.size)
"@
```

Read the small JPEG. The full PNG is 1600x900 and too large to inspect in one read.

### E. Tap

```powershell
adb -s 127.0.0.1:5555 shell input tap X Y
```

`X` and `Y` are the center of a bounds box from atom C, taken in this minute. Then dump or screenshot again. A tap that does not change the focus, the selected row, or the preview did not hit the control you named.

### F. Keys that are confirmed

| Key | Code | What it did |
|---|---|---|
| Back | 4 | Player returned to the guide |
| D-pad center | 23 | The selected guide row opened full screen |
| Enter | 66 | Committed text in the login wizard |

Send one, then look. Key 82 is in the example channel recipe and was not tried here. Do not send it to open a channel.

### G. Type

Login only. The steps are in [`SALVATION_BLUESTACKS.md`](SALVATION_BLUESTACKS.md). After Enter on Username, dump again and tap Password at the new bounds. The old Password point hits the option row under it.

### H. Name the screen

Use the focus from atom B and the texts from atom C.

| Texts or focus | Screen |
|---|---|
| `add playlist`, and no Username | Welcome. Run the login doc from step 4 |
| `Salvation` and `Cancel`, no Username | Service list. Tap Salvation |
| `Username`, `Password`, `Next` | Credentials |
| `Playlist name` and `Done`, no Username | Playlist name. The first Done can sit still. Tap Done again |
| `MainActivity` and numbered rows, or a preview plus a grid | Guide. This is the logged-in home |
| `MainActivity` plus `TV guide`, `History`, `Clear`, or `FHD` | Player, chrome showing |
| Full-frame picture and no guide grid | Player, chrome hidden. Tap the middle of the picture once if you need the chrome |

`screen_kind` in `tools/windows_lab/salvation.py` returns `home` for any `MainActivity`. The guide and the player are both `home`. Tell them apart with the grid and the `FHD` line.

### I. Read what is playing

On the guide, the preview is the top-left picture. The section name is at the top right (`PPV SECTION`, `HOLIDAY SECTION`). The selected row is the highlighted one. Its label is the channel.

On the player, show the chrome (tap the middle once) and read the number and the title next to the clock line. A confirmed reading was `5` and `PPV EVENT 03 | 8:00 PM ET - WWE MONDAY NIGHT RAW`, with badges `FHD`, `30 FPS`, `STEREO`.

`No information` on a grid cell is an empty program listing. It is not a failed login.

A full-frame card that says `Back in a Moment` and `Premium Content Loading` is a real playback state. The picture behind the words can change when the channel changes. The card is still a slate. Say so when you report the take.

### J. Select a guide row

Dump. Find the `FrameLayout` whose text is the channel you want. The grid on this screen was `GridView` covering `[0,390][1600,900]`. Rows were 65 px tall, starting at y=390. Section headers are rows too. Their labels look like `-------HOLIDAY SECTION-------` and `-------PPV SECTION-------`. A header row changes the section. It does not start a program.

Tap the row's name cell, or its program cell. The highlight moves, and the preview follows. Confirm with a screenshot before the next action.

### K. Open full screen

Select the row (atom J). Then:

```powershell
adb -s 127.0.0.1:5555 shell input keyevent 23
```

Confirm with a screenshot. A second tap on the program cell, a tap on the preview, and a double-tap all left the guide up. The preview's clickable box was `[27,20][560,320]`. Tapping its center did not open the player.

### L. Leave the player

```powershell
adb -s 127.0.0.1:5555 shell input keyevent 4
```

The guide comes back with the last channel still selected. The `TV guide` label on the player chrome did not navigate when tapped. Use Back.

### M. Choose the loopback

```powershell
.\.venv\Scripts\python.exe -c "import soundcard as sc; print(sc.default_speaker().name)"
```

Record the loopback whose name contains the default speaker and whose `isloopback` is true. Skip the one whose name starts with `Microphone`. On this PC that is the MZ-631M speaker bar. If a take's peak is 0, the sound is on a different device. Try the other loopback once. A second zero means the channel is silent, not that the recorder missed.

### N. Audio only

The player or the guide preview must already be on the channel. Six to ten seconds is a probe. Write under `C:\OHushData\work\capture\`, never under the repo.

```powershell
.\.venv\Scripts\python.exe -c @"
import sys, numpy as np, soundcard as sc, soundfile as sf
mic = next(m for m in sc.all_microphones(include_loopback=True)
           if m.isloopback and 'MZ-631M' in m.name and not m.name.startswith('Microphone'))
data = mic.record(samplerate=48000, numframes=48000*6, channels=2)
sf.write(r'C:\OHushData\work\capture\bluestacks_probe\audio_only.wav', data, 48000)
print('peak', float(np.max(np.abs(data))), 'rms', float(np.sqrt(np.mean(data**2))))
"@
```

A live probe of the loading card peaked near 0.30 and the rms was about 0.09. Treat a peak under 0.01 as quiet. Listen, or look at the waveform, before calling a long file good.

### O. Video only

Device `screenrecord` grabs the Android picture. A window on top of BlueStacks does not get into this file.

```powershell
adb -s 127.0.0.1:5555 shell screenrecord --time-limit 6 --bit-rate 4000000 /sdcard/ohush_probe.mp4
adb -s 127.0.0.1:5555 pull /sdcard/ohush_probe.mp4 C:\OHushData\work\capture\bluestacks_probe\device_video.mp4
adb -s 127.0.0.1:5555 shell rm /sdcard/ohush_probe.mp4
```

`--time-limit` on this Android build is a few minutes at most. Pull the frame at one second and look at it. The confirmed file was 1600x900, h264, about 6 seconds, and showed the loading card full frame.

### P. Picture and sound together

Start atom N and atom O in the same second, for the same duration, while the channel is already full screen. Mux afterward:

```powershell
ffmpeg -y -i C:\OHushData\work\capture\bluestacks_probe\device_video.mp4 -i C:\OHushData\work\capture\bluestacks_probe\audio_only.wav -c:v copy -c:a aac -shortest C:\OHushData\work\capture\bluestacks_probe\video_and_audio.mp4
```

The confirmed mux was 6 seconds, 1600x900, stereo AAC. The two files start together only if both commands start together. A mux of a later audio file onto an earlier video is a different take.

### Q0. Resize / tile BlueStacks on the PC display

When windows are off-screen, tiny, or stacked, tile them over the primary work area (taskbar excluded). Cursor, open-model desk agents, and humans use the same command — do not drag by eye.

```powershell
python -m tools.windows_lab windows list
python -m tools.windows_lab windows layout --mode auto
python -m tools.windows_lab windows layout --mode fill --instances Nougat32 --focus Nougat32
python -m tools.windows_lab windows layout --mode split --instances Nougat32 Nougat32_1
python -m tools.windows_lab windows layout --mode grid
# If a Qt HD-Player ignores MoveWindow (report.stuck non-empty):
python -m tools.windows_lab windows layout --mode auto --relaunch-stuck
```

`auto` = 1→fill, 2→side-by-side, 3+→grid. Windows are fitted to **16:9** inside each cell (BlueStacks surface). Even pixel sizes (gdigrab-safe). ADB farm stills do **not** require the window on screen; layout is for operator sight and computer-use aiming. `--relaunch-stuck` stops/patches `gl_win_*`/relaunches windows that refuse live moves.

### Q. Desktop window vs device stills

Farm `session start --media av` stills now come from **ADB** (`screenrecord` → 1 fps JPEGs, `screencap` fallback). That is the Android picture: **minimize, resize, or cover the BlueStacks window and the frames stay clean.** Audio is still the Windows loopback.

`gdigrab` of `title=BlueStacks App Player` is only the fallback when ADB fails. It records the rectangle of that window, including whatever is painted on top. A grab taken while Cursor covered the right half contained Cursor. Prefer ADB/atom O unless you are debugging the desktop path.

The window's width can be odd. libx264 then fails with `width not divisible by 2`. Add `-vf scale=trunc(iw/2)*2:trunc(ih/2)*2`. Keep `title=BlueStacks App Player` as one argument. A split on the space makes ffmpeg look for a window named `BlueStacks`.

DirectShow on this PC lists the speaker-bar microphone and does not list the speaker loopback. Pair `gdigrab` with atom N. Do not expect ffmpeg's dshow audio to hear the emulator.

### R. Judge the take

Read one frame and the peak.

- Frame shows a program, peak is live: the channel recorded.
- Frame shows `Premium Content Loading`, peak is live: the slate recorded, with its own sound. The game was not on.
- Frame shows the guide: the player was not full screen during the take.
- Frame shows another Windows window: the grab was atom Q and BlueStacks was covered.
- Peak is 0 on the speaker-bar loopback: try the other loopback once (atom M). A second zero is a silent channel.

## Use cases

Each one is the atoms in order. Stop when a check fails and dump again. Do not continue from a guessed screen.

### 1. Is it logged in?

A, B, C, H. `MainActivity` and a guide or a player means yes. Welcome means run the login doc. `python -m tools.windows_lab salvation status --instance Nougat32` agrees when `screen` is `home`.

### 2. Log in

[`SALVATION_BLUESTACKS.md`](SALVATION_BLUESTACKS.md), or `python -m tools.windows_lab salvation login --instance Nougat32`. The command stops when the screen is already `home`.

### 3. What is on?

H, then I, then D. Report the section, the channel number, the title, and whether the frame is a program or the loading card.

### 4. Change channel

L if a player is up. C. J on a row that is not a section header. D to see the preview change. K. I again. The number or the title has to differ from the channel you left. A preview that changes picture while the loading card stays up is still a channel change.

### 5. Change section

L if needed. J on a header row (`HOLIDAY SECTION`, `PPV SECTION`). The top-right section name changes. Then use case 4 inside that section.

### 6. Hear a channel

Use case 4, then N. Report peak and rms.

### 7. See a channel

Use case 4, then O. Look at a frame before calling it a program.

### 8. Record both

Use case 4, then P.

### 9. Probe before a long file

Use case 8 for six seconds. Keep the long file only when the frame and the peak match the channel you meant. A slate probe means the long file would be the slate too.

### 10. Park on the guide

L. Confirm the grid is back. The selected row keeps playing in the preview, so the speaker can stay live.

### 11. A second instance

Shut the source instance down. Clone it in HD-MultiInstanceManager. Boot the clone, `python -m tools.windows_lab instances discover`, then `salvation status` on the clone name. The clone boots logged in because the disk was copied. Assign a different `loopback_device` before it plays at the same time as `Nougat32`. Two playing logins on one account have not been tried. The provider can drop one of them.

A playlist refresh on one clone does not refresh the other. Refresh each, or refresh one, shut it down, and clone again.

### 12. Schedule a specific guide recording (and audit it)

Use the guide search card, not a vague channel name. Prefer a saved shortcut.

```powershell
# From a saved shortcut (sports: team/show search)
python -m tools.windows_lab schedule from-shortcut --id TNF_PRIME --at 2026-11-19T19:30:00-05:00 --minutes 270 --weekly

# From a fresh guide search (optionally open+confirm now)
python -m tools.windows_lab schedule from-guide --query Commanders --channel TNF_PRIME --title-contains "NFL 01" --at 2026-11-19T19:30:00-05:00 --minutes 270 --weekly

# Is the schedule actually working? (tape stills/audio/process)
python -m tools.windows_lab schedule audit
# Board: C:\OHushData\indexes\SCHEDULE_AUDIT.md
```

`OHushCaptureFarmRunDue` runs `run-due` then `audit --active-only` every minute. A healthy live take shows verdict `healthy_live` with growing stills.

`salvation record-add` only stores a reminder clock — it does not open or capture:

```powershell
python -m tools.windows_lab salvation record-add --instance Nougat32 --channel CHANNEL --at 2026-11-16T20:00:00-05:00 --minutes 180
```

### 13. The app is lagging

Wait. Dump. If the dump's texts and the screenshot disagree, wait and dump again. A tap aimed at the previous screen hits the next one. Dropping the instance below 60 fps is a settings change and is not required for these atoms. Adding a third instance makes the lag worse.

Farm record watches this: sessions get a `streamers_lag` score (window loss, still shortfall, early end). `farm status` → `operations.1_record.streamers_lag`. Capture re-resolves the BlueStacks window between still chunks and waits before failing a chunk. Cap concurrent at two.

### 14. The channel is a slate or a bad listing

Record what is on the screen, and say that in the report. Switch with use case 4 and probe again. Some rows in the same section were `No event available` while the neighbor carried a program title. The loading card can still play audio.

### 15. Sections, search, and a stale playlist

The signed-in playlist is named `ohush`. Its own screen reports 19688 TV channels, 34310 movies, and 9430 shows. TV is filed in 170 groups. The names are in `C:\OHushData\indexes\streamers_tv_groups.json`. The Hush ranking of those groups is `C:\OHushData\indexes\STREAMERS_LINEUP.md`.

Long-press a guide row (swipe with the finger held on the channel name). The menu has Search and Settings. Tap the word, not a remembered point.

Settings, then Playlists, then the `ohush` row, then Manage groups, then TV. That list is the section index. Scroll it. Leave every ON switch as it is. Do not tap Hide all groups.

Search takes call letters. `ESPN` returns the ESPN channels. `CBS` and `NBC` return local stations. `ABC` and `FOX` hit movie titles first, so use the groups `US ABC SECTION` and `US FOX SECTION` for those.

**Any US DMA, on purpose:** every ABC/CBS/NBC/FOX affiliate is in the matching `US * SECTION`. That is a first-class dataset source — rotate big markets (WNYW/KTTV/WFLD…), tag `network`+`market`+`call_letters`, and prefer West Coast when ET dayparts are done. Do not park forever on one Alaska/West Virginia filler.

```powershell
python -m tools.windows_lab open local --network FOX --market "New York"
```

### Autonomous recover (no Cursor turn)

When stuck (empty MAX-UK, decode error, BlueStacks home, login, overlay), do **not** burn chat tokens — run the local state machine (fresh dump → classify → fix → verify):

```powershell
python -m tools.windows_lab open snap --instance Nougat32_1
python -m tools.windows_lab open recover --instance Nougat32_1 --goal guide
python -m tools.windows_lab open recover --instance Nougat32_1 --goal picture
```

`open search` / `open local` already call `ensure_ready_for_open` first. Log: `C:\OHushData\indexes\streamers_recover.jsonl`.

### Atomic nav (teach the open model)

Human-shaped moves, one dump at a time. Trajectories + frames:

```powershell
python -m tools.windows_lab nav flag-bad
python -m tools.windows_lab nav teach --route ESPN_US --instance Nougat32_1 --save-as ESPN_US
python -m tools.windows_lab nav atlas
```

- Linear nets: All channels → section / search → **reject** `(MAX SPORTS) ESPN` for national ads.
- Events: still `open search` team/show → `NFL 01` card.
- Logs: `C:\OHushData\indexes\streamers_nav.jsonl` · board: `NAV_ATLAS.md` · routes: `streamers_nav_routes.json`.

### Frame watch (periodic stills → decisions)

Capture stills (1 fps) are not just for labeling — score them to decide playing / black / stuck / login, then recover:

```powershell
python -m tools.windows_lab frame-watch analyze --image C:\OHushData\work\streamers_recover\foo.png --vision
python -m tools.windows_lab frame-watch session --session-dir C:\OHushData\authorized_sources\<session>
python -m tools.windows_lab frame-watch watch --instance Nougat32
```

Heuristic (PIL) always; **Ollama `moondream`** (open, local) when uncertain. `OHUSH_VISION=0` disables the model. Log: `C:\OHushData\indexes\frame_watch.jsonl`. Farm loop runs frame-watch each tick.

### Desk cron (orchestrate without Cursor)

One Task Scheduler job runs the full subroutine chain every N minutes: schedule due jobs → per-instance frame-watch → login/recover/tune → start on-air record when healthy.

```powershell
python -m tools.windows_lab desk tick
python -m tools.windows_lab desk install-task --register --minutes 10
```

Board: `C:\OHushData\indexes\DESK.md` · log: `desk_orchestrator.jsonl` · task name: `OHushDeskOrchestrator`. Cap streams with `OHUSH_DESK_MAX_STREAMS` (default 2).

**Checks & balances (anti-stampede):**
- Single-flight lock `farm/desk_tick.lock` (O_EXCL create + PID/heartbeat; stale reclaim)
- Task Scheduler `MultipleInstances IgnoreNew` — overlapping triggers no-op
- Preflight: free RAM / disk / HD-Player cap / *other* desk pythons (self excluded)
- Per-tick budgets: max recoveries, max vision calls, max streams
- No new record while instance capture lock held; abort mid-tick if RAM/HD caps trip
- Desk never launches another desk tick — only frame-watch / recover / record children
- `python -m tools.windows_lab desk preflight` to inspect gates

**Sports (normal operation):** search the show name, team name, or event name first — not the AMAZON SPORTS group of empty `AMZN##` slots. Example confirmed 12 Nov 2026: search `Commanders` → Channels card `NFL 01 | 8:15 PM ET - New York Giants vs Washington Commanders` → keyevent 23 → player `NFL A` / `542` / FHD. Save every path that works:

```powershell
python -m tools.windows_lab open search --query Commanders --title-contains "NFL 01" --save-as TNF_PRIME
python -m tools.windows_lab open play --id TNF_PRIME
python -m tools.windows_lab open list
```

Shortcuts live in `C:\OHushData\indexes\streamers_open_shortcuts.json`. After open, record with `session start --no-channel-apply`.

Update all playlists is on the Playlists page. It was not run during the census. Run it only when a refresh is the task, then wait until the guide is back before the next tap.

### 16. ADB dumped a stale daemon

Atom A again. Then B. Continue only after the focus is Streamers.

## Confirmed once, on 10 Nov 2026

These bounds matched `Nougat32` at 1600x900 during that pass. Read atom C again before using them.

- Guide grid from y=390, row step 65.
- Preview `[27,20][560,320]`, clickable, tap does not open the player.
- Center key opens the selected row.
- Back returns to the guide.
- Player chrome, when showing, listed `TV guide`, `History`, `Clear`, a seek bar, and `FHD` / `30 FPS` / `STEREO`.
- Taps on `TV guide` and `History` left the same player up.
- `Clear` was not pressed.
- Channels opened that hour were on the loading card. Channel 5's title was a WWE listing. The picture was the card.

## Files from that pass

`C:\OHushData\work\capture\bluestacks_probe\`

- `audio_only.wav` — speaker-bar loopback, six seconds
- `device_video.mp4` — device screen, six seconds
- `video_and_audio.mp4` — those two muxed

## Saving a channel recipe later

After use case 4 succeeds for one named channel, write the steps that worked: wait for `MainActivity`, Back if the player is up, tap the row whose text contains that channel name, keyevent 23, then a check that the player title contains the name. Store taps as labels you re-find, not as old x,y pairs. Until that file exists, do not `channel apply` and do not `session start` for that channel.

For sports, prefer the search shortcut catalog over a brittle recipe:

```powershell
python -m tools.windows_lab open save --id SHORTCUT_ID --query "TeamOrShow" --title "exact Channels card text" --number 542 --group "NFL A" --notes "what worked"
```

### 17. Sports: search show/team, open, save shortcut

1. Know the show or the two team names (TNF → search either team).
2. `python -m tools.windows_lab open search --query <team> --save-as <ID>` (or dump → Search → type → pick live Channels card → keyevent 23).
3. Prefer `NFL 01` / network titles with a kickoff time. Skip `No event available` and French duplicates unless that is the ask.
4. Confirm player chrome (group, number, FHD) and loopback peak.
5. `open save` / `--save-as` so the next agent can `open play --id <ID>` without rediscovering.
6. `session start --no-channel-apply --channel <ID>`.
