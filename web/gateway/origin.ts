const developmentOrigins = 'http://localhost:3000,http://127.0.0.1:3000';

function parseOrigin(value: string): string | null {
  if (!value || /[\s,\\]/.test(value)) return null;
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.pathname !== '/' || url.search || url.hash) return null;
    return url.origin;
  } catch { return null; }
}

export function validatedBrowserOrigin(request: Request): string | null {
  // The internal bind URL/Host is not the public browser origin in Docker or behind an edge.
  const configured = process.env.BT_PUBLIC_WEB_ORIGINS ?? developmentOrigins;
  const allowed = new Set(configured.split(',').map(value => parseOrigin(value.trim())).filter((value): value is string => value !== null));
  // Enable only behind an edge that overwrites BOTH headers and prevents direct access.
  // Reject chains/ambiguous authorities; never trust these headers implicitly.
  if (process.env.BT_TRUST_FORWARDED_ORIGIN === 'true') {
    const host = request.headers.get('X-Forwarded-Host') ?? '';
    const proto = request.headers.get('X-Forwarded-Proto') ?? '';
    if (/^[A-Za-z0-9.[\]:-]+$/.test(host) && /^(http|https)$/.test(proto)) {
      const forwarded = parseOrigin(`${proto}://${host}`);
      if (forwarded) allowed.add(forwarded);
    }
  }
  const supplied = request.headers.get('Origin');
  if (!supplied) return null;
  const parsed = parseOrigin(supplied);
  return parsed !== null && supplied === parsed && allowed.has(parsed) ? parsed : null;
}
