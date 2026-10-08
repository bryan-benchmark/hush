"use client";

import { useEffect, useState } from "react";
import { SportsDashboard } from "@/components/SportsDashboard";

/** Same client-only gate as /label — see label/page.tsx. */
export default function Home() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    setReady(true);
  }, []);

  if (!ready) {
    return <div className="shell" suppressHydrationWarning aria-busy="true" />;
  }

  return <SportsDashboard />;
}
