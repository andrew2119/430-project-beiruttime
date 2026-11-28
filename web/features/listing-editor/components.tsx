"use client";
import { Component, type ReactNode, useEffect, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useLocale } from "@/shell/locale-context";
import { signInHref, useSession } from "@/features/identity/session";
import { ApiError } from "@/lib/api/client";
import { AnimatedList, Button, ButtonLink, BidiReference, ImageFrame, State, StatusBadge } from "@beirut-time/ui";
import { Watch, Wallet } from "lucide-react";
import Link from "next/link";
import { coverPressLook } from '@/lib/press-look';
import type { Listing } from "@contracts/contracts-catalog/listings/v1";
import { listingApiFor, scopedHref } from "./api";
import { copy, type Copy } from "./copy";
import { correctionFields } from "./validation";

export function Failure({
  error,
  t,
  locale,
  retry,
  revision = false,
}: {
  revision?: boolean;
  error: unknown;
  t: Copy;
  locale: string;
  retry?: () => void;
}) {
  const pathname = usePathname(),
    search = useSearchParams().toString();
  const code = error instanceof ApiError ? error.code : "";
  const denied = error instanceof ApiError && error.status === 401;
  const messages:Record<string,string> = {
    stale_revision:t.stale,listing_incomplete:t.complete,invalid_image:t.photoHint,
    edit_pending:t.editPending,listing_frozen:t.revisionBlocked,
    auction_edit_denied:t.revisionBlocked,edit_denied:t.revisionBlocked,
    sale_mode_frozen:t.saleModeFrozen,
    publication_review_pending:revision ? t.revisionReviewPending : t.publicationReviewPending,
    publication_review_denied:revision ? t.revisionReviewDenied : t.publicationReviewDenied,
  };
  const message = denied ? t.signInBody
    : error instanceof ApiError && error.status === 403 ? t.forbidden
    : messages[code] ?? (error instanceof ApiError && error.status === 503 ? t.unavailable : t.error);
  const fields = correctionFields(
    error instanceof ApiError ? error.details.fields : null,
  );
  return (
    <div role="alert">
      <State kind="error" title={denied ? t.signIn : t.errorTitle} body={message}>
      {fields.length > 0 && (
        <ul className="le-field-errors">
          {fields.map((field) => (
            <li key={field}>{t[field]}</li>
          ))}
        </ul>
      )}
      {denied ? (
        <ButtonLink
          href={signInHref(
            pathname + (search ? "?" + search : ""),
            locale === "ar" ? "ar" : "en",
          )}
        >
          {t.signIn}
        </ButtonLink>
      ) : (
        retry && <Button onClick={retry}>{t.retry}</Button>
      )}
      {error instanceof ApiError && error.requestId && (
        <small>
          <BidiReference>{error.requestId}</BidiReference>
        </small>
      )}
      </State>
    </div>
  );
}
export function Status({ row, t }: { row: Listing; t: Copy }) {
  return (
    <StatusBadge hue={row.is_hidden ? "neutral" : row.status === "published" ? "green" : row.status === "publication_pending" ? "orange" : "neutral"}>
      {row.is_hidden ? t.hidden : t[row.status]}
    </StatusBadge>
  );
}
export function OwnerPhoto({
  listingId,
  assetId,
  alt,
}: {
  listingId: string;
  assetId: string;
  alt: string;
}) {
  const [url, setUrl] = useState<string | null>(null),
    [failed, setFailed] = useState(false),
    [attempt, setAttempt] = useState(0);
  const t = copy(useLocale()),
    session = useSession();
  useEffect(() => {
    let alive = true,
      reader: FileReader | undefined;
    listingApiFor(session?.access_fingerprint ?? null)
      .file(listingId, assetId, session)
      .then((blob) => {
        if (!alive) return;
        // The shell intentionally allows data previews, not blob image sources.
        // Keep this watch-only preview in component memory and fence late readers.
        reader = new FileReader();
        reader.onload = () => {
          const value = reader?.result;
          if (alive && typeof value === "string") setUrl(value);
        };
        reader.onerror = () => {
          if (alive) setFailed(true);
        };
        reader.readAsDataURL(blob);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
      if (reader?.readyState === FileReader.LOADING) reader.abort();
    };
  }, [listingId, assetId, attempt, session]);
  return (
    <div className="le-photo-frame">
      <Watch aria-hidden="true" />
      {failed && (
        <Button
          variant="outline" className="le-photo-retry"
          onClick={() => {
            setFailed(false);
            setAttempt(attempt + 1);
          }}
        >
          {t.retry}
        </Button>
      )}
      {url && (
        <ImageFrame src={url} alt={alt} className="ui-image-frame-fill" placeholder={<Watch aria-hidden="true" />} />
      )}
    </div>
  );
}
export function ListingCards({
  rows,
  t,
  locale,
  organization = null,
}: {
  rows: Listing[];
  t: Copy;
  locale: string;
  organization?: string | null;
}) {
  return (
    <AnimatedList items={rows} getKey={row => row.id} className="le-listing-rows">
      {row => <article className="le-watch-row pg-row">
        <Link className="le-row-open" href={scopedHref(`/${locale}/seller/listings/${row.id}`, organization)} aria-label={`${row.status === "published" ? t.review : t.next} — ${row.facts.brand} ${row.facts.model}`} {...coverPressLook} />
        <div className="le-row-chevron-spacer" aria-hidden="true" />
        <div className="le-row-cover">
          {row.cover_id ? <OwnerPhoto key={row.cover_id} listingId={row.id} assetId={row.cover_id} alt={`${row.facts.brand} ${row.facts.model}`} /> : <Watch aria-hidden="true" />}
        </div>
        <div className="le-row-info">
          <h2>{row.facts.brand || "—"} {row.facts.model}</h2>
          <p><BidiReference>{row.facts.reference || "—"}</BidiReference> · {row.facts.location || "—"}{row.is_demo && <> · {t.demo}</>}</p>
        </div>
        <div className="le-row-price"><span className="le-wallet"><Wallet aria-hidden="true" /></span><BidiReference>{row.facts.price_minor ? new Intl.NumberFormat(locale === "ar" ? "ar-LB" : "en-US", {style:"currency",currency:"USD"}).format(row.facts.price_minor / 100) : "—"}</BidiReference></div>
        <div className="le-row-status"><Status row={row} t={t} /></div>
      </article>}
    </AnimatedList>
  );
}

export class SlotBoundary extends Component<
  { children: ReactNode; unavailable: string; retry: string },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <div className="le-notice" role="status">
        <p>{this.props.unavailable}</p>
        <Button
          variant="outline"
          onClick={() => window.location.reload()}
        >
          {this.props.retry}
        </Button>
      </div>
    ) : (
      this.props.children
    );
  }
}
