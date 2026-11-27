"use client";
import { useRef, useState } from "react";
import { useBusinessRead, contactsRead } from "./reads";
import { Button, Card, StatusBadge } from "@beirut-time/ui/foundation";
import { normalizeDigits } from "@beirut-time/i18n";
import type {
  Contacts,
  ContactChallenge,
} from "@contracts/contracts-identity/businesses";
import { useAccessContext } from "@/shell/access-context";
import { ApiError } from "@/lib/api/client";
import { businessRequest } from "./transport";
import {
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

export default function ContactDetails() {
  const t = useCopy(),
    access = useAccessContext(),
    action = useAction();
  const [localChallenge, setChallenge] = useState<
      ContactChallenge | null | undefined
    >(undefined),
    [sampleCode, setSampleCode] = useState<string | null>(null);
  const creation = useRef<{ path: string; body: string; key: string } | null>(null);
  const preparing = useRef(false);
  const [creating, setCreating] = useState(false);
  const [creationReference, setCreationReference] = useState("");
  const verification = useRef<{ path: string; body: string; key: string } | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verificationReference, setVerificationReference] = useState("");
  const query = useBusinessRead({
    read: contactsRead(access.fingerprint),
    queryKey: ["l02", "contacts", access.fingerprint],
    queryFn: () => businessRequest<Contacts>("/v1/contacts"),
    retry: false,
  });
  const [retained, setRetained] = useState<{ scope: string | null; data: Contacts | undefined }>({ scope: access.fingerprint, data: query.data });
  const [verificationDenial, setVerificationDenial] = useState<unknown>(null);
  const denied = !!verificationDenial || (query.error instanceof ApiError && [401, 403].includes(query.error.status));
  const reloadContacts = async () => {
    const answer = await query.refetch();
    if (!answer.isError) setVerificationDenial(null);
  };
  const currentContacts = denied || query.isError ? undefined : query.data;
  if (retained.scope !== access.fingerprint || (denied && retained.data !== undefined) || (currentContacts && retained.data !== currentContacts)) {
    setRetained({ scope: access.fingerprint, data: denied ? undefined : currentContacts });
  }
  const contacts = denied ? undefined : currentContacts ?? (retained.scope === access.fingerprint ? retained.data : undefined);
  // Server-acknowledged pending proof resumes after navigation. The account
  // boundary remounts this private state when identity/org/access changes.
  const challenge =
    !contacts || creating ? null : localChallenge === undefined
      ? (contacts?.pending_challenge ?? null)
      : localChallenge;
  const recoverCreation = async () => {
    const original = creation.current;
    if (!original || denied || !contacts || verifying) return;
    try {
      const result = await businessRequest<ContactChallenge>(original.path, {
        method: "POST", body: original.body,
        headers: { "Idempotency-Key": original.key },
      });
      setChallenge(result);
      creation.current = null;
      setCreating(false);
      setCreationReference("");
    } catch (error) {
      if (error instanceof ApiError && [400, 409, 422].includes(error.status)) {
        creation.current = null;
        setCreating(false);
        setCreationReference("");
      }
      throw error;
    }
  };
  return (
    <Workspace title={t.contacts} intro={t.contactIntro}>
      {!contacts && query.isPending && !creating ? (
        <BusinessLoading />
      ) : !contacts && !verifying && !creating ? (
        <>
          <Feedback error={verificationDenial ?? query.error} />
          <Button onClick={() => void reloadContacts()}>{t.retry}</Button>
        </>
      ) : (
        <>
          {(query.isError || verificationDenial) && <><Feedback error={verificationDenial ?? query.error} /><Button onClick={() => void reloadContacts()}>{t.retry}</Button></>}
          {contacts && <div className="business-grid">
            {(["email", "phone"] as const).map((channel) => (
              <Card key={channel}>
                <h2>{t[channel]}</h2>
                <p>
                  <bdi dir="ltr">{contacts[channel] ?? "—"}</bdi>
                </p>
                <StatusBadge tone={contacts[`${channel}_verified`] ? "success" : "warning"}>
                  {contacts[`${channel}_verified`]
                    ? t.verified
                    : t.unverified}
                </StatusBadge>
                {contacts[`${channel}_sample`] && (
                  <StatusBadge tone="neutral">{t.sampleVerification}</StatusBadge>
                )}
              </Card>
            ))}
          </div>}
          <Card>
            <h2>{t.requestCode}</h2>
            <form
              className="business-form"
              onSubmit={(event) => {
                event.preventDefault();
                if (preparing.current || creation.current || verification.current || verifying || action.pending || denied || !contacts) return;
                const data = new FormData(event.currentTarget);
                preparing.current = true;
                setCreating(true);
                void action.run(async () => {
                  try {
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
                    creation.current = {
                      path: "/v1/contacts/challenges",
                      body: JSON.stringify({ channel, recipient, revision: contacts.revision, proof: proof.proof }),
                      key: crypto.randomUUID(),
                    };
                    setCreationReference(creation.current.key);
                    setSampleCode(null);
                    await recoverCreation();
                  } finally {
                    preparing.current = false;
                    if (!creation.current) setCreating(false);
                  }
                });
              }}
            >
              <fieldset disabled={creating || verifying || action.pending || denied || !contacts} className="business-command-fields">
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
              </fieldset>
              <Submit pending={action.pending || creating || verifying || denied} label={t.requestCode} />
            </form>
            {creating && creationReference && (
              <div>
                <p>{t.actionReference}: <bdi dir="ltr">{creationReference}</bdi></p>
                <p>{t.operationHelp}</p>
                <Button disabled={action.pending || denied || !contacts} onClick={() => void action.run(recoverCreation)}>{t.recoverAction}</Button>
              </div>
            )}
            {challenge && (
              <div className="business-proof">
                <p>
                  {t.codeExpiry}:{" "}
                  <time dateTime={challenge.expires_at}>
                    <bdi dir="ltr">{challenge.expires_at}</bdi>
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
                        <bdi dir="ltr">{sampleCode}</bdi>
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
                    if (preparing.current || creation.current || denied) return;
                    const data = new FormData(event.currentTarget);
                    void action.run(async () => {
                      setChallenge(challenge);
                      verification.current ??= {
                        path: `/v1/contacts/challenges/${challenge.id}/verify`,
                        body: JSON.stringify({ code: text(data, "code") }),
                        key: crypto.randomUUID(),
                      };
                      setVerificationReference(verification.current.key);
                      setVerifying(true);
                      const original = verification.current;
                      try {
                        await businessRequest(original.path, {
                          method: "POST", body: original.body,
                          headers: { "Idempotency-Key": original.key },
                        });
                      } catch (error) {
                        if (error instanceof ApiError && [401, 403].includes(error.status)) {
                          setVerificationDenial(error);
                          setSampleCode(null);
                        }
                        if (error instanceof ApiError && [400, 409, 422].includes(error.status)) {
                          verification.current = null;
                          setVerifying(false);
                        }
                        throw error;
                      }
                      verification.current = null;
                      setVerifying(false);
                      setChallenge(null);
                      setSampleCode(null);
                      await query.refetch();
                    });
                  }}
                >
                  {verifying && <p>{t.operationHelp} <bdi dir="ltr">{verificationReference}</bdi></p>}
                  <fieldset disabled={verifying} className="business-command-fields">
                  <Field
                    name="code"
                    label={t.code}
                    inputMode="numeric"
                    minLength={6}
                    maxLength={6}
                  />
                  </fieldset>
                  <Submit pending={action.pending || denied} label={verifying ? t.retry : t.verify} />
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
