import * as journeys from './journeys.mjs';

const assigned = [
  journeys.payouts, journeys.refunds, journeys.inbox, journeys.savedWatches,
  journeys.savedSearches, journeys.follows, journeys.questions, journeys.messages,
  journeys.email, journeys.push, journeys.options, journeys.requests,
  journeys.assessmentQuote, journeys.eligibility, journeys.approvals, journeys.productionChanges,
];

export const features = assigned.map((run, offset) => {
  const number = offset + 33;
  const scenario = mode => async ctx => {
    try {
      return await run(ctx, mode);
    } catch (error) {
      throw new Error(`F${number} ${mode}: ${error.message}`, { cause: error });
    } finally {
      // Do not retain a previous scenario's private request in the next page.
      await ctx.page.evaluate(() => {
        if (window.__btN09) {
          window.fetch = window.__btN09.original;
          delete window.__btN09;
        }
      });
    }
  };
  return {
    feature_id: `F${number}`, proof_id: `f${number}-proof`, proof_revision: '1',
    journey: scenario('journey'), negative: scenario('negative'), recovery: scenario('recovery'),
  };
});
