"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Button, State } from "@beirut-time/ui";
import { LayoutDashboard, Plus } from "lucide-react";
import { PageHeader, PageLayout } from "@/shell/page-header";
import { ListingSkeleton } from "./row-skeleton";
import { useLocale } from "@/shell/locale-context";
import { useAccessContext } from "@/shell/access-context";
import { listingApiFor, scopedHref } from "./api";
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
  const listingApi = useMemo(
    () => listingApiFor(fingerprint, organization),
    [fingerprint, organization],
  );
  const [busy, setBusy] = useState(false),
    [failure, setFailure] = useState<unknown>(null);
  const createKey = useRef(crypto.randomUUID()),
    alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
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
      if (!alive.current) return;
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
    <PageLayout className="le-page">
      <PageHeader title={t.title} count={t.intro} actions={[
        { id: "dashboard", label: t.dashboard, icon: LayoutDashboard, onSelect: () => router.push(scopedHref(`/${locale}/seller/dashboard`, organization)) },
        { id: "new", label: busy ? t.working : t.newListing, icon: Plus, primary: true, busy, onSelect: () => void create() },
      ]} />
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
        <ListingSkeleton label={t.loading} />
      ) : rows.length ? (
        <ListingCards
          rows={rows}
          t={t}
          locale={locale}
          organization={organization}
        />
      ) : (
        query.data && (
          <State title={t.empty} body={t.emptyBody}>
            <Button chonk onClick={() => void create()} disabled={busy}>
              <Plus aria-hidden="true" />{t.newListing}
            </Button>
          </State>
        )
      )}
      {query.hasNextPage && (
        <div className="le-pager">
          <Button
            variant="outline"
            disabled={query.isFetchingNextPage}
            onClick={() => void query.fetchNextPage()}
          >
            {query.isFetchingNextPage ? t.loading : t.more}
          </Button>
        </div>
      )}
    </PageLayout>
  );
}
