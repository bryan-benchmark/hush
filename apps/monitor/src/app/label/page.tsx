import { LabelApp } from "@/components/LabelApp";

export default async function LabelPage({
  searchParams,
}: {
  searchParams: Promise<{ task?: string }>;
}) {
  const { task } = await searchParams;
  const mode = task === "all" ? undefined : task === "dataset" ? "dataset" : "replication";
  return <LabelApp task={mode} />;
}
