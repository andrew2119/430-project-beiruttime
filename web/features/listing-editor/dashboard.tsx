"use client";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { ButtonLink, BidiReference } from "@beirut-time/ui";
import { Watch } from "lucide-react";
import { useRouter } from "next/navigation";
import { PageHeader, PageLayout } from "@/shell/page-header";
import { ListingSkeleton } from "./row-skeleton";
import { useLocale } from "@/shell/locale-context";
import { useAccessContext } from "@/shell/access-context";
import { slotsFor } from "@/registry-loader";
import { listingApiFor, scopedHref } from "./api";
import { copy } from "./copy";
import { Failure, ListingCards, SlotBoundary } from "./components";

export default function Dashboard() {
  const access = useAccessContext(),
    organization = useSearchParams().get("organization_id");
  return (
    <Workspace
      key={`${access.fingerprint}:${organization}`}
      fingerprint={access.fingerprint}
      organization={organization}
    />
  );
}
function Workspace({
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
  const own = useQuery({
    queryKey: ["seller-listings", fingerprint, organization],
    queryFn: () => listingApi.list(),
    retry: false,
    refetchInterval: 15000,
  });
  const workspace = useQuery({
    queryKey: ["seller-workspace", fingerprint, organization],
    queryFn: () => listingApi.workspace(),
    retry: false,
    refetchInterval: 10000,
  });
  const data = workspace.isError ? undefined : workspace.data;
  return (
    <PageLayout className="le-page">
      <PageHeader title={t.dashboard} count={t.workspaceIntro} actions={[
        { id: "listings", label: t.listings, icon: Watch, primary: true, onSelect: () => router.push(scopedHref(`/${locale}/seller/listings`, organization)) },
      ]} />
      {own.error && (
        <Failure
          error={own.error}
          t={t}
          locale={locale}
          retry={() => void own.refetch()}
        />
      )}
      {own.isPending ? (
        <ListingSkeleton label={t.loading} />
      ) : (
        own.data && (
          <>
            <div className="le-workspace-summaries">
              <section className="le-panel">
                <span>{t.draft}</span>
                <strong>{own.data.counts.draft}</strong>
              </section>
              <section className="le-panel">
                <span>{t.published}</span>
                <strong>{own.data.counts.published}</strong>
              </section>
              <section className="le-panel">
                <span>{t.publication_pending}</span>
                <strong>{own.data.counts.publication_pending}</strong>
              </section>
            </div>
            <ListingCards
              rows={own.data.items}
              t={t}
              locale={locale}
              organization={organization}
            />
          </>
        )
      )}
      <div className="le-workspace-sections">
        <section className="le-panel">
          <h2>{t.currentBids}</h2>
          {workspace.isPending ? (
            <p role="status">{t.loading}</p>
          ) : data?.bids.status === "available" ? (
            data.bids.data.items.length ? (
              <ul className="le-activity-list">
                {data.bids.data.items.map((auction) => (
                  <li key={auction.id}>
                    <BidiReference>{auction.id.slice(0, 8)}</BidiReference>
                    <span>
                      {auction.accepted_sequence} {t.acceptedBids}
                    </span>
                    <strong>
                      <BidiReference>
                        {new Intl.NumberFormat(
                          locale === "ar" ? "ar-LB" : "en-US",
                          { style: "currency", currency: auction.currency },
                        ).format(auction.current_minor / 100)}
                      </BidiReference>
                    </strong>
                  </li>
                ))}
              </ul>
            ) : (
              <p>{t.noAuctions}</p>
            )
          ) : (
            <p>{t.unavailable}</p>
          )}
          <ButtonLink
            variant="outline"
            href={scopedHref(`/${locale}/seller/auctions`, organization)}
          >
            {t.auction} ↗
          </ButtonLink>
        </section>
        <section className="le-panel">
          <h2>{t.sales}</h2>
          {workspace.isPending ? (
            <p role="status">{t.loading}</p>
          ) : data?.sales.status === "available" ? (
            data.sales.data.items.length ? (
              <ul className="le-activity-list">
                {data.sales.data.items.map((sale) => (
                  <li key={sale.id}>
                    <BidiReference>{sale.id.slice(0, 8)}</BidiReference>
                    <strong>{t[sale.state]}</strong>
                  </li>
                ))}
              </ul>
            ) : (
              <p>{t.noSales}</p>
            )
          ) : (
            <p>{t.unavailable}</p>
          )}
        </section>
        <section className="le-panel">
          <h2>{t.payout}</h2>
          <p>{t.payoutHint}</p>
        </section>
      </div>
      <SellerSlots locale={locale} fingerprint={fingerprint} />
    </PageLayout>
  );
}
// Registered contributions own their source DTOs; this workspace does not recreate
// bidding, reservation or payout business state. Optional slots stay independent.
import { lazy, Suspense, useMemo } from "react";
function SellerSlots({
  locale,
  fingerprint,
}: {
  locale: "en" | "ar";
  fingerprint: string | null;
}) {
  const t = copy(locale);
  const slots = useMemo(
    () =>
      slotsFor("seller.dashboard").map((slot) => ({
        id: slot.id,
        Component: lazy(slot.load),
      })),
    [],
  );
  return (
    <>
      {slots.map(({ id, Component }) => (
        <SlotBoundary key={id} unavailable={t.unavailable} retry={t.retry}>
          <Suspense fallback={null}>
            <Component
              locale={locale}
              accessFingerprint={fingerprint ?? undefined}
            />
          </Suspense>
        </SlotBoundary>
      ))}
    </>
  );
}
