import { LabelApp } from "@/components/LabelApp";

export default async function LabelPage({
  searchParams,
}: {
  searchParams: Promise<{ task?: string }>;
}) {
  const { task } = await searchParams;
  return <LabelApp task={task === "all" ? undefined : "replication"} />;
}
