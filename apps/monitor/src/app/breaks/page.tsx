"use client";

import { ListenReview } from "@/components/ListenReview";

export default function BreaksPage() {
  return (
    <ListenReview
      endpoint="/api/breaks"
      kicker="Break listen"
      otherHref="/review"
      otherLabel="Current listen"
    />
  );
}
