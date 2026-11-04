"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button, Card, BidiReference } from "@beirut-time/ui";
import { normalizeDigits } from "@beirut-time/i18n";
import type {
  Contacts,
  ContactChallenge,
} from "@contracts/contracts-identity/businesses";
import { useAccessContext } from "@/shell/access-context";
import { businessRequest, command } from "./transport";
import {
  Feedback,
  Field,
  Select,
  Submit,
  text,
  useAction,
  useCopy,
  Workspace,
} from "./components";

export default function ContactDetails() {
  const t = useCopy(),
    access = useAccessContext(),
    action = useAction();
  const [localChallenge, setChallenge] = useState<
      ContactChallenge | null | undefined
    >(undefined),
    [sampleCode, setSampleCode] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["l02", "contacts", access.fingerprint],
    queryFn: () => businessRequest<Contacts>("/v1/contacts"),
    retry: false,
  });
  // Server-acknowledged pending proof resumes after navigation. The account
  // boundary remounts this private state when identity/org/access changes.
  const challenge =
    localChallenge === undefined
      ? (query.data?.pending_challenge ?? null)
      : localChallenge;
  return (
    <Workspace title={t.contacts} intro={t.contactIntro}>
      {query.isPending ? (
        <p role="status">{t.loading}</p>
      ) : query.isError ? (
        <>
          <Feedback error={query.error} />
          <Button onClick={() => query.refetch()}>{t.retry}</Button>
        </>
      ) : (
        <>
          <div className="business-grid">
            {(["email", "phone"] as const).map((channel) => (
              <Card key={channel}>
                <h2>{t[channel]}</h2>
                <p>
                  <BidiReference>{query.data[channel] ?? "—"}</BidiReference>
                </p>
                <p className="business-badge">
                  {query.data[`${channel}_verified`]
                    ? t.verified
                    : t.unverified}
                </p>
                {query.data[`${channel}_sample`] && (
                  <p className="business-badge">{t.sampleVerification}</p>
                )}
              </Card>
            ))}
          </div>
          <Card>
            <h2>{t.requestCode}</h2>
            <form
              className="business-form"
              onSubmit={(event) => {
                event.preventDefault();
                const data = new FormData(event.currentTarget);
                void action.run(async () => {
                  const channel = text(data, "channel");
                  const recipient =
                    channel === "phone"
                      ? normalizeDigits(text(data, "recipient"))
                      : text(data, "recipient").toLowerCase();
                  const proof = await businessRequest<{ proof: string }>(
                    "/v1/accounts/reauthenticate",
                    {
                      method: "POST",
                      body: JSON.stringify({
                        password: String(data.get("reauth") ?? ""),
                        purpose: "contact-change",
                        binding: `${channel}:${recipient}`,
                      }),
                    },
                  );
                  setSampleCode(null);
                  setChallenge(
                    await command<ContactChallenge>("/v1/contacts/challenges", {
                      channel,
                      recipient,
                      revision: query.data.revision,
                      proof: proof.proof,
                    }),
                  );
                });
              }}
            >
              <Select
                name="channel"
                label={t.contacts}
                options={[
                  { value: "email", label: t.email },
                  { value: "phone", label: t.phone },
                ]}
              />
              <Field
                name="recipient"
                label={`${t.email} / ${t.phone}`}
                maxLength={254}
              />
              <Field
                name="reauth"
                label={t.reauth}
                type="password"
                minLength={1}
                maxLength={128}
              />
              <Submit pending={action.pending} label={t.requestCode} />
            </form>
            {challenge && (
              <div className="business-proof">
                <p>
                  {t.codeExpiry}:{" "}
                  <time dateTime={challenge.expires_at}>
                    <BidiReference>{challenge.expires_at}</BidiReference>
                  </time>
                </p>
                {challenge.delivery_mode === "sample_simulator" ? (
                  <>
                    <p>{t.sampleDelivery}</p>
                    <Button
                      onClick={() =>
                        void action.run(async () => {
                          const response = await businessRequest<{
                            code: string;
                          }>(
                            `/v1/contacts/challenges/${challenge.id}/sample-code`,
                          );
                          setSampleCode(response.code);
                        }, false)
                      }
                    >
                      {t.showCode}
                    </Button>
                    {sampleCode && (
                      <p>
                        <BidiReference>{sampleCode}</BidiReference>
                      </p>
                    )}
                  </>
                ) : (
                  <p>{t.pendingDelivery}</p>
                )}
                <form
                  className="business-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const data = new FormData(event.currentTarget);
                    void action.run(async () => {
                      await command(
                        `/v1/contacts/challenges/${challenge.id}/verify`,
                        { code: text(data, "code") },
                      );
                      setChallenge(null);
                      setSampleCode(null);
                      await query.refetch();
                    });
                  }}
                >
                  <Field
                    name="code"
                    label={t.code}
                    inputMode="numeric"
                    minLength={6}
                    maxLength={6}
                  />
                  <Submit pending={action.pending} label={t.verify} />
                </form>
              </div>
            )}
            <Feedback error={action.error} success={action.success} />
          </Card>
        </>
      )}
    </Workspace>
  );
}
