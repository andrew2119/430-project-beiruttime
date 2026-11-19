import {auction, bidding, cancellation, delivery, dispute, fees, inspection, offer, payment,
  readFeature, reservation, returns, review, runMutation} from './journeys.mjs';

const assignments = [
  [17, review], [18, auction], [19, bidding], [20, 'policy'],
  [21, 'closing'], [22, fees], [23, reservation], [24, offer],
  [25, payment], [26, 'timeline'], [27, cancellation], [28, returns],
  [29, 'reports'], [30, inspection], [31, delivery], [32, dispute],
];

export const features = assignments.map(([number, journey]) => {
  const scenario = mode => async ctx => typeof journey === 'string'
    ? readFeature(ctx, mode, journey)
    : runMutation(ctx, mode, journey);
  return {
    feature_id: `F${number}`,
    proof_id: `f${number}-proof`,
    proof_revision: '1',
    journey: scenario('journey'),
    negative: scenario('negative'),
    recovery: scenario('recovery'),
  };
});
