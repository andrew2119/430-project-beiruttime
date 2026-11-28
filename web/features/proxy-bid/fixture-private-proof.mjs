export async function provePrivateMaximum(request, auction) {
  const other = 'Bearer synthetic-incumbent-token';
  const buyer = 'Bearer synthetic-visual-proof-only';
  const max = '/v1/auctions/' + auction.id + '/maximum';
  const preview = {
    subject_id: auction.id, subject_revision: auction.revision, purpose: 'bid',
    currency: 'USD', price_minor: 500000, schedule_id: 'usd-v2', source: 'sample',
  };
  async function expectResponse(path, authorization, key, body, status) {
    const result = await request(path, authorization, key, body);
    if (result.status !== status) throw new Error('Unexpected fixture response for ' + path);
    return result.body;
  }
  const quote = await expectResponse('/v1/quotes', buyer, 'test-preview', preview, 200);
  const reviewPath = '/v1/quotes/' + quote.id + '/review';
  const review = {...preview, quote_revision: quote.revision, payable_minor: quote.payable_minor};
  const command = {action:'submit_v2',command:{
    amount_minor: preview.price_minor, fee_quote_id: quote.id, expected_revision: auction.revision,
    watch_id:'00000000-0000-4000-8000-000000000016', quote_revision: quote.revision, policy_revision: String(quote.policy.revision),
  }};
  await expectResponse(reviewPath, buyer, 'test-review', {price_minor:1}, 422);
  for (const field of Object.keys(review)) {
    await expectResponse(reviewPath, buyer, 'test-review', {...review,[field]:null}, 409);
  }
  const missing = await expectResponse(reviewPath, other, 'test-review', review, 404);
  const missingRead = await expectResponse('/v1/quotes/' + quote.id, other, '', undefined, 404);
  for (const result of [missing, missingRead]) {
    if (result.error?.code !== 'not_found' || result.error.message !== 'Quote not found.')
      throw new Error('Missing quote response differs from the owner-scoped contract');
  }
  const refused = await expectResponse(max,buyer,'00000000-0000-4000-8000-000000000021',command,200);
  if (refused.state !== 'denied') throw new Error('An unreviewed quote admitted a bid');
  await expectResponse(reviewPath, buyer, 'test-review', review, 200);
  await expectResponse(reviewPath, buyer, 'test-review', review, 200);
  const operation = '00000000-0000-4000-8000-000000000022';
  const accepted = await expectResponse(max,buyer,operation,command,200);
  if (accepted.state !== 'accepted') throw new Error('The reviewed maximum was not accepted');
  const retry = await expectResponse(max,buyer,operation,command,200);
  if (retry.revision !== accepted.revision) throw new Error('Retry changed the accepted revision');
  await expectResponse(max,buyer,operation,{...command,command:{...command.command,amount_minor:500001}},409);
  const ceiling = await expectResponse(max,buyer,'',{action:'read_v2'},200);
  const otherCeiling = await expectResponse(max,other,'',{action:'read_v2'},200);
  if (ceiling.amount_minor !== preview.price_minor || otherCeiling.amount_minor !== null ||
      otherCeiling.active || ceiling.actor_id === otherCeiling.actor_id) throw new Error('Ceiling escaped buyer scope');
  await expectResponse(max,other,'',{action:'lookup_v2',operation_id:operation},404);
  await expectResponse(max,other,operation,command,403);
  const receipt = await expectResponse(max,buyer,'',{action:'lookup_v2',operation_id:operation},200);
  if (receipt.operation_id !== operation || receipt.revision !== accepted.revision) throw new Error('Wrong receipt returned');
}
