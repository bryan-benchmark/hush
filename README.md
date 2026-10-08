# OHush

Research mode: prove TV audio can detect ad transitions before building the product app.

```text
TV → optical → USB → Mac → Python WAV capture
                         ↘ localhost monitor (Next.js)
```

## Stack (this repo, now)

| Layer | Tech |
|-------|------|
| Capture / research | Python 3.13 + `sounddevice` |
| Live watch UI | TypeScript + React + Next.js + Tailwind |
| Product later | Firebase / GCP / OpenAI — **not built yet** |

## Setup

### Python recorder

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

List devices / record:

```bash
python recorder.py --list
python recorder.py --device 0 --seconds 30
caffeinate -i python recorder.py --device 0
```

While recording, the live API listens on `http://127.0.0.1:8787`.

### Local monitor

```bash
cd apps/monitor
npm install
npm run dev
```

Open [http://localhost:3010](http://localhost:3010).

You'll see the live peak meter, session info, and Ad / Content / Note buttons.

### Live pass-through

```bash
python recorder.py --list
python recorder.py --live
```

Choose the USB optical input and the headphone output in the monitor.
PASS-THROUGH plays stereo without muting. MANUAL exposes Mute, Unmute, and
Test mute 2 sec. AUTO is visible and cannot mute. The frozen detector is not
in this path.

To start from the terminal instead of the device menu:

```bash
python recorder.py --live --input-device "USB Audio Device" --output-device "External Headphones"
```

Names must match exactly, including trailing spaces. An index works too.
If the chosen device is gone, OHush refuses to fall back to the default mic or speakers.

## Labels

| Input | Meaning |
|-------|---------|
| `a` / Ad start | Commercial break begins |
| `c` / Content start | Show resumes |
| `n …` / Note | Freeform note |

Sessions save under `recordings/YYYY-MM-DD/hush_.../`.
