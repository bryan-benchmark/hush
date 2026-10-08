"use client";

import { useCallback, useEffect, useState } from "react";
import {
  IDLE_STATUS,
  type AudioDevice,
  type LiveStatus,
  type OperatorMode,
} from "@/lib/live";

const LIVE_ORIGIN =
  process.env.NEXT_PUBLIC_HUSH_LIVE_ORIGIN ?? "http://127.0.0.1:8787";

export type DeviceLists = {
  inputs: AudioDevice[];
  outputs: AudioDevice[];
};

async function postJson(path: string, body: unknown) {
  const res = await fetch(`${LIVE_ORIGIN}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = (await res.json().catch(() => null)) as
    | { ok?: boolean; error?: string }
    | null;
  if (!res.ok || payload?.ok === false) {
    throw new Error(payload?.error ?? "Request failed");
  }
}

export function useLiveStatus() {
  const [status, setStatus] = useState<LiveStatus>(IDLE_STATUS);
  const [connected, setConnected] = useState(false);
  const [devices, setDevices] = useState<DeviceLists>({ inputs: [], outputs: [] });
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    let es: EventSource | null = null;
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (cancelled) return;
      es = new EventSource(`${LIVE_ORIGIN}/events`);

      es.onopen = () => {
        if (!cancelled) setConnected(true);
      };

      es.onmessage = (event) => {
        try {
          const next = JSON.parse(event.data) as LiveStatus;
          setStatus({ ...IDLE_STATUS, ...next, markers: next.markers ?? [] });
          setConnected(true);
        } catch {
          // ignore malformed frames
        }
      };

      es.onerror = () => {
        setConnected(false);
        es?.close();
        retryTimer = setTimeout(connect, 1500);
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      es?.close();
    };
  }, []);

  useEffect(() => {
    if (!connected || status.pipeline !== "live" || status.recording) return;
    let cancelled = false;

    const load = async () => {
      try {
        const res = await fetch(`${LIVE_ORIGIN}/devices`);
        const body = (await res.json()) as DeviceLists & { ok?: boolean };
        if (!cancelled) {
          setDevices({
            inputs: body.inputs ?? [],
            outputs: body.outputs ?? [],
          });
        }
      } catch {
        if (!cancelled) setDevices({ inputs: [], outputs: [] });
      }
    };

    void load();
    const timer = setInterval(() => void load(), 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [connected, status.pipeline, status.recording]);

  const run = useCallback(async (path: string, body: unknown) => {
    setActionError(null);
    try {
      await postJson(path, body);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Request failed");
    }
  }, []);

  const mark = useCallback(async (type: string, note?: string) => {
    await postJson("/mark", { type, note });
  }, []);

  const startSession = useCallback(
    (inputDevice: string, outputDevice: string) =>
      run("/session/start", {
        input_device: inputDevice,
        output_device: outputDevice,
      }),
    [run],
  );

  const stopSession = useCallback(() => run("/session/stop", {}), [run]);

  const setMode = useCallback(
    (mode: OperatorMode) => run("/mode", { mode }),
    [run],
  );

  const setGate = useCallback(
    (action: "mute" | "unmute" | "test_mute") => run("/gate", { action }),
    [run],
  );

  return {
    status,
    connected,
    devices,
    actionError,
    mark,
    startSession,
    stopSession,
    setMode,
    setGate,
  };
}
