"use client";
import { Fragment, type ReactNode } from "react";
import { useAccessContext } from "@/shell/access-context";
import { useSession } from "@/features/identity/session";
/** Private forms remount on actual account/org/access changes, not theme changes. */
export default function BusinessBoundary({
  children,
}: {
  children: ReactNode;
}) {
  useSession();
  const access = useAccessContext();
  return (
    <Fragment key={access.fingerprint ?? "signed-out"}>{children}</Fragment>
  );
}
