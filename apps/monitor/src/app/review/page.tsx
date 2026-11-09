"use client";

import { ListenReview } from "@/components/ListenReview";

export default function ReviewPage() {
  return (
    <ListenReview
      endpoint="/api/review"
      kicker="Label listen"
      otherHref="/adjudicate"
      otherLabel="Boundary review"
    />
  );
}
