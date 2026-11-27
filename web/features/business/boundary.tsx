"use client";
import { Fragment, type ReactNode } from "react";
import { useAccessContext } from "@/shell/access-context";
import { Button, ButtonLink, State } from "@beirut-time/ui/foundation";
import { useLocale } from "@/shell/locale-context";
import {
  refreshSession,
  useSession,
  useSessionState,
} from "@/features/identity/session";
import { BusinessLoading, useCopy, Workspace } from "./components";
/** Private forms remount on actual account/org/access changes, not theme changes. */
export default function BusinessBoundary({
  children,
  publicWorkspace = false,
}: {
  children: ReactNode;
  publicWorkspace?: boolean;
}) {
  useSession();
  const state = useSessionState();
  const access = useAccessContext();
  const t = useCopy();
  const locale = useLocale();
  // Do not admit typing into a private form before cookie restoration settles:
  // the ensuing identity boundary must not erase an in-flight user's input.
  // Public business discovery remains available during an Identity outage.
  if (!publicWorkspace && state !== "authenticated") {
    return (
      <Workspace title={t.private} intro={t.contactIntro}>
        {state === "restoring" ? (
          <BusinessLoading />
        ) : state === "unavailable" ? (
          <div role="alert"><State kind="error" title={t.retry} body={t.unavailable}>
            <Button onClick={() => void refreshSession().catch(() => {})}>
              {t.retry}
            </Button>
          </State></div>
        ) : (
          <State title={t.signin} body={t.contactIntro}><ButtonLink href={`/${locale}/account`}>{t.signin}</ButtonLink></State>
        )}
      </Workspace>
    );
  }
  return (
    <Fragment key={access.fingerprint ?? "signed-out"}>{children}</Fragment>
  );
}
