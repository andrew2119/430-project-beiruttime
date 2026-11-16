// Revoke delayed writers synchronously before the cache purge.
export function fencePrivateState(alive: {current:boolean}, target: EventTarget, onRevoke: () => void = () => {}) {
  alive.current = true;
  const revoke = () => {alive.current=false;onRevoke();};
  target.addEventListener('bt:access-change',revoke);
  return () => {target.removeEventListener('bt:access-change',revoke);revoke();};
}
