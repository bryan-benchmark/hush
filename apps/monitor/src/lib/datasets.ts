import fs from "fs";
import path from "path";
import { repoRoot } from "@/lib/labeling";

export const SEAL = "HOLDOUT_V1";

type Role = "dev" | "holdout" | "acquisition_fixture" | "ignore";

type Datasets = {
  default_role?: Role;
  seal?: string;
  sessions?: Record<string, { role?: Role; reason?: string }>;
};

let cached: Datasets | null = null;

export function loadDatasets(): Datasets {
  if (cached) return cached;
  const p = path.join(repoRoot(), "experiments/gold/DATASETS_V1.json");
  cached = JSON.parse(fs.readFileSync(p, "utf8")) as Datasets;
  return cached;
}

export function roleOf(session: string): Role {
  const data = loadDatasets();
  return data.sessions?.[session]?.role ?? data.default_role ?? "dev";
}

export function roleReason(session: string): string | null {
  return loadDatasets().sessions?.[session]?.reason ?? null;
}

export function denial(
  session: string,
  unseal: string | null,
): { error: string; role: string; session: string } | null {
  if (labelVisible(session, unseal, false)) return null;
  const role = roleOf(session);
  if (role === "holdout") {
    return {
      error: `${session} is a sealed holdout. Open it only with unseal=${SEAL}.`,
      role,
      session,
    };
  }
  return {
    error: `${session} is ${role} and is outside the dev labeling set.`,
    role,
    session,
  };
}
export function labelVisible(
  session: string,
  unseal: string | null,
  includeFixtures: boolean,
): boolean {
  const role = roleOf(session);
  if (role === "dev") return true;
  if (role === "holdout") return unseal === SEAL;
  if (role === "acquisition_fixture") return includeFixtures;
  return false;
}
