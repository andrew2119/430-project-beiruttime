import type {MaximumIntent,MaximumQuote,MaximumReference} from './maximum-api';

type PendingReview = {key: string; quote?: MaximumQuote};
type PendingMaximum = {auctionId: string; intent: MaximumReference; review: null}
  | {auctionId: string; intent: MaximumReference; review: PendingReview};

const pendingCommands = new Map<string, PendingMaximum>();

function commandScope(scope: string, actor: string) {
  return 'buyer.maximum.v2:' + JSON.stringify([scope, actor]);
}

function readReference(record: string | null, actor: string, owner: string): PendingMaximum | null {
  if (record === null) return null;
  const {auctionId, intent, reviewKey} = JSON.parse(record);
  const identifier = (value: unknown) => typeof value === 'string' && value.length > 0 && value.length <= 100;
  if ((reviewKey !== undefined && !identifier(reviewKey)) || !identifier(auctionId) || !intent || intent.actor_id !== actor ||
      !identifier(intent.key) || !identifier(intent.watch_id) || !identifier(intent.fee_quote_id) ||
      !identifier(intent.policy_revision) || !Number.isSafeInteger(intent.revision) || intent.revision < 1 ||
      !Number.isSafeInteger(intent.quote_revision) || intent.quote_revision < 1) {
    throw new Error('Invalid pending bid reference');
  }
  const {key: operationKey, watch_id, fee_quote_id, revision, quote_revision, policy_revision} = intent;
  return {auctionId, intent: {key: operationKey, actor_id: actor, owner, watch_id, fee_quote_id,
    revision, quote_revision, policy_revision}, review: reviewKey === undefined ? null : {key: reviewKey}};
}

function operationPrefix(scope: string, actor: string) {
  return commandScope(scope, actor) + ':';
}

function operationStorageKey(scope: string, intent: MaximumReference, stage: 'review' | 'bid') {
  return operationPrefix(scope, intent.actor_id) + JSON.stringify([intent.key, stage]);
}

function migrateReference(scope: string, owner: string, actor: string) {
  const key = commandScope(scope, actor);
  for (const storage of [localStorage, sessionStorage]) {
    const record = storage.getItem(key);
    const pending = readReference(record, actor, owner);
    if (!pending) continue;
    const stage = pending.review ? 'review' : 'bid';
    const destination = operationStorageKey(scope, pending.intent, stage);
    if (localStorage.getItem(destination) === null) {
      writeReference(destination, pending.auctionId, pending.intent, pending.review?.key);
    }
    storage.removeItem(key);
  }
}

export function readPendingMaximum(scope: string, owner: string, actor: string, selectAuction: (auctionId:string)=>boolean = ()=>true): PendingMaximum | null {
  migrateReference(scope, owner, actor);
  const prefix = operationPrefix(scope, actor);
  const keys: string[] = [];
  for (let index = 0; index < localStorage.length; index++) {
    const key = localStorage.key(index);
    if (key?.startsWith(prefix)) keys.push(key);
  }
  const records = keys.flatMap(key => {
    const reference = readReference(localStorage.getItem(key), actor, owner);
    if (!reference) return [];
    if (key !== operationStorageKey(scope, reference.intent, reference.review ? 'review' : 'bid')) {
      throw new Error('Invalid pending bid reference');
    }
    return selectAuction(reference.auctionId) ? [{key, reference}] : [];
  });
  // Resolve bids before fee reviews, including when a tab closed during promotion.
  const selected = records.find(({reference}) => !reference.review) ?? records[0];
  if (!selected) return null;
  const {key, reference} = selected;
  const inMemory = pendingCommands.get(key);
  if (!reference.review && inMemory && !inMemory.review) {
    return {...reference, intent: {...inMemory.intent, owner}};
  }
  return reference.review && inMemory?.review?.key === reference.review.key && inMemory?.review?.quote
    ? {...reference, review: {...reference.review, quote: {...inMemory.review.quote, access_fingerprint: owner}}}
    : reference;
}

export function retainPendingReview(scope: string, auctionId: string, intent: MaximumIntent, review: PendingReview) {
  const pending = readPendingMaximum(scope, intent.owner, intent.actor_id, id=>id===auctionId);
  if (pending) return pending.auctionId === auctionId && pending.intent.key === intent.key && pending.review?.key === review.key;
  const key = operationStorageKey(scope, intent, 'review');
  writeReference(key, auctionId, intent, review.key);
  pendingCommands.set(key, {auctionId, intent, review});
  return true;
}

export function retainPendingMaximum(scope: string, auctionId: string, intent: MaximumIntent) {
  const reviewKey = operationStorageKey(scope, intent, 'review');
  const pending = readReference(localStorage.getItem(reviewKey), intent.actor_id, intent.owner);
  if (pending?.auctionId !== auctionId || pending.intent.key !== intent.key || !pending.review) return false;
  const bidKey = operationStorageKey(scope, intent, 'bid');
  writeReference(bidKey, auctionId, intent);
  pendingCommands.set(bidKey, {auctionId, intent, review: null});
  localStorage.removeItem(reviewKey);
  pendingCommands.delete(reviewKey);
  return true;
}

function writeReference(key: string, auctionId: string, intent: MaximumReference, reviewKey?: string) {
  const {key: operationKey, actor_id, watch_id, fee_quote_id, revision, quote_revision, policy_revision} = intent;
  localStorage.setItem(key, JSON.stringify({auctionId, reviewKey, intent: {
    key: operationKey, actor_id, watch_id, fee_quote_id, revision, quote_revision, policy_revision,
  }}));
}

export function settlePendingMaximum(scope: string, intent: MaximumReference, stage: 'review' | 'bid') {
  const reviewKey = operationStorageKey(scope, intent, 'review');
  localStorage.removeItem(reviewKey);
  pendingCommands.delete(reviewKey);
  if (stage === 'bid') {
    const bidKey = operationStorageKey(scope, intent, 'bid');
    localStorage.removeItem(bidKey);
    pendingCommands.delete(bidKey);
  }
}
