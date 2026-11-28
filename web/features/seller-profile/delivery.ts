import sellerRegistration from './delivery-contract.json';
export { sellerRegistration };

export const sellerDelivery = {
 route: sellerRegistration.route,
 read: sellerRegistration.read,
 key: ['subject_id', 'page', 'operation_id'],
 warming: 'deferred',
 retainedAnswers: 'deferred',
 refreshContent: 'deferred pending current-scope invalidation',
 placeholder: 'canonical PageLoading while current permission is checked',
 arrival: 'root shell; no additional motion',
 firstFrame: 'root theme and direction',
 proof: 'owed',
} as const;
