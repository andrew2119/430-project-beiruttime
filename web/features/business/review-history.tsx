"use client";
import { useState } from "react";
import { PageControls, pagedRequest } from "./pagination";
import { ListingPossession } from "./possession";
import { useBusinessRead, ownReviewsRead } from "./reads";
import { Button, Card } from "@beirut-time/ui/foundation";
import type { PrivateReview } from "@contracts/contracts-identity/businesses";
import { useAccessContext } from "@/shell/access-context";
import { businessRequest } from "./transport";
import { DecisionHistory, type ReviewDetail } from "./history";
import { BusinessEmpty, BusinessLoading, Feedback, useCopy, Workspace } from "./components";

function History({ id }: { id: string }) {
  const t = useCopy(),
    access = useAccessContext();
  const [historyDenial, setHistoryDenial] = useState<unknown>(null);
  const query = useBusinessRead({
    queryKey: ["l02", "own-review", access.fingerprint, id],
    queryFn: () => businessRequest<ReviewDetail>(`/v2/private-reviews/${id}`),
    retry: false,
  });
  if (historyDenial) return <><Feedback error={historyDenial} /><Button onClick={() => void query.refetch().then(answer => { if (!answer.isError) setHistoryDenial(null); })}>{t.retry}</Button></>;
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
        <bdi dir="ltr">{query.data.application_id}</bdi>
      </p>
      <DecisionHistory
        key={`${id}:${query.data.revision}`}
        reviewId={id}
        items={query.data.history}
        before={query.data.history_before_revision}
        total={query.data.history_total}
        onDenied={setHistoryDenial}
      />
    </Card>
  );
}
export default function MyReviewHistory() {
  const t = useCopy(),
    access = useAccessContext();
  const [page,setPage]=useState(1);
  const query = useBusinessRead({
    read: ownReviewsRead(access.fingerprint,page),
    queryKey: ["business-v2", "my-reviews", access.fingerprint,page],
    queryFn: () =>
      pagedRequest<PrivateReview>("/v2/private-reviews/mine",page),
    retry: false,
  });
  return (
    <Workspace title={t.myReviewHistory} intro={t.reviewIntro}>
      <ListingPossession />
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
      {query.data && !query.isError && <PageControls answer={query.data} change={setPage} />}
    </Workspace>
  );
}
