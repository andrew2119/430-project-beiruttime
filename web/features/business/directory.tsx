"use client";
import { useState } from "react";
import { PageControls, pagedRequest } from "./pagination";
import { accessDenied, PendingRecovery, CommandForm, useCommandSnapshot, usePendingCommands } from "./command-form";
import { Checkbox } from "./checkbox";
import { useBusinessRead, directoryRead } from "./reads";
import { Button, Card, StatusBadge } from "@beirut-time/ui/foundation";
import type { OfficialBusiness } from "@contracts/contracts-identity/businesses";
import {
  BusinessEmpty,
  BusinessLoading,
  Feedback,
  Field,
  Select,
  text,
  useCopy,
  Workspace,
} from "./components";
import { useAccessContext } from "@/shell/access-context";
import { useSession } from "@/features/identity/session";
import { usePublicBusinessDraft } from "./drafts";

export default function BusinessDirectory() {
  const t = useCopy(),
    access = useAccessContext();
  const { busy, onPending, recovery } = usePendingCommands();
  const [page,setPage]=useState(1),[managedPage,setManagedPage]=useState(1);
  const session = useSession();
  const canManage =
    session?.principal.permissions.includes("identity.businesses.manage") ??
    false;
  const {
    attachForm,
    save: saveDraft,
    clear: clearDraft,
  } = usePublicBusinessDraft(access.fingerprint);
  const query = useBusinessRead({
    read: directoryRead(page),
    queryKey: ["business-v2", "businesses",page],
    queryFn: () =>
      pagedRequest<OfficialBusiness>("/v2/businesses",page,false),
  });
  const managed = useBusinessRead({
    queryKey: ["business-v2", "business-records", access.fingerprint,managedPage],
    queryFn: () =>
      pagedRequest<OfficialBusiness>("/v2/businesses/manage/records",managedPage),
    enabled: canManage,
    retry: false,
  });
  const records = useCommandSnapshot(managed.isError ? undefined : managed.data, busy, access.fingerprint, accessDenied(managed.error));
  return (
    <Workspace title={t.title} intro={t.intro}>
      {query.isPending ? (
        <BusinessLoading />
      ) : query.isError ? (
        <>
          <Feedback error={query.error} />
          <Button onClick={() => query.refetch()}>{t.retry}</Button>
        </>
      ) : !query.data.items.length ? (
        <BusinessEmpty text={t.empty} />
      ) : (
        <div className="business-grid">
          {query.data.items.map((business) => (
            <Card key={business.id} className="business-card">
              <p className="business-eyebrow">
                {business.kind === "brand" ? t.brand : t.dealer}
              </p>
              <h2>{business.public_name}</h2>
              {business.sample && <StatusBadge tone="neutral">{t.sample}</StatusBadge>}
              <p>{t.onboarded}</p>
              <ul>
                {business.capabilities.map((capability) => (
                  <li key={capability}>{t[capability]}</li>
                ))}
              </ul>
              <small>
                {t.recordRef}: <bdi dir="ltr">{business.id}</bdi>
              </small>
            </Card>
          ))}
        </div>
      )}
      {query.data && !query.isError && <PageControls answer={query.data} change={setPage} />}
    {busy && !records ? <PendingRecovery recovery={recovery} onPending={onPending} refresh={() => void managed.refetch()} /> : null}
      {records?.items.map((business) => (
        <Card key={`${business.id}:${business.revision}`}>
          <h2>{business.public_name}</h2>
          <p>
            {t[business.state]} · {t.revision} {business.revision}
          </p>
          <CommandForm disabled={busy} onPending={onPending}
            onComplete={() => { void query.refetch(); void managed.refetch(); }}
            submit={(data, operation) => operation.membership(`/v1/businesses/${business.id}`, {
              revision: business.revision,
              state: business.state === "active" ? "revoked" : "active",
              reason: text(data, "reason"),
            }, "PATCH")}
          >
            <Field
              name="reason"
              label={t.reason}
              minLength={5}
              maxLength={500}
            />
          </CommandForm>
        </Card>
      ))}
      <Feedback error={managed.error} />
      {records && <PageControls answer={records} change={setManagedPage} disabled={busy} />}
      <Card>
        <h2>{t.onboard}</h2>
        <p>{t.operatorOnly}</p>
        {canManage && (
          <CommandForm disabled={busy} onPending={onPending}
            formRef={attachForm}
            onChange={saveDraft}
            onComplete={() => {
              clearDraft();
              void query.refetch();
              void managed.refetch();
            }}
            submit={(data, operation) => operation.membership("/v1/businesses", {
              legal_name: text(data, "legal_name"),
              public_name: text(data, "public_name"),
              kind: text(data, "kind"),
              capabilities: data.getAll("capabilities"),
              assurance_reference: text(data, "assurance"),
              reason: text(data, "reason"),
              sample: data.get("sample") === "on",
              confirmation_ref: text(data, "confirmation_ref") || null,
              confirmed_scope: data.getAll("confirmed_scope"),
            })}
          >
            <Field name="legal_name" label={t.legalName} minLength={2} />
            <Field
              name="public_name"
              label={t.publicName}
              minLength={2}
              maxLength={120}
            />
            <Select
              name="kind"
              label={t.kind}
              options={[
                { value: "dealer", label: t.dealer },
                { value: "brand", label: t.brand },
              ]}
            />
            <Field
              name="assurance"
              label={t.assurance}
              minLength={5}
              maxLength={160}
            />
            <fieldset className="business-checks">
              <legend>{t.scope}</legend>
              {(["sales", "customization", "servicing"] as const).map(
                (capability) => (
                  <Checkbox key={capability}
                      name="capabilities"
                      value={capability}
                      defaultChecked={capability === "sales"}
                    >{t[capability]}</Checkbox>
                ),
              )}
            </fieldset>
            <Field name="confirmation_ref" label={t.confirmationReference} required={false} maxLength={36} />
            <fieldset className="business-checks">
              <legend>{t.confirmedScope}</legend>
              <p>{t.confirmationHelp}</p>
              {(["sales", "customization", "servicing"] as const).map(capability => (
                <Checkbox key={capability} name="confirmed_scope" value={capability}>
                  {t[capability]}
                </Checkbox>
              ))}
            </fieldset>
            <Field
              name="reason"
              label={t.reason}
              minLength={5}
              maxLength={500}
            />
            <Checkbox name="sample" className="business-check">{t.sampleInput}</Checkbox>
          </CommandForm>
        )}
      </Card>
    </Workspace>
  );
}
