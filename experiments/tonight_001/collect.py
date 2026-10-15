"""Build tonight's CC0 listening queue. Does not touch the gate."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import unquote
from urllib.request import Request, urlopen

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
PAGES = CACHE / "pages"
MEDIA = HERE / "media"
CATALOG = HERE / "catalog.json"
TARGET_RMS = 0.10
PEAK_CAP = 0.90
MAX_TRACKS = 200
MAX_SECONDS = 12 * 60
MAX_CASUAL_BYTES = 18_000_000
MAX_PRIORITY_BYTES = 95_000_000

PRIORITY_PAGES = [
    "https://opengameart.org/content/free-rhythm-game-music-pack-1",
    "https://opengameart.org/content/free-rhythm-game-music-pack-2",
    "https://opengameart.org/content/funk-collection",
    "https://opengameart.org/content/slampe-synthwave-house",
    "https://opengameart.org/content/barriers",
    "https://opengameart.org/content/detour",
    "https://opengameart.org/content/midnight-cruiser",
    "https://opengameart.org/content/elevate-instrument-tracks",
    "https://opengameart.org/content/t-t-free-cyberpunk-pack",
    "https://opengameart.org/content/pack-of-loopable-game-music",
    "https://opengameart.org/content/music-pack-1",
]

AUDIO = {".ogg", ".mp3", ".wav", ".flac"}
GROUPS = (
    ("Electronic", ("house", "techno", "trance", "electro", "dnb", "drum-and-bass", "drum and bass", "cyber", "synth", "edm", "stomper", "ascend")),
    ("Funk and jazz", ("funk", "disco", "jazz", "bossa", "swing", "blues", "fusion")),
    ("Ambient", ("ambient", "calm", "piano", "relax", "lofi", "lo-fi", "chill", "atmosphere", "rain")),
    ("Chiptune", ("chiptune", "8-bit", "8bit", "nes", "rpg", "jrpg", "midi")),
    ("Rock", ("metal", "rock", "guitar")),
)


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    PAGES.mkdir(parents=True, exist_ok=True)
    MEDIA.mkdir(parents=True, exist_ok=True)
    items = _local_entries()
    lock = threading.Lock()
    counter = [len(items)]
    seen_urls: set[str] = set()
    _write(items, complete=False)
    print(f"local {len(items)} tracks ready")

    pool = ThreadPoolExecutor(max_workers=3)
    pending = []

    def submit(job: dict) -> None:
        if job["url"] in seen_urls:
            return
        seen_urls.add(job["url"])
        pending.append(pool.submit(_consume, job, items, lock, counter))

    for page in PRIORITY_PAGES:
        try:
            jobs = _page_jobs(page, priority=True)
        except Exception as exc:
            print("page skip", page, exc)
            continue
        for job in jobs:
            submit(job)
        print(f"priority {page.rsplit('/', 1)[-1]} -> {len(jobs)} files")

    links = _search_pages()
    print(f"search found {len(links)} pages")
    with ThreadPoolExecutor(max_workers=6) as fetchers:
        futures = {fetchers.submit(_page_jobs, page, False): page for page in links}
        done = 0
        for fut in as_completed(futures):
            done += 1
            if len(items) >= MAX_TRACKS:
                break
            try:
                jobs = fut.result()
            except Exception as exc:
                print("page skip", futures[fut], exc)
                continue
            for job in jobs:
                submit(job)
            if done % 20 == 0:
                print(f"fetched {done}/{len(links)} pages, {len(items)} ready, {len(seen_urls)} queued")

    print(f"working through {len(pending)} files")
    for fut in as_completed(pending):
        try:
            fut.result()
        except Exception as exc:
            print("job fail", exc)
    pool.shutdown(wait=True)
    _write(items, complete=True)
    print("catalog", len(items), CATALOG)
    polish()


def _consume(job: dict, items: list[dict], lock: threading.Lock, counter: list[int]) -> None:
    with lock:
        if len(items) >= MAX_TRACKS:
            return
    path = _download(job)
    if path is None:
        return
    for audio_path in _explode(path):
        with lock:
            if len(items) >= MAX_TRACKS:
                return
            index = counter[0]
            counter[0] += 1
        entry = _prepare(job, audio_path, index)
        if entry is None:
            continue
        with lock:
            if any(existing["sha256"] == entry["sha256"] for existing in items):
                (MEDIA / Path(entry["file"]).name).unlink(missing_ok=True)
                continue
            if any(
                existing["title"].casefold() == entry["title"].casefold()
                and existing["creator"].casefold() == entry["creator"].casefold()
                for existing in items
            ):
                (MEDIA / Path(entry["file"]).name).unlink(missing_ok=True)
                continue
            items.append(entry)
            _write(items, complete=False)
            print(f"{len(items):3d}  {entry['group']:16}  {entry['title']}")


def _local_entries() -> list[dict]:
    rows = []
    silence = MEDIA / "silence.wav"
    if not silence.exists() or silence.is_symlink():
        if silence.is_symlink() or silence.exists():
            silence.unlink()
        sf.write(str(silence), np.zeros((48000, 2)), 48000, subtype="PCM_16")
    rows.append(_link_entry("silence", "Silence", "OHush", "Baseline", silence, "local"))
    mapping = [
        ("warm_air", "Warm Air", "OHush sketch", "Ambient", HERE.parent / "sound_identity_001/renders/warm_air.wav"),
        ("velvet_beat", "Velvet Beat", "OHush sketch", "Electronic", HERE.parent / "sound_identity_001/renders/velvet_beat.wav"),
        ("light_shuffle", "Light Shuffle", "OHush sketch", "Electronic", HERE.parent / "sound_identity_001/renders/light_shuffle.wav"),
        ("slow_current", "Slow Current", "OHush sketch", "Ambient", HERE.parent / "sound_identity_001/renders/slow_current.wav"),
        ("ascend", "Ascend", "tricksntraps", "Electronic", HERE.parent / "groove_varied_001/prepared/ascend.wav"),
        ("starting_over", "Starting Over", "tricksntraps", "Electronic", HERE.parent / "groove_varied_001/prepared/starting_over.wav"),
        ("lost_utopia", "Lost Utopia", "tricksntraps", "Electronic", HERE.parent / "groove_varied_001/prepared/lost_utopia.wav"),
        ("wednesday_night", "Chill Lofi Inspired", "qubodup", "Ambient", ROOT / "ohush_live/vibes/processed/wednesday_night.wav"),
        ("lofi_again", "Lofi Again", "omfgdude", "Ambient", ROOT / "ohush_live/vibes/processed/wednesday_night_lofi_again.wav"),
        ("cup_of_tea", "A Cup of Tea", "TAD", "Ambient", ROOT / "ohush_live/vibes/processed/wednesday_night_cup_of_tea.wav"),
        ("friends_over", "Funked Up", "Joth", "Funk and jazz", ROOT / "ohush_live/vibes/processed/friends_over.wav"),
        ("friends_disco", "Funky Disco Beats", "Fupi", "Funk and jazz", ROOT / "ohush_live/vibes/processed/friends_over_disco.wav"),
        ("empty_stretch", "Empty Stretch", "Zane Little Music", "Funk and jazz", ROOT / "ohush_live/vibes/processed/friends_over_empty_stretch.wav"),
        ("cocktail", "Coffee House Bump", "OatCog", "Funk and jazz", ROOT / "ohush_live/vibes/processed/cocktail_lounge.wav"),
        ("bossa", "Bossa Nova", "Joth", "Funk and jazz", ROOT / "ohush_live/vibes/processed/cocktail_lounge_bossa.wav"),
        ("rainy_night", "Soft Rain Loop", "_lynks", "Ambient", ROOT / "ohush_live/vibes/processed/rainy_night.wav"),
        ("stadium", "Stadium crowd", "FlatHill", "Ambient", ROOT / "ohush_live/vibes/processed/stadium_vibe.wav"),
    ]
    for item_id, title, creator, group, src in mapping:
        if src.is_file():
            rows.append(_link_entry(item_id, title, creator, group, src, "local"))
    return [row for row in rows if row is not None]


def _link_entry(item_id: str, title: str, creator: str, group: str, src: Path, source_page: str) -> dict | None:
    dest = MEDIA / f"{item_id}{src.suffix.lower()}"
    if src.resolve() != dest.resolve():
        if dest.is_symlink() or dest.exists():
            dest.unlink()
        dest.symlink_to(src.resolve())
    target = dest if dest.exists() else src
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    info = sf.info(str(target))
    if creator == "OHush sketch":
        license_name = "sketch"
    elif creator == "OHush":
        license_name = "baseline"
    else:
        license_name = "CC0"
    return {
        "id": item_id,
        "title": title,
        "creator": creator,
        "group": group,
        "license": license_name,
        "source_page": source_page,
        "file": f"media/{dest.name}",
        "duration_s": round(info.duration, 1),
        "sha256": digest,
    }


def _search_pages() -> list[str]:
    found = []
    for page in range(0, 8):
        url = (
            "https://opengameart.org/art-search-advanced?field_art_type_tid[]=12"
            "&field_art_licenses_tid[]=4&sort_by=count&sort_order=DESC&items_per_page=48"
            f"&page={page}"
        )
        html = _get(url)
        for href in re.findall(r'href="(/content/[^"#?]+)"', html):
            if href.startswith("/content/") and href.count("/") == 2 and "art-search" not in href:
                full = "https://opengameart.org" + href
                if full not in found and full not in PRIORITY_PAGES:
                    found.append(full)
        print(f"search page {page} -> {len(found)} content pages")
    return found


def _page_jobs(page: str, priority: bool = False) -> list[dict]:
    html = _get(page)
    field = _license_field(html)
    if "CC0" not in field:
        return []
    if any(token in field for token in ("CC-BY", "CC-BY-SA", "GPL", "OGA-BY")):
        return []
    title = _text(html, "title") or page.rsplit("/", 1)[-1]
    title = re.sub(r"\s*\|\s*OpenGameArt.org\s*$", "", title).strip()
    creator = _creator(html)
    files = []
    for href in re.findall(r'href="(https://opengameart.org/sites/default/files/[^"]+)"', html):
        suffix = Path(href.split("?")[0]).suffix.lower()
        if suffix in AUDIO or suffix == ".zip":
            files.append(href)
    chosen = _prefer(files, zip_limit=24 if priority else 8)
    group = _group(title + " " + page)
    multi = len(chosen) > 1 or any(href.lower().endswith(".zip") for href in chosen)
    return [
        {
            "url": href,
            "title": title,
            "creator": creator,
            "group": group,
            "source_page": page,
            "multi": multi,
            "priority": priority,
        }
        for href in chosen
    ]


def _license_field(html: str) -> str:
    match = re.search(
        r'field-name-field-art-licenses.*?</div></div></div>',
        html,
        re.S,
    )
    return match.group(0) if match else ""


def _creator(html: str) -> str:
    match = re.search(r'field-name-author.*?<a[^>]*>([^<]+)</a>', html, re.S)
    if not match:
        match = re.search(r"Author:\s*</div>\s*<div[^>]*>\s*<a[^>]*>([^<]+)", html, re.S)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else "unknown"


def _text(html: str, tag: str) -> str:
    match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", html, re.S)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def _prefer(urls: list[str], zip_limit: int) -> list[str]:
    by_stem: dict[str, str] = {}
    zips = []
    rank = {".mp3": 0, ".ogg": 1, ".flac": 2, ".wav": 3}
    for url in urls:
        suffix = Path(url.split("?")[0]).suffix.lower()
        if suffix == ".zip":
            zips.append(url)
            continue
        stem = Path(url.split("?")[0]).stem.lower()
        current = by_stem.get(stem)
        if current is None or rank[suffix] < rank[Path(current.split("?")[0]).suffix.lower()]:
            by_stem[stem] = url
    chosen = list(by_stem.values())
    if not chosen:
        chosen = zips[:zip_limit]
    return chosen


def _group(text: str) -> str:
    lowered = text.lower()
    for name, words in GROUPS:
        if any(word in lowered for word in words):
            return name
    return "Other"


def _download(job: dict) -> Path | None:
    url = job["url"]
    name = Path(url.split("?")[0]).name
    dest = CACHE / name
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    partial = dest.with_suffix(dest.suffix + ".part")
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=90) as response:
            length = int(response.headers.get("Content-Length") or 0)
            suffix = dest.suffix.lower()
            ceiling = MAX_PRIORITY_BYTES if job.get("priority") else MAX_CASUAL_BYTES
            if length > ceiling:
                print("skip large", name, length)
                return None
            if not job.get("priority") and suffix == ".wav" and length == 0:
                return None
            written = 0
            with partial.open("wb") as handle:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > ceiling:
                        print("skip large", name, written)
                        partial.unlink(missing_ok=True)
                        return None
                    handle.write(chunk)
    except Exception as exc:
        partial.unlink(missing_ok=True)
        print("download fail", url, exc)
        return None
    if written < 1000:
        partial.unlink(missing_ok=True)
        return None
    partial.replace(dest)
    return dest


def _explode(path: Path) -> list[Path]:
    if path.suffix.lower() != ".zip":
        return [path]
    out = CACHE / path.stem
    out.mkdir(parents=True, exist_ok=True)
    found = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir() or info.file_size > MAX_PRIORITY_BYTES:
                continue
            suffix = Path(info.filename).suffix.lower()
            if suffix not in AUDIO:
                continue
            target = out / Path(info.filename).name
            if not target.exists():
                target.write_bytes(archive.read(info))
            found.append(target)
    return found


def _prepare(job: dict, path: Path, index: int) -> dict | None:
    try:
        audio, rate = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception as exc:
        print("decode skip", path.name, exc)
        return None
    if audio.shape[0] < rate or audio.shape[0] > MAX_SECONDS * rate:
        return None
    if audio.shape[1] == 1:
        audio = np.column_stack([audio[:, 0], audio[:, 0]])
    else:
        audio = audio[:, :2]
    rms = float(np.sqrt(np.mean(np.square(audio))))
    if rms < 1e-4:
        return None
    scaled = audio * (TARGET_RMS / rms)
    peak = float(np.max(np.abs(scaled)))
    if peak > PEAK_CAP:
        scaled *= PEAK_CAP / peak
    item_id = f"{index:03d}_{_slug(Path(path).stem)}"
    wav = CACHE / f"{item_id}.wav"
    m4a = MEDIA / f"{item_id}.m4a"
    sf.write(str(wav), scaled, rate, subtype="PCM_16")
    result = subprocess.run(
        ["/usr/bin/afconvert", "-f", "m4af", "-d", "aac", "-b", "160000", str(wav), str(m4a)],
        capture_output=True,
        text=True,
    )
    wav.unlink(missing_ok=True)
    if result.returncode != 0 or not m4a.exists():
        print("encode skip", path.name, result.stderr[-200:])
        return None
    title = _clean_title(re.sub(r"^\d+[\s._-]*", "", Path(path).stem))
    if job.get("title") and not job.get("multi"):
        title = _clean_title(job["title"])
    group = _group(f"{title} {job['source_page']}")
    if group == "Other":
        group = job["group"]
    return {
        "id": item_id,
        "title": title or path.stem,
        "creator": job["creator"],
        "group": group,
        "license": "CC0",
        "source_page": job["source_page"],
        "file": f"media/{m4a.name}",
        "duration_s": round(scaled.shape[0] / rate, 1),
        "sha256": hashlib.sha256(m4a.read_bytes()).hexdigest(),
    }


def _clean_title(text: str) -> str:
    title = unquote(text).replace("_", " ")
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"\.mp3$", "", title, flags=re.I)
    title = re.sub(r"\s+0$", "", title)
    return title


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "track"


def _write(items: list[dict], complete: bool) -> None:
    CATALOG.write_text(
        json.dumps({"experiment": "TONIGHT_001", "complete": complete, "tracks": items}, indent=2) + "\n"
    )


def _get(url: str) -> str:
    key = hashlib.sha256(url.encode()).hexdigest()[:20]
    dest = PAGES / f"{key}.html"
    if dest.exists() and dest.stat().st_size > 400:
        return dest.read_text(encoding="utf-8", errors="replace")
    text = _get_bytes(url).decode("utf-8", "replace")
    dest.write_text(text, encoding="utf-8")
    return text


def _get_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=40) as response:
        return response.read()


TAG_GROUPS = (
    ("Funk and jazz", ("funk", "jazz", "bossa", "swing", "blues", "disco", "fusion")),
    ("Ambient", ("ambient", "ambience", "calm", "piano", "relax", "lofi", "lo-fi", "chill", "atmosphere", "rain", "meditation")),
    ("Chiptune", ("chiptune", "8-bit", "8bit", "nes")),
    ("Rock", ("metal", "rock", "guitar", "punk")),
    ("Cinematic", ("orchestral", "cinematic", "epic", "trailer", "battle", "action")),
    ("Electronic", ("house", "techno", "trance", "electro", "dnb", "drum-and-bass", "drum and bass", "cyber", "synth", "edm", "dubstep", "industrial", "electronic")),
)
STEM_TITLES = {
    "bass", "drums", "drumloop", "melody", "bell", "chords", "sfx",
    "loop1", "loop2", "loop3", "happypart", "happypart2", "tensepart",
}


def polish() -> None:
    """Clean titles and group tracks from the page tags already on disk."""
    if not CATALOG.exists():
        return
    catalog = json.loads(CATALOG.read_text())
    for track in catalog.get("tracks", []):
        track["title"] = _clean_title(track["title"])
        if track.get("id") == "silence":
            info = sf.info(str(MEDIA / "silence.wav"))
            track["duration_s"] = round(info.duration, 1)
            track["license"] = "baseline"
        if track.get("source_page") == "local":
            continue
        if track["title"].casefold() in STEM_TITLES:
            track["group"] = "Loops and stems"
            continue
        tags = _page_tags(track.get("source_page") or "")
        blob = " ".join([track["title"], track.get("source_page") or "", *tags]).lower()
        for name, words in TAG_GROUPS:
            if any(re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", blob) for word in words):
                track["group"] = name
                break
    kept = []
    seen = set()
    for track in catalog.get("tracks", []):
        key = (track["title"].casefold(), track["creator"].casefold())
        if key in seen:
            continue
        seen.add(key)
        kept.append(track)
    catalog["tracks"] = kept
    CATALOG.write_text(json.dumps(catalog, indent=2) + "\n")
    print("polished", len(catalog.get("tracks", [])), "complete", catalog.get("complete"))


def _page_tags(page: str) -> list[str]:
    if not page.startswith("http"):
        return []
    key = hashlib.sha256(page.encode()).hexdigest()[:20]
    dest = PAGES / f"{key}.html"
    if not dest.exists():
        return []
    html = dest.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"field-name-field-art-tags.*?</div></div></div>", html, re.S)
    if not match:
        return []
    return [re.sub(r"\s+", " ", tag).strip() for tag in re.findall(r">([^<]+)</a>", match.group(0))]


if __name__ == "__main__":
    main()
