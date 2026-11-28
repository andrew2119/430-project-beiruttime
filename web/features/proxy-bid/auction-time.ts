const NANOSECONDS_PER_SECOND = 1_000_000_000n;
const MAX_DURATION = 90n * 86_400n * NANOSECONDS_PER_SECOND;

function utcInstant(value: unknown) {
  if (typeof value !== 'string') return null;
  const parts = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(?:Z|\+00:00)$/.exec(value);
  if (!parts) return null;
  const milliseconds = Date.parse(parts[1] + 'Z');
  if (!Number.isFinite(milliseconds) || !new Date(milliseconds).toISOString().startsWith(parts[1] + '.')) return null;
  return BigInt(milliseconds) * 1_000_000n + BigInt((parts[2] ?? '').padEnd(9, '0'));
}

export function auctionTiming(startsAt: unknown, endsAt: unknown, serverTime: unknown) {
  const start = utcInstant(startsAt), end = utcInstant(endsAt), now = utcInstant(serverTime);
  if (start === null || end === null || now === null || end <= start || end - start > MAX_DURATION) return null;
  const status = now < start ? 'scheduled' : now < end ? 'live' : 'ended';
  const left = status === 'scheduled' ? start - now : end - now;
  const seconds = left <= 0n ? 0 : Number((left + NANOSECONDS_PER_SECOND - 1n) / NANOSECONDS_PER_SECOND);
  const millisecondsUntilEnd = end <= now ? 0 : Number((end - now + 999_999n) / 1_000_000n);
  return {status, seconds, millisecondsUntilEnd};
}

const MAX_TIMER_DELAY = 2_147_483_647;

/** Hide a shortcut when the last observed server window has elapsed. This does not admit a bid. */
export function observeAuctionEnd(millisecondsUntilEnd:number,answerAge:number,onEnd:()=>void) {
  const target = performance.now() + Math.max(0,millisecondsUntilEnd-answerAge);
  let timer:ReturnType<typeof setTimeout>|undefined;
  function check() {
    const remaining = Math.ceil(target-performance.now());
    if(remaining<=0) onEnd();
    else timer = setTimeout(check,Math.min(remaining,MAX_TIMER_DELAY));
  }
  check();
  return () => {if(timer!==undefined) clearTimeout(timer);};
}
