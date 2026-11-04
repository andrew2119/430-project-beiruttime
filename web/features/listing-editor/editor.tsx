"use client";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {ApiError} from '@/lib/api/client';
import { useSearchParams } from "next/navigation";
import { useSession } from "@/features/identity/session";
import {
  Button,
  ButtonLink,
  Input,
  Skeleton,
  BidiReference,
} from "@beirut-time/ui";
import { normalizeDigits } from "@beirut-time/i18n";
import { useLocale } from "@/shell/locale-context";
import { useAccessContext } from "@/shell/access-context";
import type {
  Listing,
  WatchFacts,
  Modification,
  FeeQuote,
} from "@contracts/contracts-catalog/listings/v1";
import { listingApi, scopedHref } from "./api";
import { copy } from "./copy";
import { Failure, OwnerPhoto, Status } from "./components";
import { parseMinor } from "./money";

export default function Editor({ id }: { id: string }) {
  const access = useAccessContext(),
    organization = useSearchParams().get("organization_id");
  return (
    <DraftLoader
      key={`${access.fingerprint}:${organization}:${id}`}
      id={id}
      fingerprint={access.fingerprint}
      organization={organization}
    />
  );
}
function DraftLoader({
  id,
  fingerprint,
  organization,
}: {
  id: string;
  fingerprint: string | null;
  organization: string | null;
}) {
  const locale = useLocale(),
    t = copy(locale);
  const query = useQuery({
    queryKey: ["listing-editor", fingerprint, organization, id],
    queryFn: () => listingApi.read(id),
    retry: false,
    staleTime: Infinity,
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
  });
  if (query.isPending) return <Skeleton label={t.loading} />;
  if (!query.data)
    return (
      <div className="le-page">
        <header className="le-page-header">
          <h1>{t.newListing}</h1>
        </header>
        <Failure
          error={query.error}
          t={t}
          locale={locale}
          retry={() => void query.refetch()}
        />
      </div>
    );
  return (
    <DraftEditor
      key={query.dataUpdatedAt}
      initial={query.data}
      fingerprint={fingerprint}
      organization={organization}
      reload={() => void query.refetch()}
    />
  );
}
function DraftEditor({
  initial,
  fingerprint,
  organization,
  reload,
}: {
  initial: Listing;
  fingerprint: string | null;
  organization: string | null;
  reload: () => void;
}) {
  const id = initial.id,
    locale = useLocale(),
    t = copy(locale);
  const session = useSession();
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const [row, setRow] = useState(initial),
    [facts, setFacts] = useState(initial.facts);
  const [step, setStep] = useState(0),
    [dirty, setDirty] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null),
    [notice, setNotice] = useState(""),
    [safe, setSafe] = useState(false);
  const [price, setPrice] = useState(
      initial.facts.price_minor === null
        ? ""
        : String(initial.facts.price_minor / 100),
    ),
    [quote, setQuote] = useState<FeeQuote | null>(
      initial.fee_snapshot as FeeQuote | null,
    );
  const publicationKey = useRef(crypto.randomUUID());
  const pendingSave=useRef<{signature:string;key:string}|null>(null);
  const pendingUpload=useRef<{signature:string;key:string}|null>(null);
  const media = useQuery({
    queryKey: ["listing-media", fingerprint, organization, id, row.revision],
    queryFn: () => listingApi.media(id),
    retry: false,
  });
  const current = row,
    form = facts,
    editable = current.status === "draft";
  function field<K extends keyof WatchFacts>(name: K, value: WatchFacts[K]) {
    setFacts({ ...form, [name]: value });
    setDirty(true);
    setNotice("");
    setQuote(null);
  }
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      await action();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }
  async function persist() {
    const signature=JSON.stringify([current.revision,form]);
    if(pendingSave.current?.signature!==signature)pendingSave.current={signature,key:crypto.randomUUID()};
    const saved = await listingApi.save(current, form, pendingSave.current.key);
    pendingSave.current=null;
    setRow(saved);setFacts(saved.facts);setDirty(false);setQuote(null);setNotice(t.saved);
    return saved;
  }
  async function save(){await persist();}
  function modify(index: number, name: keyof Modification, value: string) {
    field(
      "modifications",
      form.modifications.map((item, i) =>
        i === index ? { ...item, [name]: value } : item,
      ),
    );
  }
  async function fileUpload(
    file: File | undefined,
    kind: "public_photo" | "private_document",
  ) {
    if (!file) return;
    await run(async () => {
      if(file.size>8_000_000)throw new ApiError(413,'media_bytes_limit','');
      let saved = current;
      if (dirty) saved=await persist();
      const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer()))).map(byte=>byte.toString(16).padStart(2,'0')).join('');
      if(!alive.current)return;
      const signature=JSON.stringify([saved.id,saved.revision,kind,hash]);
      if(pendingUpload.current?.signature!==signature)pendingUpload.current={signature,key:crypto.randomUUID()};
      const result = await listingApi.upload(saved,file,kind,pendingUpload.current.key);
      pendingUpload.current=null;
      setRow(result.listing);
      setFacts(result.listing.facts);
      setQuote(null);
      setNotice(t.saved);
    });
  }
  async function gallery(ids: string[], cover: string) {
    await run(async () => {
      const result = await listingApi.gallery(
        current,
        ids,
        cover,
        crypto.randomUUID(),
      );
      setRow(result);
      setQuote(null);
      setNotice(t.saved);
    });
  }
  async function remove(asset: string) {
    await run(async () => {
      const result = await listingApi.remove(
        current,
        asset,
        crypto.randomUUID(),
      );
      setRow(result);
      setQuote(null);
      setNotice(t.saved);
    });
  }
  const labels = [t.facts, t.disclosure, t.photos, t.review];
  const money = (minor: number) =>
    new Intl.NumberFormat(locale === "ar" ? "ar-LB" : "en-US", {
      style: "currency",
      currency: "USD",
    }).format(minor / 100);
  return (
    <div className="le-page">
      <header className="le-page-header">
        <div>
          <ButtonLink
            className="le-back button-secondary"
            href={scopedHref(`/${locale}/seller/listings`, organization)}
          >
            ← {t.listings}
          </ButtonLink>
          <p className="le-eyebrow">{t.eyebrow}</p>
          <h1>
            {form.brand || t.newListing} {form.model}
          </h1>
          <div className="le-inline">
            <Status row={current} t={t} />
            <small>
              {t.revision} <BidiReference>{current.revision}</BidiReference>
            </small>
            {current.is_demo && <small>{t.demo}</small>}
          </div>
        </div>
        <div className="le-actions">
          <span role="status">{dirty ? t.unsaved : notice || t.saved}</span>
          <Button
            disabled={!editable || busy || !dirty}
            onClick={() => void run(save)}
          >
            {busy ? t.working : t.save}
          </Button>
        </div>
      </header>
      <nav className="le-steps" aria-label={t.newListing}>
        {labels.map((label, i) => (
          <Button
            key={label}
            className={step === i ? "le-step-active" : "button-secondary"}
            aria-current={step === i ? "step" : undefined}
            onClick={() => setStep(i)}
          >
            <span aria-hidden="true">0{i + 1}</span>
            {label}
          </Button>
        ))}
      </nav>
      {!organization &&
        session &&
        !session.principal.permissions.includes(
          "identity.listings.publish",
        ) && (
          <div className="le-notice">
            <p>{t.verificationHint}</p>
            <ButtonLink href={`/${locale}/seller/verification`}>
              {t.verifySeller}
            </ButtonLink>
          </div>
        )}
      {Boolean(error) && (
        <Failure error={error} t={t} locale={locale} retry={reload} />
      )}
      {current.status === "publication_pending" && (
        <div className="le-notice" role="status">
          {t.pendingBody}
        </div>
      )}
      {current.is_hidden && (
        <div className="le-notice" role="status">
          {t.hidden}
        </div>
      )}
      {current.status === "published" && !current.is_hidden && (
        <div className="le-notice le-success" role="status">
          <p>{t.publishedBody}</p>
          <ButtonLink href={`/${locale}/watches/${current.id}`}>
            {t.publicWatch}
          </ButtonLink>
        </div>
      )}
      <div className="le-editor-layout">
        <div className="le-editor-main">
          {step === 0 && (
            <section className="le-panel">
              <h2>{t.facts}</h2>
              <fieldset disabled={!editable || busy}>
                <div className="le-form-grid">
                  {(["brand", "model", "reference", "location"] as const).map(
                    (name) => (
                      <label key={name}>
                        {t[name]}
                        <Input
                          value={form[name]}
                          maxLength={name === "brand" ? 100 : 160}
                          onChange={(e) => field(name, e.target.value)}
                        />
                      </label>
                    ),
                  )}
                  <label>
                    {t.year}
                    <Input
                      inputMode="numeric"
                      value={form.year ?? ""}
                      onChange={(e) => {
                        const text = normalizeDigits(e.target.value);
                        if (/^\d{0,4}$/.test(text))
                          field("year", text ? Number(text) : null);
                      }}
                    />
                  </label>
                  <label>
                    {t.price}
                    <Input
                      inputMode="decimal"
                      dir="ltr"
                      value={price}
                      onChange={(e) => {
                        setPrice(e.target.value);
                        field("price_minor", parseMinor(e.target.value));
                      }}
                      aria-invalid={price !== "" && form.price_minor === null}
                    />
                  </label>
                  <label className="le-full">
                    {t.condition}
                    <textarea
                      rows={4}
                      maxLength={2000}
                      value={form.condition}
                      onChange={(e) => field("condition", e.target.value)}
                    />
                  </label>
                  <label>
                    {t.saleMode}
                    <select
                      value={form.sale_mode}
                      onChange={(e) =>
                        field(
                          "sale_mode",
                          e.target.value as WatchFacts["sale_mode"],
                        )
                      }
                    >
                      {(["fixed_price", "auction", "offer"] as const).map(
                        (mode) => (
                          <option value={mode} key={mode}>
                            {t[mode]}
                          </option>
                        ),
                      )}
                    </select>
                  </label>
                </div>
                <h3>{t.wear}</h3>
                <div className="le-form-grid">
                  {(
                    ["case", "dial", "crystal", "bracelet", "movement"] as const
                  ).map((component) => (
                    <label key={component}>
                      {t[component]}
                      <Input
                        maxLength={1000}
                        value={form.component_wear[component] ?? ""}
                        onChange={(e) =>
                          field("component_wear", {
                            ...form.component_wear,
                            [component]: e.target.value,
                          })
                        }
                      />
                    </label>
                  ))}
                </div>
                <h3>{t.included}</h3>
                <div className="le-inline">
                  {(["box", "papers", "links"] as const).map((item) => (
                    <label className="le-check" key={item}>
                      <input
                        type="checkbox"
                        checked={form.included.includes(item)}
                        onChange={(e) =>
                          field(
                            "included",
                            e.target.checked
                              ? [...form.included, item]
                              : form.included.filter((value) => value !== item),
                          )
                        }
                      />
                      {t[item]}
                    </label>
                  ))}
                </div>
                <label className="le-check">
                  <input
                    type="checkbox"
                    checked={form.no_documents}
                    onChange={(e) => field("no_documents", e.target.checked)}
                  />
                  {t.noDocuments}
                </label>
                <label className="le-check">
                  <input
                    type="checkbox"
                    checked={form.ownership_confirmed}
                    onChange={(e) =>
                      field("ownership_confirmed", e.target.checked)
                    }
                  />
                  {t.ownership}
                </label>
              </fieldset>
            </section>
          )}
          {step === 1 && (
            <section className="le-panel">
              <h2>{t.disclosure}</h2>
              <p>{t.disclosureHint}</p>
              <fieldset disabled={!editable || busy}>
                <label>
                  {t.modifiedQuestion}
                  <select
                    value={form.modified === null ? "" : String(form.modified)}
                    onChange={(e) => {
                      field(
                        "modified",
                        e.target.value === ""
                          ? null
                          : e.target.value === "true",
                      );
                      if (e.target.value === "false") {
                        setFacts({
                          ...form,
                          modified: false,
                          modifications: [],
                        });
                        setDirty(true);
                      }
                    }}
                  >
                    <option value="">{t.choose}</option>
                    <option value="false">{t.no}</option>
                    <option value="true">{t.yes}</option>
                  </select>
                </label>
                {form.modified && (
                  <>
                    <div className="le-components">
                      {form.modifications.map((item, index) => (
                        <section className="le-component" key={index}>
                          <div className="le-form-grid">
                            <label>
                              {t.component}
                              <Input
                                maxLength={100}
                                value={item.component}
                                onChange={(e) =>
                                  modify(index, "component", e.target.value)
                                }
                              />
                            </label>
                            <label>
                              {t.provenance}
                              <select
                                value={item.provenance}
                                onChange={(e) =>
                                  modify(index, "provenance", e.target.value)
                                }
                              >
                                {(
                                  [
                                    "genuine",
                                    "aftermarket",
                                    "reworked",
                                    "unknown",
                                  ] as const
                                ).map((kind) => (
                                  <option value={kind} key={kind}>
                                    {t[kind]}
                                  </option>
                                ))}
                              </select>
                            </label>
                            <label>
                              {t.modifier}
                              <Input
                                maxLength={160}
                                value={item.modifier}
                                onChange={(e) =>
                                  modify(index, "modifier", e.target.value)
                                }
                              />
                            </label>
                            <label>
                              {t.warranty}
                              <Input
                                maxLength={160}
                                value={item.warranty_issuer}
                                onChange={(e) =>
                                  modify(
                                    index,
                                    "warranty_issuer",
                                    e.target.value,
                                  )
                                }
                              />
                            </label>
                            <label className="le-full">
                              {t.notes}
                              <textarea
                                value={item.notes}
                                maxLength={1000}
                                onChange={(e) =>
                                  modify(index, "notes", e.target.value)
                                }
                              />
                            </label>
                          </div>
                          <Button
                            className="button-secondary"
                            onClick={() =>
                              field(
                                "modifications",
                                form.modifications.filter(
                                  (_, i) => i !== index,
                                ),
                              )
                            }
                          >
                            {t.remove}
                          </Button>
                        </section>
                      ))}
                    </div>
                    <Button
                      className="button-secondary"
                      disabled={form.modifications.length >= 20}
                      onClick={() =>
                        field("modifications", [
                          ...form.modifications,
                          {
                            component: "",
                            provenance: "unknown",
                            modifier: "",
                            warranty_issuer: "",
                            notes: "",
                          },
                        ])
                      }
                    >
                      {t.addComponent} ＋
                    </Button>
                  </>
                )}
              </fieldset>
            </section>
          )}
          {step === 2 && (
            <>
              <section className="le-panel">
                <h2>{t.publicPhotos}</h2>
                <p>{t.photoHint}</p>
                <label className="le-check">
                  <input
                    type="checkbox"
                    checked={safe}
                    onChange={(e) => setSafe(e.target.checked)}
                  />
                  {t.photoSafety}
                </label>
                <label className={`le-upload ${!safe ? "le-disabled" : ""}`}>
                  {t.addPhoto}
                  <input
                    aria-label={t.addPhoto}
                    type="file"
                    accept="image/jpeg,image/png"
                    disabled={!editable || busy || !safe}
                    onChange={(e) => {
                      void fileUpload(e.target.files?.[0], "public_photo");
                      e.target.value = "";
                    }}
                  />
                </label>
                <div className="le-photo-grid">
                  {current.photo_ids.map((asset, index) => (
                    <article key={asset} className="le-photo-item">
                      <OwnerPhoto
                        listingId={id}
                        assetId={asset}
                        alt={`${form.brand} ${form.model} — ${index + 1}`}
                      />
                      <div className="le-inline">
                        <Button
                          className="button-secondary"
                          disabled={
                            !editable ||
                            busy ||
                            dirty ||
                            asset === current.cover_id
                          }
                          onClick={() => void gallery(current.photo_ids, asset)}
                        >
                          {asset === current.cover_id ? t.cover : t.makeCover}
                        </Button>
                        <Button
                          className="button-secondary"
                          aria-label={t.moveEarlier}
                          disabled={!editable || busy || dirty || index === 0}
                          onClick={() => {
                            const ids = [...current.photo_ids];
                            [ids[index - 1], ids[index]] = [
                              ids[index],
                              ids[index - 1],
                            ];
                            void gallery(ids, current.cover_id!);
                          }}
                        >
                          ↑
                        </Button>
                        <Button
                          className="button-secondary"
                          aria-label={t.moveLater}
                          disabled={
                            !editable ||
                            busy ||
                            dirty ||
                            index === current.photo_ids.length - 1
                          }
                          onClick={() => {
                            const ids = [...current.photo_ids];
                            [ids[index + 1], ids[index]] = [
                              ids[index],
                              ids[index + 1],
                            ];
                            void gallery(ids, current.cover_id!);
                          }}
                        >
                          ↓
                        </Button>
                        <Button
                          className="button-secondary"
                          disabled={!editable || busy || dirty}
                          onClick={() => void remove(asset)}
                        >
                          {t.remove}
                        </Button>
                      </div>
                    </article>
                  ))}
                </div>
              </section>
              <section className="le-panel">
                <h2>{t.privateDocuments}</h2>
                <p>{t.documentHint}</p>
                <label className="le-upload">
                  {t.addDocument}
                  <input
                    type="file"
                    aria-label={t.addDocument}
                    accept="image/jpeg,image/png,application/pdf"
                    disabled={!editable || busy}
                    onChange={(e) => {
                      void fileUpload(e.target.files?.[0], "private_document");
                      e.target.value = "";
                    }}
                  />
                </label>
                {media.error && (
                  <Failure
                    error={media.error}
                    t={t}
                    locale={locale}
                    retry={() => void media.refetch()}
                  />
                )}
                <ul className="le-document-list">
                  {media.data?.items
                    .filter((asset) => asset.kind === "private_document")
                    .map((asset, index) => (
                      <li key={asset.id}>
                        <span>
                          {t.privateDocuments} {index + 1}{" "}
                          <BidiReference>{asset.mime}</BidiReference>
                        </span>
                        <Button
                          className="button-secondary"
                          onClick={() =>
                            void run(async () => {
                              const blob = await listingApi.file(id, asset.id,session);
                              if (!alive.current) return;
                              const url = URL.createObjectURL(blob),
                                a = document.createElement("a");
                              a.href = url;
                              a.download = "private-watch-document";
                              a.click();
                              setTimeout(() => URL.revokeObjectURL(url), 1000);
                            })
                          }
                        >
                          {t.download}
                        </Button>
                        <Button
                          className="button-secondary"
                          disabled={!editable || busy || dirty}
                          onClick={() => void remove(asset.id)}
                        >
                          {t.remove}
                        </Button>
                      </li>
                    ))}
                </ul>
              </section>
            </>
          )}
          {step === 3 && (
            <section className="le-panel">
              <h2>{t.review}</h2>
              <p>{t.complete}</p>
              <dl className="le-review">
                <div>
                  <dt>{t.saleMode}</dt>
                  <dd>{t[form.sale_mode]}</dd>
                </div>
                <div>
                  <dt>{t.price}</dt>
                  <dd>
                    <BidiReference>
                      {form.price_minor ? money(form.price_minor) : "—"}
                    </BidiReference>
                  </dd>
                </div>
                <div>
                  <dt>{t.photos}</dt>
                  <dd>{current.photo_ids.length}</dd>
                </div>
                <div>
                  <dt>{t.disclosure}</dt>
                  <dd>
                    {form.modified === null
                      ? t.choose
                      : form.modified
                        ? t.yes
                        : t.no}
                  </dd>
                </div>
              </dl>
              <p>{t.feeHint}</p>
              <Button
                className="button-secondary"
                disabled={busy || dirty || !editable}
                onClick={() =>
                  void run(async () =>
                    setQuote(
                      await listingApi.quote(current, crypto.randomUUID()),
                    ),
                  )
                }
              >
                {t.feeReview}
              </Button>
              {quote && (
                <div className="le-fee">
                  <p>
                    {t.sellerFee}:{" "}
                    <BidiReference>
                      {typeof quote.seller_commission_minor === "number"
                        ? money(quote.seller_commission_minor)
                        : "—"}
                    </BidiReference>
                  </p>
                  <p>
                    {t.buyerFee}:{" "}
                    <BidiReference>
                      {typeof quote.buyer_fee_minor === "number"
                        ? money(quote.buyer_fee_minor)
                        : "—"}
                    </BidiReference>
                  </p>
                  <small>
                    <BidiReference>{quote.rules_version}</BidiReference>
                  </small>
                </div>
              )}
              <div className="le-publish">
                <Button
                  disabled={
                    busy || dirty || !quote || current.status === "published"
                  }
                  onClick={() =>
                    void run(async () => {
                      if (!quote) return;
                      const result = await listingApi.publish(
                        current,
                        quote,
                        publicationKey.current,
                      );
                      setRow(result);
                      setFacts(result.facts);
                      setNotice(t.published);
                    })
                  }
                >
                  {busy ? t.publishing : t.publish} ↗
                </Button>
              </div>
            </section>
          )}
        </div>
        <aside className="le-editor-aside">
          <div className="le-preview">
            {current.cover_id ? (
              <OwnerPhoto
                key={current.cover_id}
                listingId={id}
                assetId={current.cover_id}
                alt={`${form.brand} ${form.model}`}
              />
            ) : (
              <div className="le-photo-frame le-photo-empty" aria-hidden="true">
                ◇
              </div>
            )}
            <div>
              <p className="le-eyebrow">{t.eyebrow}</p>
              <h2>
                {form.brand || "—"}
                <br />
                {form.model}
              </h2>
              <p>
                <BidiReference>{form.reference || "—"}</BidiReference>
              </p>
              <strong>
                <BidiReference>
                  {form.price_minor ? money(form.price_minor) : "—"}
                </BidiReference>
              </strong>
              <p>{form.location}</p>
              <Status row={current} t={t} />
            </div>
          </div>
          <p className="le-aside-note">{t.emptyBody}</p>
        </aside>
      </div>
      <footer className="le-editor-footer">
        <Button
          className="button-secondary"
          onClick={() => {
            setStep((step + 1) % 4);
            document
              .querySelector("main")
              ?.scrollTo({ top: 0, behavior: "instant" });
          }}
        >
          {labels[(step + 1) % 4]} →
        </Button>
        <Button
          disabled={busy || !dirty || !editable}
          onClick={() => void run(save)}
        >
          {busy ? t.working : t.save}
        </Button>
      </footer>
    </div>
  );
}
