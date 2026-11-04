"use client";
import { Component, type ReactNode, useEffect, useState } from "react";
import Image from "next/image";
import { usePathname, useSearchParams } from "next/navigation";
import { useLocale } from "@/shell/locale-context";
import { signInHref,useSession } from "@/features/identity/session";
import { ApiError } from "@/lib/api/client";
import { Button, ButtonLink, BidiReference } from "@beirut-time/ui";
import type { Listing } from "@contracts/contracts-catalog/listings/v1";
import { listingApi, scopedHref } from "./api";
import { copy, type Copy } from "./copy";
import { correctionFields } from "./validation";

export function Failure({
  error,
  t,
  locale,
  retry,
}: {
  error: unknown;
  t: Copy;
  locale: string;
  retry?: () => void;
}) {
  const pathname = usePathname(),
    search = useSearchParams().toString();
  const code = error instanceof ApiError ? error.code : "";
  const denied = error instanceof ApiError && error.status === 401;
  const message = denied
    ? t.signInBody
    : error instanceof ApiError && error.status === 403
      ? t.forbidden
      : code === "stale_revision"
        ? t.stale
        : code === "listing_incomplete"
          ? t.complete
          : code === "invalid_image"
            ? t.photoHint
            : error instanceof ApiError && error.status === 503
              ? t.unavailable
              : t.error;
  const fields = correctionFields(
    error instanceof ApiError ? error.details.fields : null,
  );
  return (
    <div className="le-notice" role="alert">
      <p>{message}</p>
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
    </div>
  );
}
export function Status({ row, t }: { row: Listing; t: Copy }) {
  return (
    <span
      className={`le-status le-status-${row.is_hidden ? "hidden" : row.status}`}
    >
      {row.is_hidden ? t.hidden : t[row.status]}
    </span>
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
  const t = copy(useLocale()),session=useSession();
  useEffect(() => {
    let alive = true,reader:FileReader|undefined;
    listingApi.file(listingId,assetId,session).then(blob=>{
      if(!alive)return;
      // The shell intentionally allows data previews, not blob image sources.
      // Keep this watch-only preview in component memory and fence late readers.
      reader=new FileReader();
      reader.onload=()=>{const value=reader?.result;if(alive&&typeof value==='string')setUrl(value);};
      reader.onerror=()=>{if(alive)setFailed(true);};
      reader.readAsDataURL(blob);
    }).catch(()=>{if(alive)setFailed(true);});
    return ()=>{alive=false;if(reader?.readyState===FileReader.LOADING)reader.abort();};
  }, [listingId, assetId, attempt,session]);
  return (
    <div className="le-photo-frame">
      <span aria-hidden="true">◇</span>
      {failed && (
        <Button
          className="le-photo-retry button-secondary"
          onClick={() => {
            setFailed(false);
            setAttempt(attempt + 1);
          }}
        >
          {t.retry}
        </Button>
      )}
      {url && (
        <Image
          src={url}
          alt={alt}
          fill
          unoptimized
          sizes="(max-width:850px) 90vw, 400px"
          className="le-owner-image"
          onLoad={(e) => {
            const image = e.currentTarget;
            void image
              .decode()
              .then(() => {
                image.dataset.ready = "true";
              })
              .catch(() => {});
          }}
        />
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
    <div className="le-listing-grid">
      {rows.map((row) => (
        <article className="le-watch-card" key={row.id}>
          {row.cover_id ? (
            <OwnerPhoto
              key={row.cover_id}
              listingId={row.id}
              assetId={row.cover_id}
              alt={`${row.facts.brand} ${row.facts.model}`}
            />
          ) : (
            <div className="le-photo-frame le-photo-empty" aria-hidden="true">
              ◇
            </div>
          )}
          <div className="le-watch-content">
            <div className="le-inline">
              <Status row={row} t={t} />
              {row.is_demo && <small>{t.demo}</small>}
            </div>
            <h2>
              {row.facts.brand || "—"} <span>{row.facts.model}</span>
            </h2>
            <p>
              <BidiReference>{row.facts.reference || "—"}</BidiReference> ·{" "}
              {row.facts.location || "—"}
            </p>
            <div className="le-inline le-between">
              <span>
                {row.facts.price_minor
                  ? new Intl.NumberFormat(locale === "ar" ? "ar-LB" : "en-US", {
                      style: "currency",
                      currency: "USD",
                    }).format(row.facts.price_minor / 100)
                  : "—"}
              </span>
              <ButtonLink
                href={scopedHref(
                  `/${locale}/seller/listings/${row.id}`,
                  organization,
                )}
              >
                {row.status === "published" ? t.review : t.next}{" "}
                <span aria-hidden="true">↗</span>
              </ButtonLink>
            </div>
          </div>
        </article>
      ))}
    </div>
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
          className="button-secondary"
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
