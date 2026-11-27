"use client";
import { useId, useState, type ReactNode } from "react";
import { Button, ButtonLink, Input, RowSkeleton, State } from "@beirut-time/ui/foundation";
import { usePathname } from "next/navigation";
import { PageHeader, PageFrame, PageBody } from "@/shell/foundation/page";
import { fieldLimits } from "./field-limits";
import { CanonicalSelect as FormSelect } from "./canonical-select";
import { useSession } from "@/features/identity/session";
import { useLocale } from "@/shell/locale-context";
import { ApiError } from "@/lib/api/client";
import en from "./en.json";
import ar from "./ar.json";
export function useCopy() {
  return useLocale() === "ar" ? ar : en;
}
export function capabilityLabel(
  capability: string,
  t: ReturnType<typeof useCopy>,
) {
  const labels: Record<string, string> = {
    "business.stock.write": t.stockWrite,
    "business.jobs.write": t.jobsWrite,
    "business.records.read": t.recordsRead,
    "business.staff.manage": t.staffManage,
  };
  return labels[capability] ?? capability;
}
export function Workspace({
  title,
  intro,
  children,
}: {
  title: string;
  intro: string;
  children: ReactNode;
}) {
  const t = useCopy(),
    locale = useLocale();
  const pathname = usePathname().replace(/^\/(en|ar)(?=\/|$)/, "");
  const session = useSession();
  const entries = [
    { id: "/business", label: t.directory, visible: true },
    { id: "/business/contacts", label: t.contacts, visible: !!session },
    { id: "/business/review-history", label: t.myReviewHistory, visible: !!session },
    { id: "/business/membership", label: t.membership, visible: !!session },
    { id: "/operations/verification", label: t.operations, visible: session?.principal.roles.includes("operator") || session?.principal.permissions.includes("identity.private-seller.review") },
  ].filter(item => item.visible).map(item => ({ ...item, href: `/${locale}${item.id}` }));
  return (
    <PageFrame>
      <PageHeader title={title} lead={intro} tabs={<nav className="business-tabs" aria-label={t.private}>{entries.map(entry => <ButtonLink key={entry.id} href={entry.href} variant={pathname === entry.id ? "default" : "outline"}><span aria-current={pathname === entry.id ? "page" : undefined}>{entry.label}</span></ButtonLink>)}</nav>} />
      <PageBody><div className="business-content">{children}</div></PageBody>
    </PageFrame>
  );
}
export function Field({
  label,
  name,
  type = "text",
  required = true,
  minLength,
  maxLength = 180,
  defaultValue,
  inputMode,
}: {
  label: string;
  name: string;
  type?: "text" | "email" | "tel" | "password" | "number";
  required?: boolean;
  minLength?: number;
  maxLength?: number;
  defaultValue?: string;
  inputMode?: "numeric" | "tel" | "email";
}) {
  const id = useId();
  return (
    <Input className="business-field" id={id} label={label} name={name} type={type}
      required={required} defaultValue={defaultValue} inputMode={inputMode}
      autoComplete={type === "password" ? "off" : undefined}
      ref={node => fieldLimits(node, minLength, maxLength)} />
  );
}
export function Select({
  label,
  name,
  options,
  defaultValue,
}: {
  label: string;
  name: string;
  options: { value: string; label: string }[];
  defaultValue?: string;
}) {
  const id = useId();
  return (
    <FormSelect id={id} name={name} label={label} defaultValue={defaultValue}>
      {options.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
    </FormSelect>
  );
}
export function Feedback({
  error,
  success,
}: {
  error: unknown;
  success?: boolean;
}) {
  const t = useCopy(),
    locale = useLocale();
  if (error) {
    const api = error instanceof ApiError ? error : null;
    const message =
      api?.code === "private_evidence_required" ? t.photoRequired :
      api?.status === 413 || api?.status === 415 ? t.photoRequired :
      api?.code === "invalid_credentials" ||
      api?.code === "reauthentication_required"
        ? t.passwordIncorrect
        : api?.code === "business_capability_required"
          ? t.unsupportedCapability
          : api?.code === "applicant_unavailable"
            ? t.applicantUnavailable
            : api?.code === "incomplete_application"
              ? t.evidenceIncomplete
              : api?.code === "invalid_contact"
                ? t.invalidContact
                : api?.status === 422
                  ? t.checkFields
                  : api?.status === 401
                    ? t.signin
                    : api?.status === 403
                      ? t.forbidden
                      : api?.status === 409
                        ? t.stale
                        : api?.code === "verification_failed"
                          ? t.verification_failed
                          : api?.code === "verification_limited"
                            ? t.verification_limited
                            : t.unavailable;
    return (
      <div className="business-feedback" role="alert">
        <State kind="error" title={t.retry} body={message}>
        {api?.status === 401 && api.code !== "invalid_credentials" && (
          <ButtonLink href={`/${locale}/account`}>{t.signin}</ButtonLink>
        )}
        {api?.requestId && <bdi dir="ltr">{api.requestId}</bdi>}
        </State>
      </div>
    );
  }
  return success ? (
    <p className="business-feedback" role="status">
      {t.saved}
    </p>
  ) : null;
}
export function BusinessLoading() {
  const t = useCopy();
  return <div role="status" aria-label={t.loading} aria-busy="true" className="business-loading"><span className="sr-only">{t.loading}</span>{[0, 1, 2].map(row => <RowSkeleton key={row} />)}</div>;
}
export function BusinessEmpty({ text }: { text: string }) {
  return <State title={text} body="" />;
}
export function useAction() {
  const [pending, setPending] = useState(false),
    [error, setError] = useState<unknown>(null),
    [success, setSuccess] = useState(false);
  async function run(action: () => Promise<unknown>, acknowledge = true) {
    if (pending) return;
    setPending(true);
    setError(null);
    setSuccess(false);
    try {
      await action();
      setSuccess(acknowledge);
    } catch (error) {
      setError(error);
    } finally {
      setPending(false);
    }
  }
  return { pending, error, success, run };
}
export function Submit({
  pending,
  label,
}: {
  pending: boolean;
  label: string;
}) {
  const t = useCopy();
  return (
    <Button type="submit" disabled={pending} aria-busy={pending}>
      {pending ? t.loading : label}
    </Button>
  );
}
export function text(data: FormData, key: string) {
  return String(data.get(key) ?? "").trim();
}
export function integer(data: FormData, key: string) {
  return Number(
    text(data, key).replace(/[٠-٩۰-۹]/g, (char) =>
      String(
        "٠١٢٣٤٥٦٧٨٩".includes(char)
          ? "٠١٢٣٤٥٦٧٨٩".indexOf(char)
          : "۰۱۲۳۴۵۶۷۸۹".indexOf(char),
      ),
    ),
  );
}
