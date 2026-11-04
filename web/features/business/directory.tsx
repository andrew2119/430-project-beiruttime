"use client";
import { useQuery } from "@tanstack/react-query";
import { AnimatedList, BidiReference, Button, Card, Checkbox, StatusBadge } from "@beirut-time/ui";
import type { OfficialBusiness } from "@contracts/contracts-identity/businesses";
import { businessRequest, command } from "./transport";
import {
  BusinessEmpty,
  BusinessLoading,
  Feedback,
  Field,
  Select,
  Submit,
  text,
  useAction,
  useCopy,
  Workspace,
} from "./components";
import { useAccessContext } from "@/shell/access-context";
import { useSession } from "@/features/identity/session";
import { usePublicBusinessDraft } from "./drafts";

export default function BusinessDirectory() {
  const t = useCopy(),
    access = useAccessContext(),
    action = useAction();
  const session = useSession();
  const canManage =
    session?.principal.permissions.includes("identity.businesses.manage") ??
    false;
  const {
    attachForm,
    save: saveDraft,
    clear: clearDraft,
  } = usePublicBusinessDraft(access.fingerprint);
  const query = useQuery({
    queryKey: ["l02", "businesses"],
    queryFn: () =>
      businessRequest<{ items: OfficialBusiness[] }>(
        "/v1/businesses",
        {},
        false,
      ),
  });
  const managed = useQuery({
    queryKey: ["l02", "business-records", access.fingerprint],
    queryFn: () =>
      businessRequest<{ items: OfficialBusiness[] }>(
        "/v1/businesses/manage/records",
      ),
    enabled: canManage,
    retry: false,
  });
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
        <AnimatedList items={query.data.items} getKey={business => business.id} grid className="business-grid">
          {(business) => (
            <Card key={business.id} className="business-card">
              <p className="business-eyebrow">
                {business.kind === "brand" ? t.brand : t.dealer}
              </p>
              <h2>{business.public_name}</h2>
              {business.sample && <StatusBadge hue="neutral">{t.sample}</StatusBadge>}
              <p>{t.onboarded}</p>
              <ul>
                {business.capabilities.map((capability) => (
                  <li key={capability}>{t[capability]}</li>
                ))}
              </ul>
              <small>
                {t.recordRef}: <BidiReference>{business.id}</BidiReference>
              </small>
            </Card>
          )}
        </AnimatedList>
      )}
      {managed.data?.items.map((business) => (
        <Card key={`${business.id}:${business.revision}`}>
          <h2>{business.public_name}</h2>
          <p>
            {t[business.state]} · {t.revision} {business.revision}
          </p>
          <form
            className="business-form"
            onSubmit={(event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              void action.run(async () => {
                await command(
                  `/v1/businesses/${business.id}`,
                  {
                    revision: business.revision,
                    state: business.state === "active" ? "revoked" : "active",
                    reason: text(data, "reason"),
                  },
                  "PATCH",
                );
                await Promise.all([query.refetch(), managed.refetch()]);
              });
            }}
          >
            <Field
              name="reason"
              label={t.reason}
              minLength={5}
              maxLength={500}
            />
            <Submit
              pending={action.pending}
              label={business.state === "active" ? t.revoke : t.reactivate}
            />
          </form>
        </Card>
      ))}
      <Feedback error={managed.error} />
      <Card>
        <h2>{t.onboard}</h2>
        <p>{t.operatorOnly}</p>
        {canManage && (
          <form
            ref={attachForm}
            onChange={saveDraft}
            className="business-form"
            onSubmit={(event) => {
              event.preventDefault();
              const form = event.currentTarget;
              const data = new FormData(form);
              void action.run(async () => {
                await command("/v1/businesses", {
                  legal_name: text(data, "legal_name"),
                  public_name: text(data, "public_name"),
                  kind: text(data, "kind"),
                  capabilities: data.getAll("capabilities"),
                  assurance_reference: text(data, "assurance"),
                  reason: text(data, "reason"),
                  sample: data.get("sample") === "on",
                });
                form.reset();
                clearDraft();
                await Promise.all([query.refetch(), managed.refetch()]);
              });
            }}
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
            <Field
              name="reason"
              label={t.reason}
              minLength={5}
              maxLength={500}
            />
            <Checkbox name="sample" className="business-check">{t.sampleInput}</Checkbox>
            <Submit pending={action.pending} label={t.onboard} />
            <Feedback error={action.error} success={action.success} />
          </form>
        )}
      </Card>
    </Workspace>
  );
}
