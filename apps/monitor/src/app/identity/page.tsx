"use client";

import { useEffect, useState } from "react";
import { IdentityQueue } from "@/components/IdentityQueue";

export default function IdentityPage() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    setReady(true);
  }, []);
  if (!ready) return <div className="shell" suppressHydrationWarning aria-busy="true" />;
  return <IdentityQueue />;
}
