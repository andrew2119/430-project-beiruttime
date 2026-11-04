"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BidiReference, Card, Checkbox, StatusBadge } from "@beirut-time/ui";
import type { Membership } from "@contracts/contracts-identity/businesses";
import { useAccessContext } from "@/shell/access-context";
import { useSession } from "@/features/identity/session";
import { businessRequest, command } from "./transport";
import {
  BusinessEmpty,
  BusinessLoading,
  Feedback,
  capabilityLabel,
  Field,
  Select,
  Submit,
  text,
  useAction,
  useCopy,
  Workspace,
} from "./components";
export default function Memberships() {
  const t = useCopy(),
    access = useAccessContext(),
    action = useAction(),
    [business, setBusiness] = useState("");
  const session = useSession();
  const canManage =
    session?.principal.permissions.includes("identity.membership.manage") ??
    false;
  const query = useQuery({
    queryKey: ["l02", "memberships", access.fingerprint, business],
    queryFn: () =>
      businessRequest<{ items: Membership[] }>(
        `/v1/businesses/${business}/memberships`,
      ),
    enabled: !!business,
    retry: false,
  });
  return (
    <Workspace title={t.membership} intro={t.grantHelp}>
      <Card>
        <form
          className="business-form"
          onSubmit={(event) => {
            event.preventDefault();
            setBusiness(text(new FormData(event.currentTarget), "business"));
          }}
        >
          <Field name="business" label={t.businessId} maxLength={36} />
          <Submit pending={query.isFetching} label={t.reload} />
        </form>
        <Feedback error={query.error} />
      </Card>
      {business && query.isPending && <BusinessLoading />}
      {query.data?.items.length === 0 && <BusinessEmpty text={t.noMembers} />}
      {query.data?.items.map((member) => (
        <Card key={`${member.id}:${member.revision}`}>
          <h2>
            <BidiReference>{member.subject_id}</BidiReference>
          </h2>
          <p>
            <StatusBadge hue={member.state === "active" ? "green" : "orange"}>{t[member.state]}</StatusBadge> · {t.revision} {member.revision}
          </p>
          <p>{member.intervention_scope}</p>
          <p>
            {member.capabilities
              .map((capability) => capabilityLabel(capability, t))
              .join(" · ")}
          </p>
          {canManage && (
            <form
              className="business-form"
              onSubmit={(event) => {
                event.preventDefault();
                const data = new FormData(event.currentTarget);
                void action.run(async () => {
                  await command(
                    `/v1/memberships/${member.id}`,
                    {
                      revision: member.revision,
                      state: text(data, "state"),
                      capabilities: data.getAll("capabilities"),
                      qualifications: text(data, "qualifications")
                        .split(",")
                        .map((item) => item.trim())
                        .filter(Boolean),
                      intervention_scope: text(data, "scope"),
                      reason: text(data, "reason"),
                    },
                    "PATCH",
                  );
                  await query.refetch();
                });
              }}
            >
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
              <Submit pending={action.pending} label={t.save} />
            </form>
          )}
        </Card>
      ))}
      {canManage && (
        <Card>
          <h2>{t.grant}</h2>
          <form
            className="business-form"
            onSubmit={(event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              void action.run(async () => {
                await command("/v1/memberships", {
                  business_id: text(data, "business"),
                  subject_id: text(data, "subject"),
                  capabilities: data.getAll("capabilities"),
                  qualifications: text(data, "qualifications")
                    .split(",")
                    .map((item) => item.trim())
                    .filter(Boolean),
                  intervention_scope: text(data, "scope"),
                  reason: text(data, "reason"),
                });
                setBusiness(text(data, "business"));
                if (business) await query.refetch();
              });
            }}
          >
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
            <Submit pending={action.pending} label={t.grant} />
          </form>
        </Card>
      )}
      <Feedback error={action.error} success={action.success} />
    </Workspace>
  );
}
