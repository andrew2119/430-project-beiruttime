"use client";
import { PageControls, pagedRequest } from "./pagination";
import { useState } from "react";
import { useBusinessRead } from "./reads";
import { Card, StatusBadge } from "@beirut-time/ui/foundation";
import { Checkbox } from "./checkbox";
import type { Membership } from "@contracts/contracts-identity/businesses";
import { useAccessContext } from "@/shell/access-context";
import { useSession } from "@/features/identity/session";
import { accessDenied, PendingRecovery, CommandForm, useCommandSnapshot, usePendingCommands } from "./command-form";
import {
  BusinessEmpty,
  BusinessLoading,
  Feedback,
  capabilityLabel,
  Field,
  Select,
  Submit,
  text,
  useCopy,
} from "./components";
export function PlatformMemberships() {
  const t = useCopy(),
    access = useAccessContext(),
    [business, setBusiness] = useState("");
  const [page,setPage]=useState(1);
  const {busy, onPending: setBusy, recovery} = usePendingCommands();
  const session = useSession();
  const canManage =
    session?.principal.permissions.includes("identity.membership.manage") ??
    false;
  const query = useBusinessRead({
    queryKey: ["business-v2", "memberships", access.fingerprint, business,page],
    queryFn: () =>
      pagedRequest<Membership>(`/v2/businesses/${encodeURIComponent(business)}/memberships`,page),
    enabled: !!business,
    retry: false,
  });
  const data = useCommandSnapshot(
    query.isError ? undefined : query.data,
    busy, access.fingerprint, accessDenied(query.error),
  );
  if (!canManage) return null;
  return (
    <section aria-label={t.platformMembership}><h2>{t.platformMembership}</h2><p>{t.grantHelp}</p>
      <Card>
        <form
          className="business-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (busy) return;
            setPage(1); setBusiness(text(new FormData(event.currentTarget), "business"));
          }}
        >
          <Field name="business" label={t.businessId} maxLength={36} />
          <Submit pending={query.isFetching || busy} label={t.reload} />
        </form>
        <Feedback error={query.error} />
      </Card>
      {business && query.isPending && <BusinessLoading />}
    {busy && !data ? <PendingRecovery recovery={recovery} onPending={setBusy} refresh={() => void query.refetch()} /> : null}
      {data?.items.length === 0 && <BusinessEmpty text={t.noMembers} />}
      {data?.items.map((member) => (
        <Card key={`${member.id}:${member.revision}`}>
          <h2>
            <bdi dir="ltr">{member.subject_id}</bdi>
          </h2>
          <p>
            <StatusBadge tone={member.state === "active" ? "success" : "warning"}>{t[member.state]}</StatusBadge> · {t.revision} {member.revision}
          </p>
          <p>{member.intervention_scope}</p>
          <p>
            {member.capabilities
              .map((capability) => capabilityLabel(capability, t))
              .join(" · ")}
          </p>
          {canManage && (
            <CommandForm disabled={busy} onPending={setBusy} onComplete={() => void query.refetch()}
              submit={(data, operation) => operation.membership(`/v1/memberships/${member.id}`, {
                revision: member.revision, state: text(data, "state"),
                capabilities: data.getAll("capabilities"),
                qualifications: text(data, "qualifications").split(",").map(item => item.trim()).filter(Boolean),
                intervention_scope: text(data, "scope"), reason: text(data, "reason"),
              }, "PATCH")}>
              <Select
                name="state"
                label={t.decision}
                defaultValue={member.state}
                options={(["active", "suspended", "revoked"] as const).map(
                  (state) => ({ value: state, label: t[state] }),
                )}
              />
              <Field
                name="scope"
                label={t.scope}
                minLength={5}
                maxLength={300}
                defaultValue={member.intervention_scope}
              />
              <Field
                name="qualifications"
                label={t.qualifications}
                required={false}
                maxLength={1300}
                defaultValue={member.qualifications.join(", ")}
              />
              <fieldset className="business-checks">
                <legend>{t.scope}</legend>
                {[
                  "business.stock.write",
                  "business.jobs.write",
                  "business.records.read",
                  "business.staff.manage",
                ].map((capability) => (
                  <Checkbox key={capability} name="capabilities" value={capability}
                    defaultChecked={member.capabilities.includes(capability)}>
                    {capabilityLabel(capability, t)}
                  </Checkbox>
                ))}
              </fieldset>
              <Field
                name="reason"
                label={t.reason}
                minLength={5}
                maxLength={500}
              />
            </CommandForm>
          )}
        </Card>
      ))}
      {data && <PageControls answer={data} change={setPage} disabled={busy} />}
      {canManage && (
        <Card>
          <h2>{t.grant}</h2>
          <CommandForm disabled={busy} onPending={setBusy} onComplete={() => void query.refetch()}
            submit={(data, operation) => operation.membership("/v1/memberships", {
              business_id: text(data, "business"), subject_id: text(data, "subject"),
              capabilities: data.getAll("capabilities"),
              qualifications: text(data, "qualifications").split(",").map(item => item.trim()).filter(Boolean),
              intervention_scope: text(data, "scope"), reason: text(data, "reason"),
            })}>
            <Field name="business" label={t.businessId} maxLength={36} />
            <Field name="subject" label={t.subjectId} maxLength={36} />
            <Field name="scope" label={t.scope} minLength={5} maxLength={300} />
            <Field
              name="qualifications"
              label={t.qualifications}
              required={false}
              maxLength={1300}
            />
            <fieldset className="business-checks">
              <legend>{t.scope}</legend>
              {[
                "business.stock.write",
                "business.jobs.write",
                "business.records.read",
                "business.staff.manage",
              ].map((capability) => (
                <Checkbox key={capability} name="capabilities" value={capability}>
                  {capabilityLabel(capability, t)}
                </Checkbox>
              ))}
            </fieldset>
            <Field
              name="reason"
              label={t.reason}
              minLength={5}
              maxLength={500}
            />
          </CommandForm>
        </Card>
      )}
    </section>
  );
}
