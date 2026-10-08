"use client";

import { FormEvent, useState } from "react";

type Props = {
  disabled: boolean;
  onMark: (type: string, note?: string) => Promise<void>;
};

export function MarkControls({ disabled, onMark }: Props) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(type: string, value?: string) {
    setBusy(true);
    setError(null);
    try {
      await onMark(type, value);
      if (type === "note") setNote("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Mark failed");
    } finally {
      setBusy(false);
    }
  }

  function onNoteSubmit(e: FormEvent) {
    e.preventDefault();
    if (!note.trim()) return;
    void run("note", note.trim());
  }

  const locked = disabled || busy;

  return (
    <section className="marks">
      <div className="mark-row">
        <button
          type="button"
          className="mark-btn ad"
          disabled={locked}
          onClick={() => void run("ad_start")}
        >
          Ad start
          <kbd>A</kbd>
        </button>
        <button
          type="button"
          className="mark-btn content"
          disabled={locked}
          onClick={() => void run("content_start")}
        >
          Content start
          <kbd>C</kbd>
        </button>
      </div>

      <form className="note-form" onSubmit={onNoteSubmit}>
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Note — network promo, weird transition…"
          disabled={locked}
        />
        <button type="submit" disabled={locked || !note.trim()}>
          Note
        </button>
      </form>

      {error ? <p className="mark-error">{error}</p> : null}
    </section>
  );
}
