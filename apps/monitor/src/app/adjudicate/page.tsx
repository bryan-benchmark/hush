"use client";

import { ListenReview } from "@/components/ListenReview";

export default function AdjudicatePage() {
  return (
    <ListenReview
      endpoint="/api/adjudicate"
      kicker="Boundary review"
      otherHref="/returns"
      otherLabel="Return cues"
    />
  );
}
