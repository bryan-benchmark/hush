"use client";

import { ListenReview } from "@/components/ListenReview";

export default function LoudPage() {
  return (
    <ListenReview
      endpoint="/api/loud"
      kicker="Loud show"
      ask="Mark what you hear"
      hint="Cut when the spot changes. Dictate or type what each stretch is. The green tick is only why we queued this—not a real cut."
      hideResearchMark
      dictation
      otherHref="/review"
      otherLabel="Current listen"
    />
  );
}
