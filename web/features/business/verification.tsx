"use client";
import { PageControls, pagedRequest } from "./pagination";
import { accessDenied, PendingRecovery, CommandForm, useCommandSnapshot, usePendingCommands } from "./command-form";
import { ListingPossession } from "./possession";
import { useState } from "react";
import { useBusinessRead, reviewQueueRead } from "./reads";
import { Button, Card } from "@beirut-time/ui/foundation";
import type { PrivateReview } from "@contracts/contracts-identity/businesses";
import { useAccessContext } from "@/shell/access-context";
import { useSession } from "@/features/identity/session";
import { businessRequest, businessFile } from "./transport";
import { DecisionHistory, type ReviewDetail } from "./history";
import {
  BusinessEmpty,
  BusinessLoading,
  Feedback,
  Field,
  Select,
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
  const [page,setPage]=useState(1);
  const [historyDenial, setHistoryDenial] = useState<unknown>(null);
  const {busy, onPending, recovery} = usePendingCommands();
  const canAssign =
    session?.principal.permissions.includes("identity.private-seller.assign") ??
    false;
  const query = useBusinessRead({
    read: reviewQueueRead(access.fingerprint,page),
    queryKey: ["business-v2", "reviews", access.fingerprint,page],
    queryFn: () =>
      pagedRequest<PrivateReview>("/v2/private-reviews",page),
    retry: false,
  });
  const detail = useBusinessRead({
    queryKey: ["l02", "review", access.fingerprint, selected],
    queryFn: () =>
      businessRequest<ReviewDetail>(`/v2/private-reviews/${selected}`),
    enabled: !!selected,
    retry: false,
  });
  const evidence = useBusinessRead({
    queryKey: ["l02", "evidence", access.fingerprint, selected],
    queryFn: () =>
      businessRequest<{
        items: { id: string; kind: "identity" | "possession"; size: number }[];
      }>(`/v1/private-reviews/${selected}/evidence`),
    enabled: !!selected,
    retry: false,
  });
  const currentDetail = useCommandSnapshot(detail.isError || evidence.isError ? undefined : detail.data, busy, access.fingerprint, accessDenied(detail.error) || accessDenied(evidence.error) || !!historyDenial);
  return (
    <Workspace title={t.reviewTitle} intro={t.reviewIntro}>
      <ListingPossession />
      <Card>
        <h2>{t.queue}</h2>
        <p>{t.reviewHelp}</p>
        {query.isPending ? (
          <BusinessLoading />
        ) : query.isError ? (
          <Feedback error={query.error} />
        ) : !query.data.items.length ? (
          <BusinessEmpty text={t.noReviews} />
        ) : (
          <ul className="business-queue">
            {query.data.items.map((review) => (
              <li key={review.id}>
                <div>
                  <bdi dir="ltr">{review.application_id}</bdi>
                  <p>
                    {t[review.state]} · {t.revision} {review.revision}
                  </p>
                </div>
                <Button variant="outline" disabled={busy} onClick={() => { if (!busy) { if (selected !== review.id) setHistoryDenial(null); setSelected(review.id); } }}>{t.open}</Button>
              </li>
            ))}
          </ul>
        )}
        <Button disabled={busy} onClick={() => query.refetch()}>{t.reload}</Button>
        {query.data && !query.isError && <PageControls answer={query.data} change={setPage} disabled={busy} />}
      </Card>
    {busy && !currentDetail ? <PendingRecovery recovery={recovery} onPending={onPending} refresh={() => void detail.refetch()} /> : null}
      {selected && (
        <Card >
          {!currentDetail && (detail.isError || evidence.isError || historyDenial) ? (
            <>
              <Feedback error={historyDenial ?? (evidence.isError ? evidence.error : detail.error)} />
              <Button onClick={() => void Promise.all([detail.refetch(), evidence.refetch()]).then(([record, files]) => {
                if (!record.isError && !files.isError) setHistoryDenial(null);
              })}>{t.retry}</Button>
            </>
          ) : !currentDetail ? (
            <BusinessLoading />
          ) : (
            <>
              <h2>
                <bdi dir="ltr">{currentDetail.application_id}</bdi>
              </h2>
              <h3>{t.evidence}</h3>
              <Feedback error={evidence.error} />
              {evidence.isError && <Button onClick={() => void evidence.refetch()}>{t.retry}</Button>}
              {evidence.isPending && <BusinessLoading />}
              {!evidence.isError && evidence.data?.items.length === 0 && <BusinessEmpty text={t.evidenceIncomplete} />}
              <ul className="business-queue">
                {!evidence.isError && evidence.data?.items.map((file) => (
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
                          ).catch((error: unknown) => {
                            if (accessDenied(error)) setHistoryDenial(error);
                            throw error;
                          });
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
              <CommandForm
                key={`${selected}:${currentDetail.revision}`}
                disabled={busy} onPending={onPending}
                onComplete={() => { void query.refetch(); void detail.refetch(); }}
                submit={(data, operation) => operation.membership(`/v1/private-reviews/${selected}/verdict`, {
                  revision: currentDetail.revision,
                  application_revision: integer(data, "application_revision"),
                  state: text(data, "state"), reason: text(data, "reason"),
                })}
              >
                <Field
                  name="application_revision"
                  label={t.applicationRevision}
                  type="number"
                  defaultValue={String(currentDetail.application_revision)}
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
              </CommandForm>
              <h3>{t.history}</h3>
              <DecisionHistory
                key={`${selected}:${currentDetail.revision}`}
                reviewId={selected}
                items={currentDetail.history}
                before={currentDetail.history_before_revision}
                total={currentDetail.history_total}
                onDenied={setHistoryDenial}
              />
            </>
          )}
        </Card>
      )}
      {canAssign && (
        <Card>
          <h2>{t.assign}</h2>
          <CommandForm disabled={busy} onPending={onPending}
            onComplete={() => { void query.refetch(); }}
            submit={(data, operation) => operation.membership("/v1/private-reviews", {
              application_id: text(data, "application"), reviewer_id: text(data, "reviewer"), reason: text(data, "reason"),
            })}>
            <Field name="application" label={t.application} maxLength={36} />
            <Field name="reviewer" label={t.reviewer} maxLength={36} />
            <Field
              name="reason"
              label={t.reason}
              minLength={5}
              maxLength={500}
            />
          </CommandForm>
        </Card>
      )}
      {canAssign && (
        <Card>
          <h2>{t.reassign}</h2>
          <CommandForm disabled={busy} onPending={onPending}
            onComplete={() => { setSelected(""); void query.refetch(); }}
            submit={(data, operation) => operation.membership(`/v1/private-reviews/${text(data, "review")}/reassign`, {
              revision: integer(data, "revision"), reviewer_id: text(data, "reviewer"), reason: text(data, "reason"),
            })}>
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
          </CommandForm>
        </Card>
      )}
      <Feedback error={action.error} success={action.success} />
    </Workspace>
  );
}
