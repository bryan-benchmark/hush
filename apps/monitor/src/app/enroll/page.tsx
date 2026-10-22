"use client";

import { useEffect, useMemo, useState } from "react";

type Item = {
  id: string;
  session: string;
  network: string;
  date: string;
  play_start: number;
  duration: number;
  kind: string;
  group_minutes: number;
  hint: string;
};

type Label = { id: string; who: string; condition: string };

const NAMES = [
  "Mike Tirico",
  "Cris Collinsworth",
  "Joe Buck",
  "Troy Aikman",
  "Al Michaels",
  "Kirk Herbstreit",
  "Maria Taylor",
  "Clarissa Thompson",
  "Ryan Fitzpatrick",
  "Andrew Whitworth",
  "Richard Sherman",
  "Tony Gonzalez",
  "Chris Fowler",
  "Mike Tomlin",
];

const CONDITIONS: { id: string; label: string; key: string }[] = [
  { id: "clear", label: "Clear talk", key: "1" },
  { id: "laugh", label: "Laughing or joking", key: "2" },
  { id: "loud", label: "Speaking loud", key: "3" },
  { id: "crowd", label: "Over the crowd", key: "4" },
  { id: "song", label: "Over a song", key: "5" },
  { id: "news", label: "News", key: "6" },
  { id: "not_them", label: "Commercial", key: "7" },
  { id: "other_show", label: "Other show", key: "8" },
  { id: "skip", label: "Two voices", key: "9" },
];

const TARGET = 8;

export default function EnrollPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [labels, setLabels] = useState<Label[]>([]);
  const [index, setIndex] = useState(0);
  const [who, setWho] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch("/api/enroll")
      .then((res) => res.json())
      .then((data) => {
        const next = (data.items ?? []) as Item[];
        const prior = (data.labels ?? []) as Label[];
        setItems(next);
        setLabels(prior);
        const done = new Set(prior.map((row) => row.id));
        const first = next.findIndex((item) => !done.has(item.id));
        setIndex(first >= 0 ? first : 0);
        const lastNamed = [...prior].reverse().find((row) => row.who);
        if (lastNamed) setWho(lastNamed.who);
      })
      .catch(() => setError("Could not load the clips."));
  }, []);

  const item = items[index];
  const done = useMemo(() => new Set(labels.map((row) => row.id)), [labels]);
  const tally = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of labels) {
      if (!row.who || row.condition === "skip" || row.condition === "not_them" || row.condition === "news" || row.condition === "other_show") continue;
      const key = `${row.who} · ${row.condition}`;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [labels]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      const found = CONDITIONS.find((row) => row.key === event.key);
      if (found) {
        event.preventDefault();
        void save(found.id);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  async function save(condition: string) {
    if (!item || saving) return;
    if (!who.trim() && condition !== "not_them" && condition !== "news" && condition !== "other_show" && condition !== "skip") {
      setError("Pick the person first.");
      return;
    }
    setSaving(true);
    setError("");
    const sendWho = condition === "news" || condition === "other_show" || condition === "skip" || (condition === "not_them" && NAMES.includes(who.trim())) ? "" : who.trim();
    const res = await fetch("/api/enroll", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: item.id, who: sendWho, condition }),
    });
    setSaving(false);
    if (!res.ok) {
      setError("That was not saved.");
      return;
    }
    const row = { id: item.id, who: sendWho, condition };
    const nextLabels = [...labels.filter((saved) => saved.id !== item.id), row];
    setLabels(nextLabels);
    const nextDone = new Set(nextLabels.map((saved) => saved.id));
    const upcoming = items.findIndex((candidate, at) => at > index && !nextDone.has(candidate.id));
    setIndex(upcoming >= 0 ? upcoming : Math.min(items.length - 1, index + 1));
  }

  const src = item
    ? `/api/audio?session=${encodeURIComponent(item.session)}&mode=timeline&start=${item.play_start}&duration=${item.duration}`
    : "";

  return (
    <main className="shell identity-shell">
      <div className="atmosphere" aria-hidden="true" />
      <header className="top">
        <p className="tag">{items.length === 0 ? "Loading" : `${labels.length} saved · ${index + 1} of ${items.length}`}</p>
        <h1 className="identity-ask">Who is talking, and how?</h1>
      </header>
      {item ? (
        <section className="identity-card" style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
          <p className="tag">
            {item.network} · {item.date}
            {item.kind === "voice" ? ` · a long voice, ${item.group_minutes} min on this game` : " · inside a labeled commercial"}
          </p>
          <p className="identity-ask" style={{ fontSize: "1.35rem" }}>{item.hint}</p>
          <audio key={src} src={src} controls autoPlay style={{ width: "100%" }} />
          <p className="tag">3 seconds. Only mark it if that person is the only one talking the whole time.</p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
            {NAMES.map((name) => (
              <button
                key={name}
                type="button"
                className={who === name ? "tool-card action on" : "tool-card action"}
                onClick={() => setWho(name)}
              >
                <span className="tool-value" style={{ fontSize: "0.95rem" }}>{name}</span>
              </button>
            ))}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
            {CONDITIONS.map((row) => (
              <button key={row.id} type="button" className="tool-card action" disabled={saving} onClick={() => void save(row.id)}>
                <span className="tool-value" style={{ fontSize: "1rem" }}>{row.label}</span>
                <span className="tool-kicker">Key {row.key}</span>
              </button>
            ))}
          </div>
          {error ? <p className="tag">{error}</p> : null}
          <div>
            <p className="tag">Target is {TARGET} clips of each kind, for each person. These are the enrollment. A later game is the test.</p>
            {tally.length === 0 ? <p className="tag">Nothing saved yet.</p> : null}
            {tally.map(([key, count]) => (
              <p key={key} className="tag">
                {key}: {count}/{TARGET}
              </p>
            ))}
          </div>
          <div className="tool-row">
            <button type="button" className="tool-card action" onClick={() => setIndex(Math.max(0, index - 1))}>
              <span className="tool-value">Back</span>
            </button>
            <button type="button" className="tool-card action" onClick={() => setIndex(Math.min(items.length - 1, index + 1))}>
              <span className="tool-value">Next</span>
            </button>
          </div>
        </section>
      ) : (
        <p className="tag">{error || "No clips."}</p>
      )}
    </main>
  );
}
