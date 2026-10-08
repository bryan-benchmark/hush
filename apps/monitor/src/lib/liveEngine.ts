import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export const LIVE_ORIGIN = "http://127.0.0.1:8770";

function repoRoot() {
  const guesses = [join(process.cwd(), "..", ".."), join(process.cwd(), ".."), process.cwd()];
  for (const guess of guesses) {
    if (existsSync(join(guess, "ohush_live")) && existsSync(join(guess, ".venv", "bin", "python"))) {
      return guess;
    }
  }
  return guesses[0];
}

const REPO = repoRoot();
const PYTHON = join(REPO, ".venv", "bin", "python");
const PID_FILE = join(REPO, "ohush_live", "sessions", ".desk.pid");

declare global {
  // eslint-disable-next-line no-var
  var __ohushLiveChild: ChildProcess | undefined;
}

async function ping(): Promise<boolean> {
  try {
    const res = await fetch(`${LIVE_ORIGIN}/state`, { cache: "no-store" });
    return res.ok;
  } catch {
    return false;
  }
}

export async function ensureLive(): Promise<{ ok: boolean; error?: string }> {
  if (await ping()) return { ok: true };

  if (!existsSync(PYTHON)) {
    return { ok: false, error: "OHush is not ready on this Mac yet." };
  }

  if (global.__ohushLiveChild && !global.__ohushLiveChild.killed) {
    for (let i = 0; i < 40; i += 1) {
      await new Promise((r) => setTimeout(r, 250));
      if (await ping()) return { ok: true };
    }
  }

  const child = spawn(PYTHON, ["-m", "ohush_live.sports_daemon"], {
    cwd: REPO,
    detached: true,
    stdio: "ignore",
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });
  child.unref();
  global.__ohushLiveChild = child;

  try {
    mkdirSync(join(REPO, "ohush_live", "sessions"), { recursive: true });
    writeFileSync(PID_FILE, String(child.pid ?? ""), "utf8");
  } catch {
    // pid file is optional
  }

  for (let i = 0; i < 80; i += 1) {
    await new Promise((r) => setTimeout(r, 250));
    if (await ping()) return { ok: true };
    if (child.exitCode != null) {
      return { ok: false, error: "Could not start listening on this Mac." };
    }
  }
  return { ok: false, error: "Still warming up. Try again in a moment." };
}

export async function liveFetch(path: string, init?: RequestInit) {
  const res = await fetch(`${LIVE_ORIGIN}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const text = await res.text();
  let json: unknown = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = { error: text || "bad response" };
  }
  return { res, json };
}
