import { NextRequest, NextResponse } from 'next/server';
export function proxy(request: NextRequest) {
  // Classify the public URL, not a mutable/normalized NextURL from routing.
  const publicUrl = new URL(request.url);
  const path = publicUrl.pathname;
  const match = /^\/(en|ar)(?=\/|$)/.exec(path);
  if (!match) {
    const locale = request.cookies.get('bt-locale')?.value === 'ar' ? 'ar' : 'en';
    const destination = new URL(publicUrl);
    destination.pathname = `/${locale}${path === '/' ? '' : path}`;
    return NextResponse.redirect(destination);
  }
  const locale = match[1];
  const internalPath = path.slice(match[0].length) || '/';
  const headers = new Headers(request.headers);
  headers.set('x-bt-locale', locale);
  headers.set('x-bt-path', internalPath);
  // Forward the same nonce into rendering and the response policy.
  const nonce = Buffer.from(crypto.randomUUID()).toString('base64');
  headers.set('x-nonce', nonce);
  const dev = process.env.NODE_ENV !== 'production';
  const csp = `default-src 'self'; script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ''}; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'${dev ? ' ws: http:' : ''}; worker-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'`;
  headers.set('Content-Security-Policy', csp);
  const destination = new URL(publicUrl);
  destination.pathname = internalPath;
  const response = NextResponse.rewrite(destination, { status: 200, request: { headers } });
  response.headers.set('Content-Security-Policy', csp);
  return response;
}
export const config = { matcher: ['/((?!api|_next|icons|sw.js|favicon.ico).*)'] };
