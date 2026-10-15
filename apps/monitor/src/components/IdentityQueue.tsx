"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BrandMark } from "@/components/BrandMark";

type Choice = { id: string; label: string };
type Answer = { choice: string; text?: string };
type Clip = {
  id: string;
  start_seconds: number;
  wall: string;
  ask: string;
  note: string;
  choices: Choice[];
};

function elapsed(seconds: number) {
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function IdentityQueue() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const noteRef = useRef<HTMLInputElement | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  const [index, setIndex] = useState(0);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch("/api/identity")
      .then((res) => res.json())
      .then((data: { clips: Clip[]; answers: Record<string, Answer> }) => {
        setClips(data.clips);
        setAnswers(data.answers ?? {});
        const firstOpen = data.clips.findIndex((clip) => !data.answers?.[clip.id]);
        setIndex(firstOpen === -1 ? data.clips.length : firstOpen);
        if (firstOpen !== -1 && data.clips.some((clip, i) => i > firstOpen && data.answers?.[clip.id])) {
          setNotice("The last clip is already saved. This one still needs an answer.");
        }
      })
      .catch(() => setError("Could not load the clip queue."));
  }, []);

  const clip = clips[index];

  useEffect(() => {
    if (!clip) return;
    setDraft(answers[clip.id]?.text ?? "");
    // Restore the typed note only when the clip changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clip?.id]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !clip) return;
    audio.src = `/api/identity/audio?id=${encodeURIComponent(clip.id)}`;
    audio.play().catch(() => undefined);
  }, [clip]);

  const choose = useCallback(
    async (choice: string, text?: string) => {
      if (!clip || saving) return;
      const said = text?.trim() ?? "";
      if (choice === "said" && !said) return;
      setSaving(true);
      setError(null);
      try {
        const res = await fetch("/api/identity", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: clip.id, choice, ...(choice === "said" ? { text: said } : {}) }),
        });
        const data = (await res.json()) as { answers?: Record<string, Answer>; error?: string };
        if (!res.ok) throw new Error(data.error || "save failed");
        const nextAnswers = data.answers ?? {};
        setAnswers(nextAnswers);
        const later = clips.findIndex((row, i) => i > index && !nextAnswers[row.id]);
        if (later !== -1) {
          setNotice(null);
          setIndex(later);
        } else {
          const earlier = clips.findIndex((row) => !nextAnswers[row.id]);
          if (earlier !== -1) {
            setNotice("Saved. One clip from the start still needs an answer.");
            setIndex(earlier);
          } else {
            setNotice(null);
            setIndex(clips.length);
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "save failed");
      } finally {
        setSaving(false);
      }
    },
    [clip, clips, index, saving],
  );

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const typing = event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement;
      if (!clip || typing || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === " ") {
        event.preventDefault();
        const audio = audioRef.current;
        if (!audio) return;
        if (audio.paused) audio.play().catch(() => undefined);
        else audio.pause();
        return;
      }
      const n = Number(event.key);
      if (n >= 1 && n <= clip.choices.length) {
        event.preventDefault();
        choose(clip.choices[n - 1].id);
      } else if (n === clip.choices.length + 1) {
        event.preventDefault();
        noteRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [choose, clip]);

  const done = clips.length > 0 && clips.every((row) => answers[row.id]);
  const gap = clips.findIndex((row) => !answers[row.id]);
  const gapNote =
    clip && answers[clip.id] && gap !== -1 && gap !== index
      ? `This one is saved. Clip ${gap + 1} still needs an answer.`
      : null;

  return (
    <main className="shell identity-shell">
      <div className="atmosphere" aria-hidden="true" />
      <header className="top">
        <BrandMark />
        <p className="tag">Eighteen seconds each. Number keys pick a button. The last box is what it actually is. Space replays.</p>
      </header>

      {error ? <p className="device">{error}</p> : null}
      {gapNote || notice ? <p className="identity-note">{gapNote || notice}</p> : null}

      {!clips.length ? (
        <p className="device">Loading clips.</p>
      ) : done || index >= clips.length ? (
        <section className="blind-panel">
          <p className="identity-ask">Saved.</p>
          <p className="identity-note">That’s the queue. Your answers are saved. You can close this page.</p>
        </section>
      ) : (
        <section className="identity-card">
          <p className="device">
            {index + 1} of {clips.length}
            {answers[clip.id] ? " · answered" : ""}
            {answers[clip.id]?.text ? ` · ${answers[clip.id].text}` : ""}
          </p>
          <h1 className="identity-ask">{clip.ask}</h1>
          <p className="identity-note">{clip.note}</p>
          <p className="device">
            {clip.wall} · {elapsed(clip.start_seconds)} into the recording
          </p>
          <audio ref={audioRef} controls preload="auto" />
          <div className="identity-choices">
            {clip.choices.map((choice, i) => (
              <button
                key={choice.id}
                type="button"
                className={answers[clip.id]?.choice === choice.id ? "on" : ""}
                disabled={saving}
                onClick={() => choose(choice.id)}
              >
                {i + 1} · {choice.label}
              </button>
            ))}
          </div>
          <form
            className={answers[clip.id]?.choice === "said" ? "identity-said on" : "identity-said"}
            onSubmit={(event) => {
              event.preventDefault();
              choose("said", draft);
            }}
          >
            <label>
              {clip.choices.length + 1} · This is
              <input
                ref={noteRef}
                value={draft}
                disabled={saving}
                placeholder="Tell me what this is"
                onChange={(event) => setDraft(event.target.value)}
              />
            </label>
            <button
              type="submit"
              disabled={saving || !draft.trim() || answers[clip.id]?.text === draft.trim()}
            >
              {answers[clip.id]?.text === draft.trim() ? "Saved" : "Save"}
            </button>
          </form>
          <div className="identity-nav">
            <button type="button" disabled={index === 0} onClick={() => setIndex((n) => n - 1)}>
              Previous
            </button>
            <button
              type="button"
              disabled={index >= clips.length - 1}
              onClick={() => setIndex((n) => n + 1)}
            >
              Next
            </button>
          </div>
        </section>
      )}
    </main>
  );
}
