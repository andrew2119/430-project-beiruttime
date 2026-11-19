import assert from 'node:assert/strict';

// Local contract only. The producer supplies a newly captured synthetic record;
// a browser user may only read it and request a freshly authorized destination.
// This port never supplies evidence to the connected matrix.
export async function emailContract(mode, actor, port) {
  assert.ok(['journey', 'negative', 'recovery'].includes(mode));
  const captured = await port.capture();
  assert.equal(captured.schema_version, 'transaction-email.v1');
  assert.equal(captured.actor_id, actor.actor_id);
  assert.equal(captured.synthetic, true);
  assert.equal(captured.state, 'captured');
  assert.ok(captured.operation_id);
  const operation = captured.operation_id;
  if (mode === 'negative') {
    const denied = await port.open(operation, 'buyer2');
    assert.ok([403, 404].includes(denied.status));
    assert.ok(denied.json?.error?.code);
    assert.deepEqual(Object.keys(denied.json), ['error']);
    assert.deepEqual(Object.keys(denied.json.error), ['code']);
    await port.visible('denied');
    return;
  }
  const opened = await port.open(operation, 'buyer');
  assert.equal(opened.status, 200);
  assert.deepEqual(opened.json, captured);
  await port.visible(operation);
  if (mode === 'recovery') {
    await port.reload();
    const restored = await port.open(operation, 'buyer');
    assert.equal(restored.status, 200);
    assert.deepEqual(restored.json, opened.json);
    await port.visible(operation);
  }
  const destination = await port.destination(operation);
  assert.equal(destination.status, 200);
  assert.match(destination.json.url, /^\/(inbox|prices\/[a-z0-9-]+|checkout\/[a-z0-9-]+)$/);
}
