"use client";
import { useQuery } from "@tanstack/react-query";
import { BidiReference, Button, Card } from "@beirut-time/ui";
import type { PrivateReview } from "@contracts/contracts-identity/businesses";
import { useAccessContext } from "@/shell/access-context";
import { businessRequest } from "./transport";
import { DecisionHistory, type ReviewDetail } from "./history";
import { BusinessEmpty, BusinessLoading, Feedback, useCopy, Workspace } from "./components";

function History({ id }: { id: string }) {
  const t = useCopy(),
    access = useAccessContext();
  const query = useQuery({
    queryKey: ["l02", "own-review", access.fingerprint, id],
    queryFn: () => businessRequest<ReviewDetail>(`/v1/private-reviews/${id}`),
    retry: false,
  });
  if (query.isPending) return <BusinessLoading />;
  if (query.isError)
    return (
      <>
        <Feedback error={query.error} />
        <Button onClick={() => query.refetch()}>{t.retry}</Button>
      </>
    );
  return (
    <Card>
      <h2>{t[query.data.state]}</h2>
      <p>
        {t.application}:{" "}
        <BidiReference>{query.data.application_id}</BidiReference>
      </p>
      <DecisionHistory
        key={`${id}:${query.data.revision}`}
        reviewId={id}
        items={query.data.history}
        before={query.data.history_before_revision}
      />
    </Card>
  );
}
export default function MyReviewHistory() {
  const t = useCopy(),
    access = useAccessContext();
  const query = useQuery({
    queryKey: ["l02", "my-reviews", access.fingerprint],
    queryFn: () =>
      businessRequest<{ items: PrivateReview[] }>("/v1/private-reviews/mine"),
    retry: false,
  });
  return (
    <Workspace title={t.myReviewHistory} intro={t.reviewIntro}>
      {query.isPending ? (
        <BusinessLoading />
      ) : query.isError ? (
        <>
          <Feedback error={query.error} />
          <Button onClick={() => query.refetch()}>{t.retry}</Button>
        </>
      ) : !query.data.items.length ? (
        <BusinessEmpty text={t.noReviews} />
      ) : (
        query.data.items.map((review) => (
          <History key={review.id} id={review.id} />
        ))
      )}
    </Workspace>
  );
}
