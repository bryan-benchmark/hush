"use client";

import { useEffect, useState } from "react";
import { FarmLabelApp } from "@/components/FarmLabelApp";

export default function FarmLabelPage() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    setReady(true);
  }, []);

  if (!ready) {
    return <div className="shell" suppressHydrationWarning aria-busy="true" />;
  }

  return <FarmLabelApp />;
}
