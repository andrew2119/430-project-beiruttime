# Browser session v1

Import `{ useSession, useSessionState, authenticatedRequest, refreshSession, signOut, safeReturnPath, signInHref }` from `@/features/identity/session` and `Session` from `@contracts/contracts-identity/accounts`.

`const session = useSession()` restores the HttpOnly cookie once and returns `Session | null`. `useSessionState()` distinguishes restoring, signed-out, unavailable and authenticated. Null alone can mean signed out or restoring; protected reads should call `authenticatedRequest` and render 401 as a sign-in link, 403 as denied, 409 as reload/correction and 503 as unavailable with explicit retry. Never invent demo authority. `session.principal` is the foundation CurrentPrincipal shape; `session.account` is the current account; `session.access_fingerprint` partitions query keys. Do not copy tokens into state persistence, query keys, URL strings, localStorage or sessionStorage.

`authenticatedRequest<T>(gatewayPath, RequestInit & {accessFingerprint?: string})` adds the current memory-only Bearer token, attempts one coordinated refresh after 401, preserves cancellation and uses the foundation request deadline/error parser. For JSON, supply Content-Type application/json, JSON.stringify(body) and an Idempotency-Key per logical command (retain that key for uncertain retries). Example:

```tsx
const result = await authenticatedRequest<MyDTO>('/api/web/v1/orders/v1/reservations', {
  method: 'POST', accessFingerprint: session.access_fingerprint, headers: {'Content-Type':'application/json','Idempotency-Key': operationId},
  body: JSON.stringify(command)
});
```

Pass the form/query owner's `accessFingerprint` whenever a callback can outlive a render or awaits file preparation. The wrapper rejects a stale owner before sending and fences late responses after any identity/access change; old evidence must never be submitted under a newly signed-in account.

`signInHref('/buyer','ar')` returns a localized account address with allowlisted intended destination. Account login returns there. `safeReturnPath` rejects external/protocol-relative/backslash/fragment/control-character/unowned destinations. The server still enforces actual permissions; this helper is not authorization.

Identity's account forms use `beginSession('login'|'register', JSON.stringify(command), operationId)` to serialize new sign-in with cookie refresh/logout and fence abandoned answers. Other screens normally use the sign-in link, not a second login form.

Identity calls foundation setAccessContext on restore/login/logout; private TanStack caches and draft conveniences purge on access changes. Sign-out broadcasts to same-origin tabs, fences late refresh responses, and serializes server logout after refresh cookie rotation. Backend current-principal queries always check account status/session liveness; claims carry no self-granted business/operator role.
