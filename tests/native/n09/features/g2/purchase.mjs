import assert from 'node:assert/strict';

// Completion must record custody, independent assurance, actual receipt and the
// full protection window before requesting the same simulated seller transfer.
// No completion page or approved handover observation interface is published yet.
export async function completePurchase(ctx, purchase) {
  throw new Error(`Purchase ${purchase.order_id}: handover and release composition unavailable; connected proof deferred`);
}

export async function releasedPurchase(ctx, create, complete = completePurchase) {
  const buyer = await ctx.actor('buyer');
  const purchase = await create(ctx);
  assert.equal(purchase.actor_id, buyer.actor_id, 'The purchase must belong to the reviewing buyer');
  assert.ok(purchase.order_id && purchase.operation_id, 'A new paid purchase must have returned references');
  const released = await complete(ctx, purchase);
  assert.equal(released.order_id, purchase.order_id, 'Completion must retain the new purchase');
  assert.equal(released.actor_id, buyer.actor_id, 'Completion must retain its buyer');
  assert.equal(released.state, 'released', 'Reviews require completed release');
  assert.ok(released.operation_id, 'Completion must return the actual release reference');
  return purchase.order_id;
}
