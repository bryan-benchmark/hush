import { LabelApp } from "@/components/LabelApp";

export default async function LabelPage({
  searchParams,
}: {
  searchParams: Promise<{ task?: string; session?: string }>;
}) {
  const { task, session } = await searchParams;
  const mode = task === "all" ? undefined : task === "dataset" ? "dataset" : "replication";
  return <LabelApp task={mode} initialSession={session} />;
}
