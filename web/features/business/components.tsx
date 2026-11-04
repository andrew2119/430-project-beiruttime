"use client";
import Link from "next/link";
import { useId, useState, type ReactNode } from "react";
import { Button, Input } from "@beirut-time/ui";
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
  return (
    <div className="business-workspace">
      <header className="business-heading">
        <p className="business-eyebrow">{t.eyebrow}</p>
        <h1>{title}</h1>
        <p>{intro}</p>
      </header>
      <nav className="business-tabs" aria-label={t.private}>
        <Link href={`/${locale}/business`}>{t.directory}</Link>
        <Link href={`/${locale}/business/contacts`}>{t.contacts}</Link>
        <Link href={`/${locale}/business/review-history`}>
          {t.myReviewHistory}
        </Link>
        <Link href={`/${locale}/business/membership`}>{t.membership}</Link>
        <Link href={`/${locale}/operations/verification`}>{t.operations}</Link>
      </nav>
      {children}
    </div>
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
  type?: string;
  required?: boolean;
  minLength?: number;
  maxLength?: number;
  defaultValue?: string;
  inputMode?: "numeric" | "tel" | "email";
}) {
  const id = useId();
  return (
    <label className="business-field" htmlFor={id}>
      <span>{label}</span>
      <Input
        id={id}
        name={name}
        type={type}
        required={required}
        minLength={minLength}
        maxLength={maxLength}
        defaultValue={defaultValue}
        inputMode={inputMode}
        autoComplete={type === "password" ? "off" : undefined}
      />
    </label>
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
    <label className="business-field" htmlFor={id}>
      <span>{label}</span>
      <select id={id} name={name} defaultValue={defaultValue}>
        {options.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
    </label>
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
        <p>{message}</p>
        {api?.status === 401 && api.code !== "invalid_credentials" && (
          <Link href={`/${locale}/account`}>{t.signin}</Link>
        )}
        {api?.requestId && <bdi dir="ltr">{api.requestId}</bdi>}
      </div>
    );
  }
  return success ? (
    <p className="business-feedback" role="status">
      {t.saved}
    </p>
  ) : null;
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
    <Button type="submit" disabled={pending}>
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
