"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BidiReference, Button, Card } from "@beirut-time/ui";
import type { PrivateReview } from "@contracts/contracts-identity/businesses";
import { useAccessContext } from "@/shell/access-context";
import { useSession } from "@/features/identity/session";
import { businessRequest, businessFile, command } from "./transport";
import { DecisionHistory, type ReviewDetail } from "./history";
import {
  Feedback,
  Field,
  Select,
  Submit,
  integer,
  text,
  useAction,
  useCopy,
  Workspace,
} from "./components";
export default function VerificationDesk() {
  const t = useCopy(),
    access = useAccessContext(),
    session = useSession(),
    action = useAction(),
    [selected, setSelected] = useState("");
  const canAssign =
    session?.principal.permissions.includes("identity.private-seller.assign") ??
    false;
  const query = useQuery({
    queryKey: ["l02", "reviews", access.fingerprint],
    queryFn: () =>
      businessRequest<{ items: PrivateReview[] }>("/v1/private-reviews"),
    retry: false,
  });
  const detail = useQuery({
    queryKey: ["l02", "review", access.fingerprint, selected],
    queryFn: () =>
      businessRequest<ReviewDetail>(`/v1/private-reviews/${selected}`),
    enabled: !!selected,
    retry: false,
  });
  const evidence = useQuery({
    queryKey: ["l02", "evidence", access.fingerprint, selected],
    queryFn: () =>
      businessRequest<{
        items: { id: string; kind: "identity" | "possession"; size: number }[];
      }>(`/v1/private-reviews/${selected}/evidence`),
    enabled: !!selected,
    retry: false,
  });
  return (
    <Workspace title={t.reviewTitle} intro={t.reviewIntro}>
      <Card>
        <h2>{t.queue}</h2>
        <p>{t.reviewHelp}</p>
        {query.isPending ? (
          <p role="status">{t.loading}</p>
        ) : query.isError ? (
          <Feedback error={query.error} />
        ) : !query.data.items.length ? (
          <p>{t.noReviews}</p>
        ) : (
          <ul className="business-queue">
            {query.data.items.map((review) => (
              <li key={review.id}>
                <div>
                  <BidiReference>{review.application_id}</BidiReference>
                  <p>
                    {t[review.state]} · {t.revision} {review.revision}
                  </p>
                </div>
                <Button onClick={() => setSelected(review.id)}>{t.open}</Button>
              </li>
            ))}
          </ul>
        )}
        <Button onClick={() => query.refetch()}>{t.reload}</Button>
      </Card>
      {selected && (
        <Card>
          {detail.isError ? (
            <Feedback error={detail.error} />
          ) : detail.isPending ? (
            <p role="status">{t.loading}</p>
          ) : (
            <>
              <h2>
                <BidiReference>{detail.data.application_id}</BidiReference>
              </h2>
              <h3>{t.evidence}</h3>
              <Feedback error={evidence.error} />
              <ul className="business-queue">
                {evidence.data?.items.map((file) => (
                  <li key={file.id}>
                    <span>
                      {file.kind === "identity"
                        ? t.identityProof
                        : t.possessionProof}
                    </span>
                    <Button
                      disabled={action.pending}
                      onClick={() =>
                        void action.run(async () => {
                          const blob = await businessFile(
                            `/v1/private-reviews/${selected}/files/${file.id}`,
                            session?.access_token ?? null,
                          );
                          const url = URL.createObjectURL(blob);
                          const anchor = document.createElement("a");
                          anchor.href = url;
                          anchor.download = "private-verification-evidence";
                          anchor.hidden = true;
                          document.body.append(anchor);
                          try {
                            anchor.click();
                          } finally {
                            anchor.remove();
                            // Allow the browser to admit the explicit download.
                            setTimeout(() => URL.revokeObjectURL(url), 1000);
                          }
                        }, false)
                      }
                    >
                      {t.download}
                    </Button>
                  </li>
                ))}
              </ul>
              <form
                key={`${selected}:${detail.data.revision}`}
                className="business-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  const data = new FormData(event.currentTarget);
                  void action.run(async () => {
                    await command(`/v1/private-reviews/${selected}/verdict`, {
                      revision: detail.data.revision,
                      application_revision: integer(
                        data,
                        "application_revision",
                      ),
                      state: text(data, "state"),
                      reason: text(data, "reason"),
                    });
                    await Promise.all([query.refetch(), detail.refetch()]);
                  });
                }}
              >
                <Field
                  name="application_revision"
                  label={t.applicationRevision}
                  type="number"
                  defaultValue={String(detail.data.application_revision)}
                  inputMode="numeric"
                />
                <Select
                  name="state"
                  label={t.decision}
                  options={(
                    ["correction", "approved", "rejected", "suspended"] as const
                  ).map((state) => ({ value: state, label: t[state] }))}
                />
                <Field
                  name="reason"
                  label={t.reason}
                  minLength={5}
                  maxLength={500}
                />
                <Submit pending={action.pending} label={t.verdict} />
              </form>
              <h3>{t.history}</h3>
              <DecisionHistory
                key={`${selected}:${detail.data.revision}`}
                reviewId={selected}
                items={detail.data.history}
                before={detail.data.history_before_revision}
              />
            </>
          )}
        </Card>
      )}
      {canAssign && (
        <Card>
          <h2>{t.assign}</h2>
          <form
            className="business-form"
            onSubmit={(event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              void action.run(async () => {
                await command("/v1/private-reviews", {
                  application_id: text(data, "application"),
                  reviewer_id: text(data, "reviewer"),
                  reason: text(data, "reason"),
                });
                await query.refetch();
              });
            }}
          >
            <Field name="application" label={t.application} maxLength={36} />
            <Field name="reviewer" label={t.reviewer} maxLength={36} />
            <Field
              name="reason"
              label={t.reason}
              minLength={5}
              maxLength={500}
            />
            <Submit pending={action.pending} label={t.assign} />
          </form>
        </Card>
      )}
      {canAssign && (
        <Card>
          <h2>{t.reassign}</h2>
          <form
            className="business-form"
            onSubmit={(event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              void action.run(async () => {
                await command(
                  `/v1/private-reviews/${text(data, "review")}/reassign`,
                  {
                    revision: integer(data, "revision"),
                    reviewer_id: text(data, "reviewer"),
                    reason: text(data, "reason"),
                  },
                );
                setSelected("");
                await query.refetch();
              });
            }}
          >
            <Field name="review" label={t.reviewReference} maxLength={36} />
            <Field
              name="revision"
              label={t.revision}
              type="number"
              inputMode="numeric"
            />
            <Field name="reviewer" label={t.reviewer} maxLength={36} />
            <Field
              name="reason"
              label={t.reason}
              minLength={5}
              maxLength={500}
            />
            <Submit pending={action.pending} label={t.reassign} />
          </form>
        </Card>
      )}
      <Feedback error={action.error} success={action.success} />
    </Workspace>
  );
}
