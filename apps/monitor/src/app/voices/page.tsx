"use client";

import { useEffect, useRef, useState } from "react";
import { WaveTransport } from "@/components/WaveTransport";

type Item = {
  id: string;
  session: string;
  play_start: number;
  duration: number;
  rank: number;
  heard_seconds: number;
  session_label: string;
  date_label: string;
  program: string;
  network: string;
  ad_voice: boolean;
  ad_share: number;
  n_in_session: number;
  ask?: string;
  suggestions?: string[];
};
type Person = { start_s: number; end_s: number; what: string; who: string };
type Named = { id: string; who: string; what: string; people: Person[]; session?: string; play_start?: number | null };

function labelFor(item: Item, rows: Named[]) {
  const byClip = rows.find(
    (row) => row.session === item.session && row.play_start != null && Math.abs(row.play_start - item.play_start) < 0.05,
  );
  if (byClip) return byClip;
  return rows.find((row) => row.id === item.id && (!row.session || row.session === item.session));
}

export default function VoicesPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [named, setNamed] = useState<Named[]>([]);
  const [index, setIndex] = useState(0);
  const [said, setSaid] = useState("");
  const [who, setWho] = useState("");
  const [people, setPeople] = useState<Person[]>([]);
  const [draft, setDraft] = useState<{ start_s: number; end_s: number } | null>(null);
  const [markIn, setMarkIn] = useState<number | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [error, setError] = useState("");
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const decodedRef = useRef<AudioBuffer | null>(null);
  const dragRef = useRef<{ start: number } | null>(null);
  const namedRef = useRef(named);
  const peopleRef = useRef(people);
  const draftRef = useRef(draft);
  const markInRef = useRef(markIn);
  const saidRef = useRef(said);
  const whoRef = useRef(who);
  const editingRef = useRef(editing);
  const itemRef = useRef<Item | undefined>(undefined);
  const editGen = useRef(0);
  const fieldsRef = useRef<HTMLDivElement | null>(null);
  namedRef.current = named;
  peopleRef.current = people;
  draftRef.current = draft;
  markInRef.current = markIn;
  saidRef.current = said;
  whoRef.current = who;
  editingRef.current = editing;
  itemRef.current = items[index];

  useEffect(() => {
    fetch("/api/voices")
      .then((res) => res.json())
      .then((data) => {
        const next = (data.items ?? []) as Item[];
        const prior = (data.named ?? []) as Named[];
        setItems(next);
        setNamed(prior);
        const first = next.findIndex((item) => !labelFor(item, prior));
        setIndex(first >= 0 ? first : 0);
      })
      .catch(() => setError("Could not load the voices."));
  }, []);

  const item = items[index];

  useEffect(() => {
    if (!item) return;
    const last = labelFor(item, namedRef.current);
    setSaid("");
    setWho("");
    if (last?.people?.length) setPeople(last.people);
    else if (last?.who) {
      const preset = last.what === "Broadcaster" || last.what === "Not a broadcaster";
      setPeople([{ start_s: 0, end_s: item.duration, what: preset ? "" : last.what, who: last.who }]);
    } else setPeople([]);
    setDraft(null);
    setMarkIn(null);
    setEditing(null);
    decodedRef.current = null;
  }, [item]);

  useEffect(() => {
    if (markIn == null) return;
    let frame = 0;
    const tick = () => {
      const start = markInRef.current;
      const audio = audioRef.current;
      if (start != null && audio) {
        const duration = item?.duration ?? audio.duration ?? 8;
        const at = Math.round(Math.min(duration, Math.max(0, audio.currentTime)) * 100) / 100;
        if (at > start) setDraft({ start_s: start, end_s: at });
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [markIn, item]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const decoded = decodedRef.current;
    if (!canvas || !decoded) return;
    drawVoice(canvas, decoded, people, draft);
  }, [people, draft]);

  function timeAt(clientX: number, canvas: HTMLCanvasElement) {
    const rect = canvas.getBoundingClientRect();
    const fraction = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    const duration = item?.duration ?? 8;
    return Math.round(fraction * duration * 100) / 100;
  }

  function onPointerDown(event: React.PointerEvent<HTMLCanvasElement>) {
    leaveBox();
    const at = timeAt(event.clientX, event.currentTarget);
    dragRef.current = { start: at };
    markInRef.current = null;
    setMarkIn(null);
    event.currentTarget.setPointerCapture(event.pointerId);
    setEditing(null);
    setDraft({ start_s: at, end_s: at });
  }

  function onPointerMove(event: React.PointerEvent<HTMLCanvasElement>) {
    if (!dragRef.current) return;
    const at = timeAt(event.clientX, event.currentTarget);
    const start = dragRef.current.start;
    setDraft({ start_s: Math.min(start, at), end_s: Math.max(start, at) });
  }

  function onPointerUp(event: React.PointerEvent<HTMLCanvasElement>) {
    if (!dragRef.current) return;
    const at = timeAt(event.clientX, event.currentTarget);
    const start = dragRef.current.start;
    dragRef.current = null;
    const left = Math.min(start, at);
    const right = Math.max(start, at);
    if (right - left < 0.2) {
      const hit = people.findIndex((person) => at >= person.start_s - 0.05 && at <= person.end_s + 0.05);
      if (hit >= 0) {
        setEditing(hit);
        setDraft({ start_s: people[hit].start_s, end_s: people[hit].end_s });
        setSaid(people[hit].what);
        setWho(people[hit].who);
      } else {
        setDraft(null);
      }
      return;
    }
    setEditing(null);
    setDraft({ start_s: left, end_s: right });
    setSaid("");
    setWho("");
  }

  async function save(nextPeople: Person[], gen: number, clip: Item) {
    setError("");
    const res = await fetch("/api/voices", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: clip.id, people: nextPeople }),
    });
    if (!res.ok) {
      setError("That was not saved.");
      return;
    }
    const ordered = [...nextPeople].sort((a, b) => a.start_s - b.start_s);
    const row: Named = {
      id: clip.id,
      session: clip.session,
      play_start: clip.play_start,
      who: ordered.map((person) => person.who).filter(Boolean).join(" · "),
      what: ordered.map((person) => person.what || person.who).join(" · "),
      people: ordered,
    };
    const nextNamed = [
      ...namedRef.current.filter((saved) => saved.session !== clip.session || Math.abs((saved.play_start ?? -1) - clip.play_start) >= 0.05),
      row,
    ];
    namedRef.current = nextNamed;
    setNamed(nextNamed);
    if (itemRef.current?.id === clip.id) {
      peopleRef.current = ordered;
      setPeople(ordered);
      if (editGen.current === gen) {
        draftRef.current = null;
        editingRef.current = null;
        saidRef.current = "";
        whoRef.current = "";
        setDraft(null);
        setEditing(null);
        setSaid("");
        setWho("");
      }
    }
  }

  function commitPerson() {
    const desc = saidRef.current.trim();
    const name = whoRef.current.trim();
    const clip = itemRef.current;
    if (!clip || markInRef.current != null || (!desc && !name)) return;
    const current = draftRef.current;
    const duration = clip.duration > 0 ? clip.duration : 8;
    const span = current && current.end_s - current.start_s >= 0.2 ? current : { start_s: 0, end_s: duration };
    const person = { start_s: span.start_s, end_s: span.end_s, what: desc, who: name };
    const editingNow = editingRef.current;
    const existing = editingNow != null ? peopleRef.current[editingNow] : null;
    if (
      existing &&
      existing.what === person.what &&
      existing.who === person.who &&
      existing.start_s === person.start_s &&
      existing.end_s === person.end_s
    ) {
      return;
    }
    const next = [...peopleRef.current];
    if (editingNow != null && editingNow < next.length) next[editingNow] = person;
    else next.push(person);
    peopleRef.current = next;
    saidRef.current = "";
    whoRef.current = "";
    draftRef.current = null;
    editingRef.current = null;
    setPeople(next);
    setSaid("");
    setWho("");
    setDraft(null);
    setEditing(null);
    void save(next, editGen.current, clip);
  }

  function leaveBox() {
    commitPerson();
    editGen.current += 1;
  }

  function onFieldsBlur(event: React.FocusEvent<HTMLDivElement>) {
    const next = event.relatedTarget;
    if (next instanceof Node && event.currentTarget.contains(next)) return;
    if (next instanceof HTMLElement && next.dataset.skipSave === "1") return;
    commitPerson();
  }

  function playhead() {
    const audio = audioRef.current;
    const duration = item?.duration ?? 8;
    const at = audio && Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
    return Math.round(Math.min(duration, Math.max(0, at)) * 100) / 100;
  }

  function markWhole() {
    leaveBox();
    const duration = item?.duration && item.duration > 0 ? item.duration : audioRef.current?.duration || 8;
    const end = Math.round(duration * 100) / 100;
    markInRef.current = null;
    setMarkIn(null);
    setEditing(null);
    setDraft({ start_s: 0, end_s: end });
    setError("");
    const audio = audioRef.current;
    if (audio) {
      audio.currentTime = 0;
      void audio.play();
    }
  }

  function markStart() {
    leaveBox();
    const at = playhead();
    markInRef.current = at;
    setMarkIn(at);
    setEditing(null);
    setDraft({ start_s: at, end_s: at });
    setError("");
    const audio = audioRef.current;
    if (audio?.paused) void audio.play();
  }

  function markEnd() {
    const start = markInRef.current;
    if (start == null) return;
    const at = playhead();
    if (at - start < 0.15) {
      setError("Keep listening, then tap End.");
      return;
    }
    markInRef.current = null;
    setMarkIn(null);
    setDraft({ start_s: start, end_s: at });
    setError("");
  }

  const whole =
    draft != null && draft.start_s <= 0.05 && item != null && draft.end_s >= Math.max(0.2, item.duration) - 0.05;
  const boxLabel =
    markIn != null ? `Started at ${markIn.toFixed(1)}s` : draft && draft.end_s - draft.start_s >= 0.2 ? `${draft.start_s.toFixed(1)}–${draft.end_s.toFixed(1)}s` : "";

  return (
    <main className="shell identity-shell">
      <div className="atmosphere" aria-hidden="true" />
      <header className="top">
        <p className="tag">{items.length === 0 ? "Loading" : `${index + 1} of ${items.length}`}</p>
        <h1 className="identity-ask">What is this?</h1>
      </header>
      {item ? (
        <section className="identity-card" style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
          <p className="tag">{item.date_label}</p>
          <p className="identity-ask" style={{ fontSize: "1.6rem" }}>
            {item.network} · {item.program}
          </p>
          <WaveTransport
            src={`/api/audio?session=${encodeURIComponent(item.session)}&mode=timeline&start=${item.play_start}&duration=${item.duration}`}
            audioRef={audioRef}
            canvasRef={canvasRef}
            loop={markIn == null && draft && draft.end_s - draft.start_s >= 0.2 ? draft : markIn == null ? { start_s: 0, end_s: item.duration } : null}
            loopByDefault
            onDecoded={(buffer) => {
              decodedRef.current = buffer;
              const canvas = canvasRef.current;
              if (canvas) drawVoice(canvas, buffer, peopleRef.current, draftRef.current);
            }}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
          />
          <div className="tool-row marks">
            {markIn == null ? (
              <button type="button" className="tool-card action" onClick={markStart}>
                <span className="tool-value">Start</span>
                <span className="tool-kicker">From the playhead</span>
              </button>
            ) : (
              <button type="button" className="tool-card action end" onClick={markEnd}>
                <span className="tool-value">End</span>
                <span className="tool-kicker">Close this box</span>
              </button>
            )}
            <button type="button" className={whole ? "tool-card action on" : "tool-card action"} onClick={markWhole}>
              <span className="tool-value">Whole</span>
              <span className="tool-kicker">The entire clip</span>
            </button>
            {boxLabel ? (
              <div className="tool-card read">
                <span className="tool-value">{markIn != null ? markIn.toFixed(1) : `${draft?.start_s.toFixed(1)}–${draft?.end_s.toFixed(1)}`}</span>
                <span className="tool-kicker">{markIn != null ? "Started" : "Marked"}</span>
              </div>
            ) : (
              <div className="tool-card read">
                <span className="tool-value">—</span>
                <span className="tool-kicker">No box yet</span>
              </div>
            )}
          </div>
          <div ref={fieldsRef} onBlur={onFieldsBlur} style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
            <label className="identity-said" style={{ display: "flex", flexDirection: "column" }}>
              What it is
              <input
                value={said}
                placeholder="Intro, outro, an ad, the booth"
                onChange={(event) => {
                  saidRef.current = event.target.value;
                  setSaid(event.target.value);
                }}
              />
            </label>
            <label className="identity-said" style={{ display: "flex", flexDirection: "column" }}>
              Who, if it’s a person
              <input
                value={who}
                placeholder="Leave blank if it isn’t a person"
                onChange={(event) => {
                  whoRef.current = event.target.value;
                  setWho(event.target.value);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    commitPerson();
                  }
                }}
              />
            </label>
          </div>
          {people.length ? (
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: "0.35rem" }}>
              {people.map((person, personIndex) => (
                <li key={`${personIndex}-${person.start_s}-${person.end_s}`} style={{ display: "flex", gap: "0.6rem", alignItems: "center" }}>
                  <button
                    type="button"
                    data-skip-save="1"
                    onClick={() => {
                      leaveBox();
                      editingRef.current = personIndex;
                      const nextDraft = { start_s: person.start_s, end_s: person.end_s };
                      draftRef.current = nextDraft;
                      saidRef.current = person.what;
                      whoRef.current = person.who;
                      setEditing(personIndex);
                      setDraft(nextDraft);
                      setSaid(person.what);
                      setWho(person.who);
                      if (audioRef.current) {
                        audioRef.current.currentTime = person.start_s;
                        void audioRef.current.play();
                      }
                    }}
                  >
                    {person.start_s.toFixed(1)}–{person.end_s.toFixed(1)}s
                  </button>
                  <span style={{ flex: 1 }}>{[person.what, person.who].filter(Boolean).join(" · ")}</span>
                  <button
                    type="button"
                    data-skip-save="1"
                    onClick={() => {
                      editGen.current += 1;
                      const clip = itemRef.current;
                      if (!clip) return;
                      void save(
                        peopleRef.current.filter((_, i) => i !== personIndex),
                        editGen.current,
                        clip,
                      );
                    }}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          <div className="identity-nav">
            <button
              type="button"
              disabled={index === 0}
              onClick={() => {
                leaveBox();
                setIndex((n) => n - 1);
              }}
            >
              Previous
            </button>
            <button
              type="button"
              disabled={index >= items.length - 1}
              onClick={() => {
                leaveBox();
                setIndex((n) => n + 1);
              }}
            >
              Next
            </button>
          </div>
        </section>
      ) : (
        <p>No voices in the queue.</p>
      )}
      {error ? <p className="device">{error}</p> : null}
    </main>
  );
}

function drawVoice(
  canvas: HTMLCanvasElement,
  audio: AudioBuffer,
  people: Person[],
  draft: { start_s: number; end_s: number } | null,
) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const data = audio.getChannelData(0);
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#1a1024";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#d7c6f5";
  ctx.beginPath();
  const step = Math.max(1, Math.floor(data.length / width));
  for (let x = 0; x < width; x += 1) {
    let min = 1;
    let max = -1;
    const start = x * step;
    for (let i = 0; i < step; i += 1) {
      const sample = data[start + i] ?? 0;
      if (sample < min) min = sample;
      if (sample > max) max = sample;
    }
    ctx.moveTo(x, (1 - max) * 0.5 * height);
    ctx.lineTo(x, (1 - min) * 0.5 * height);
  }
  ctx.stroke();
  const xAt = (seconds: number) => Math.round((seconds / audio.duration) * canvas.width);
  for (const person of people) {
    const left = xAt(person.start_s);
    const right = xAt(person.end_s);
    ctx.fillStyle = "#f2c14e55";
    ctx.fillRect(left, 18, Math.max(2, right - left), canvas.height - 28);
    ctx.fillStyle = "#ffffff";
    ctx.font = "12px ui-monospace, monospace";
    if (right - left > 36) ctx.fillText(person.what || person.who, left + 4, 36);
  }
  if (draft && draft.end_s > draft.start_s) {
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.strokeRect(xAt(draft.start_s), 14, Math.max(2, xAt(draft.end_s) - xAt(draft.start_s)), canvas.height - 22);
    ctx.lineWidth = 1;
  }
}
