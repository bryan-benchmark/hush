"use client";

import { ListenReview } from "@/components/ListenReview";

export default function ReturnsPage() {
  return (
    <ListenReview
      endpoint="/api/returns"
      kicker="Return cue"
      otherHref="/adjudicate"
      otherLabel="Boundary review"
    />
  );
}
