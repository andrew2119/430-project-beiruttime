"use client";
import { useEffect, useRef, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Button, ButtonLink, Skeleton } from "@beirut-time/ui";
import { useLocale } from "@/shell/locale-context";
import { useAccessContext } from "@/shell/access-context";
import { listingApi, scopedHref } from "./api";
import { copy } from "./copy";
import { Failure, ListingCards } from "./components";

export default function ListingsView() {
  const access = useAccessContext(),
    organization = useSearchParams().get("organization_id");
  return (
    <ListingIndex
      key={`${access.fingerprint}:${organization}`}
      fingerprint={access.fingerprint}
      organization={organization}
    />
  );
}
function ListingIndex({
  fingerprint,
  organization,
}: {
  fingerprint: string | null;
  organization: string | null;
}) {
  const locale = useLocale(),
    t = copy(locale),
    router = useRouter();
  const [busy, setBusy] = useState(false),
    [failure, setFailure] = useState<unknown>(null);
  const createKey = useRef(crypto.randomUUID()),alive=useRef(true);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  const query = useInfiniteQuery({
    queryKey: ["listing-editor", fingerprint, organization],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => listingApi.list(pageParam),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    retry: false,
  });
  const rows = query.data?.pages.flatMap((page) => page.items) ?? [];
  async function create() {
    setBusy(true);
    setFailure(null);
    try {
      const row = await listingApi.create(createKey.current);
      if(!alive.current)return;
      router.push(
        scopedHref(`/${locale}/seller/listings/${row.id}`, organization),
      );
    } catch (error) {
      setFailure(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="le-page">
      <header className="le-page-header">
        <div>
          <p className="le-eyebrow">{t.eyebrow}</p>
          <h1>{t.title}</h1>
          <p>{t.intro}</p>
        </div>
        <div className="le-actions">
          <ButtonLink
            className="button-secondary"
            href={scopedHref(`/${locale}/seller/dashboard`, organization)}
          >
            {t.dashboard}
          </ButtonLink>
          <Button disabled={busy} onClick={() => void create()}>
            {busy ? t.working : t.newListing} <span aria-hidden="true">＋</span>
          </Button>
        </div>
      </header>
      {Boolean(failure || query.error) && (
        <Failure
          error={failure || query.error}
          t={t}
          locale={locale}
          retry={() => {
            setFailure(null);
            void query.refetch();
          }}
        />
      )}
      {query.isPending ? (
        <Skeleton label={t.loading} />
      ) : rows.length ? (
        <ListingCards
          rows={rows}
          t={t}
          locale={locale}
          organization={organization}
        />
      ) : (
        query.data && (
          <section className="le-empty">
            <span aria-hidden="true">◇</span>
            <h2>{t.empty}</h2>
            <p>{t.emptyBody}</p>
            <Button onClick={() => void create()} disabled={busy}>
              {t.newListing}
            </Button>
          </section>
        )
      )}
      {query.hasNextPage && (
        <div className="le-pager">
          <Button
            className="button-secondary"
            disabled={query.isFetchingNextPage}
            onClick={() => void query.fetchNextPage()}
          >
            {query.isFetchingNextPage ? t.loading : t.more}
          </Button>
        </div>
      )}
    </div>
  );
}
