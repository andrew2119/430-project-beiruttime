'use client';
export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <html lang="en"><body><main style={{ padding: 32, fontFamily: 'system-ui' }}><h1>Beirut Time</h1><p>This page could not load. لم يتم تحميل الصفحة.</p><button onClick={reset} style={{ minHeight: 44 }}>Try again · حاول مجدداً</button></main></body></html>;
}
