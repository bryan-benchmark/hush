import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
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
  // eslint-disable-next-line no-var
  var __ohushLiveStarting: Promise<{ ok: boolean; error?: string }> | undefined;
}

async function ping(): Promise<boolean> {
  try {
    const res = await fetch(`${LIVE_ORIGIN}/state`, { cache: "no-store", signal: AbortSignal.timeout(800) });
    return res.ok;
  } catch {
    return false;
  }
}

function readPid(): number | null {
  try {
    const raw = readFileSync(PID_FILE, "utf8").trim();
    const pid = Number(raw);
    return Number.isFinite(pid) && pid > 0 ? pid : null;
  } catch {
    return null;
  }
}

function pidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function waitForLive(ms: number): Promise<boolean> {
  const steps = Math.ceil(ms / 250);
  for (let i = 0; i < steps; i += 1) {
    if (await ping()) return true;
    await new Promise((r) => setTimeout(r, 250));
  }
  return false;
}

function childRunning(child: ChildProcess | undefined): boolean {
  if (!child || child.killed) return false;
  if (child.exitCode != null || child.signalCode != null) return false;
  const pid = child.pid;
  return typeof pid === "number" && pidAlive(pid);
}

async function startLiveOnce(): Promise<{ ok: boolean; error?: string }> {
  if (await ping()) return { ok: true };

  if (!existsSync(PYTHON)) {
    return { ok: false, error: "OHush is not ready on this Mac yet." };
  }

  // Another engine is still warming (or live). Wait — never kill it.
  // Killing used to wipe an in-memory session the user never Stopped.
  const existing = readPid();
  if (existing && pidAlive(existing)) {
    if (await waitForLive(90_000)) return { ok: true };
    if (await ping()) return { ok: true };
    // Pid file can go stale after a crash; only then fall through to spawn.
    if (pidAlive(existing)) {
      return { ok: false, error: "Still warming up. Try again in a moment." };
    }
  }

  if (childRunning(global.__ohushLiveChild)) {
    if (await waitForLive(90_000)) return { ok: true };
    if (await ping()) return { ok: true };
    if (childRunning(global.__ohushLiveChild)) {
      return { ok: false, error: "Still warming up. Try again in a moment." };
    }
  }
  global.__ohushLiveChild = undefined;

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

  // make_beds + first PortAudio open can exceed a minute on a loaded Mac.
  if (await waitForLive(180_000)) return { ok: true };
  if (await ping()) return { ok: true };
  if (child.exitCode != null || !childRunning(child)) {
    global.__ohushLiveChild = undefined;
    return { ok: false, error: "Could not start listening on this Mac." };
  }
  return { ok: false, error: "Still warming up. Try again in a moment." };
}

function externalEngine(): boolean {
  const mode = (process.env.OHUSH_ENGINE || "").trim().toLowerCase();
  return mode === "external" || mode === "1" || mode === "true";
}

export async function ensureLive(): Promise<{ ok: boolean; error?: string }> {
  if (await ping()) return { ok: true };
  // Game-night / desk mode: UI hot-reloads; engine is started separately and
  // must never be spawned or killed from Next.
  if (externalEngine()) {
    return {
      ok: false,
      error: "Start the engine first: ./scripts/desk engine",
    };
  }
  // Collapse concurrent boot/state/device calls into one spawn attempt.
  if (!global.__ohushLiveStarting) {
    global.__ohushLiveStarting = startLiveOnce().finally(() => {
      global.__ohushLiveStarting = undefined;
    });
  }
  return global.__ohushLiveStarting;
}

export async function liveFetch(path: string, init?: RequestInit) {
  let res: Response;
  try {
    res = await fetch(`${LIVE_ORIGIN}${path}`, {
      ...init,
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    return {
      res: new Response(null, { status: 503 }),
      json: { ok: false, error: "The audio engine is not running." },
    };
  }
  const text = await res.text();
  let json: unknown = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = { error: text || "bad response" };
  }
  return { res, json };
}
