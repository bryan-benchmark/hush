"use client";

import { useEffect, useState } from "react";
import { DeepLabelApp } from "@/components/DeepLabelApp";

/** Same client-only gate as /label — avoid hydration mismatch on the shell. */
export default function DeepLabelPage() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    setReady(true);
  }, []);

  if (!ready) {
    return <div className="shell" suppressHydrationWarning aria-busy="true" />;
  }

  return <DeepLabelApp />;
}
