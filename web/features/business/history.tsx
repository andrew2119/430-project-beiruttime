"use client";
import { useRef, useState } from "react";
import { Button, StatusBadge } from "@beirut-time/ui/foundation";
import type { PrivateReview } from "@contracts/contracts-identity/businesses";
import type { PersonReviewHistory } from "@contracts/contracts-identity/businesses/workspace_v2";
import { formatNumber } from "@beirut-time/ui/foundation";
import { useLocale } from "@/shell/locale-context";
import { accessDenied } from "./command-form";
import { businessRequest } from "./transport";
import { Feedback, useAction, useCopy } from "./components";
export type Decision = {
  revision: number;
  state: PrivateReview["state"];
  reason: string;
  created_at: string;
};
export type ReviewDetail = PersonReviewHistory;

/** Read-only paging of acknowledged history; this owns no verification state. */
export function DecisionHistory({
  reviewId,
  items,
  before,
  total,
  onDenied,
}: {
  reviewId: string;
  items: Decision[];
  before?: number | null;
  total: number;
  onDenied: (error: unknown) => void;
}) {
  const locale = useLocale();
  const denied = useRef(false);
  const [denial, setDenial] = useState<unknown>(null);
  const t = useCopy(),
    action = useAction(),
    [history, setHistory] = useState(items),
    [cursor, setCursor] = useState(before ?? null);
  if (denial) return <Feedback error={denial} />;
  return (
    <>
      <p>{t.serverTotal}: {formatNumber(total,locale)}</p>
      <ol className="business-timeline">
        {history.map((item) => (
          <li key={item.revision} className="business-step">
            <span className="business-step-dot" aria-hidden="true">✓</span>
            <div className="business-step-body">
              <StatusBadge tone={item.state === "approved" ? "success" : item.state === "rejected" ? "error" : "warning"}>{t[item.state]}</StatusBadge>
              <p>{item.reason}</p>
              <time dateTime={item.created_at}>
                <bdi dir="ltr">{item.created_at}</bdi>
              </time>
            </div>
          </li>
        ))}
      </ol>
      {cursor !== null && (
        <Button
          disabled={action.pending}
          onClick={() =>
            void action.run(async () => {
              try {
              const page = await businessRequest<ReviewDetail>(
                `/v2/private-reviews/${reviewId}?before_revision=${cursor}`,
              );
              if (denied.current) return;
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
              } catch (error) {
                if (accessDenied(error)) {
                  denied.current = true;
                  setHistory([]);
                  setCursor(null);
                  setDenial(error);
                  onDenied(error);
                }
                throw error;
              }
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
