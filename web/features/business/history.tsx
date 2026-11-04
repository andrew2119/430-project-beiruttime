"use client";
import { useState } from "react";
import { BidiReference, Button } from "@beirut-time/ui";
import type { PrivateReview } from "@contracts/contracts-identity/businesses";
import { businessRequest } from "./transport";
import { Feedback, useAction, useCopy } from "./components";
export type Decision = {
  revision: number;
  state: PrivateReview["state"];
  reason: string;
  created_at: string;
};
export type ReviewDetail = PrivateReview & {
  history: Decision[];
  history_before_revision?: number | null;
};

/** Read-only paging of acknowledged history; this owns no verification state. */
export function DecisionHistory({
  reviewId,
  items,
  before,
}: {
  reviewId: string;
  items: Decision[];
  before?: number | null;
}) {
  const t = useCopy(),
    action = useAction(),
    [history, setHistory] = useState(items),
    [cursor, setCursor] = useState(before ?? null);
  return (
    <>
      <ol>
        {history.map((item) => (
          <li key={item.revision}>
            <p>
              {t[item.state]} · {item.reason}
            </p>
            <time dateTime={item.created_at}>
              <BidiReference>{item.created_at}</BidiReference>
            </time>
          </li>
        ))}
      </ol>
      {cursor !== null && (
        <Button
          disabled={action.pending}
          onClick={() =>
            void action.run(async () => {
              const page = await businessRequest<ReviewDetail>(
                `/v1/private-reviews/${reviewId}?before_revision=${cursor}`,
              );
              setHistory((old) =>
                [
                  ...new Map(
                    [...page.history, ...old].map((item) => [
                      item.revision,
                      item,
                    ]),
                  ).values(),
                ].sort((a, b) => a.revision - b.revision),
              );
              setCursor(page.history_before_revision ?? null);
            }, false)
          }
        >
          {t.earlierHistory}
        </Button>
      )}
      <Feedback error={action.error} />
    </>
  );
}
