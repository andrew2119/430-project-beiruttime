# Business commands v2

These additive contracts describe private listing-possession and ordinary staff
commands. They do not register HTTP endpoints. The operation table in
`current_v2.py` is the transport lookup reserved for runtime composition.

The runtime must authenticate the actor, load current business, membership,
platform ceiling, assignment, watch identity and listing revision, and execute
one serialized transaction. Request-supplied authority flags are forbidden.
The pure transition modules accept facts loaded by that boundary. They cannot
make a projection authoritative.

Every command requires a stable operation reference. Persist a request digest,
actor, business, subject, watch, source revisions, result and resulting revision
in the same transaction as history and outbox. An identical retry returns that
receipt after current read authorization; conflicting reuse denies. Lost response
recovery uses the operation lookup. Unknown commit stays pending and retries the
same reference. Reordered revisions deny without mutation. Dependency timeout
returns unavailable with the same reference, never approval or an empty job list.

Possession issue generates six random digits on the server. Persist only its
challenge-bound digest; deliver the code privately with a synthetic label. A code
is single use and submission must occur strictly before issue plus 24 hours.
The private photo must belong to the current seller and listing. Submission
requires a current approved seller. Review requires a qualified assigned person
other than that seller. Reassignment increments assignment and record revisions
and removes the prior reviewer's evidence access immediately. Correction and
rejection require a fresh challenge. Changed watch identity or relisting changes
the source revision and invalidates the old verdict. Public validation exposes
only verdict and source revisions, never code, evidence reference or photo.

An ordinary administrator has an active selected-business membership and a
platform-set permission ceiling. Ordinary grants exclude staff administration,
platform and reviewer permissions. Self-intervention and intervention on any
privileged membership deny. Removing job permission, suspending or removing a
responsible colleague requires current complete responsibility facts and a current
qualified replacement in the same business. Apply replacement revisions and the
membership change atomically, or apply neither. Business reactivation does not
reactivate a suspended or revoked member.

Synthetic capability declarations never imply real commercial permission. Real
activation requires a recorded confirmation covering the exact offering scope.
The existing onboarding command accepts `confirmation_ref` (a private record UUID)
and `confirmed_scope` (the exact selected capabilities). Only a currently permitted
platform operator may record this business confirmation. Non-synthetic onboarding
without it, or with a different scope, returns `business_confirmation_required`
before any write. The same transaction records its reference, scope, recording
operator and server time. Reactivation checks the retained confirmation again;
legacy non-synthetic records without confirmation cannot reactivate. Synthetic
onboarding never manufactures a real confirmation. Confirmation details are absent
from public responses and events. These fields are included in the existing request
digest; identical committed retries return the existing receipt after authorization,
and changed confirmation fields require a different operation reference.

## Required response translations

| State | English | Arabic |
| --- | --- | --- |
| pending | Pending review. Keep this action reference. | المراجعة قيد الانتظار. احتفظ بمرجع هذا الإجراء. |
| denied | Current permission is required. | يلزم إذن ساري المفعول. |
| stale | Reload the current record and review your changes. | أعد تحميل السجل الحالي وراجع تغييراتك. |
| unavailable | Temporarily unavailable. Retry the same action. | غير متاح مؤقتًا. أعد محاولة الإجراء نفسه. |
| expired | Request a new possession code and photo. | اطلب رمز حيازة وصورة جديدين. |
| replacement | Select a responsible replacement before continuing. | اختر بديلًا مسؤولًا قبل المتابعة. |

The deterministic local tests exercise transitions only. Runtime transaction,
authenticated producer, private-file ownership, retention, event delivery and
connected timeout/restart proofs remain required before connected acceptance.

## Private workspace reads

`workspace_v2.ts` defines the additive read shapes. GET listing-possession
`/v2/listing-possession/listings/{watch_id}?listing_revision=N` loads the current
seller, watch and listing revisions and permitted controls. It returns 403 on
lost access and 409 on a changed listing. GET `/v2/listing-possession/history/{watch_id}`
returns a private `Page<ProofHistory>`. GET `/v2/business-staff/workspaces/{business_id}`
returns `StaffWorkspace`, with the current actor, platform ceiling, complete active
responsibilities and qualified replacements. All paged reads accept `page` and
`page_size` (maximum 25) and return server totals. Replacement options are complete
for the selected business or the workspace is unavailable. Commands reload these
facts in the serialized boundary; visible controls confer no permission.

Private photo POST `/v2/listing-possession/photos` accepts multipart `photo`,
`watch_id`, `listing_revision` and `challenge_id` with an Idempotency-Key.
Only the seller can upload for its current issued challenge. It returns an
access-controlled `evidence_ref`, binds ownership and listing, strips metadata,
validates the image and applies retention. Repeating the same key/file returns
the same reference; changing bytes or binding denies. No photo enters public
reads or receipts. GET `/v2/listing-possession/evidence/{watch_id}` checks current
assignment before returning the private photo. Codes are delivered only by the
labelled synthetic delivery path, never by these reads.

Staff requests also bind `ceiling_revision`, complete `job_revisions` and
`replacement_revision`; changed responsibilities or qualifications deny stale
rather than replacing against an old screen. The runtime adapter verifies those
fields before invoking the pure transition. GET operation lookup returns a
`BusinessResult` only after current read authorization. A 404 does not establish
that a prior command failed; retry the original immutable request.

`BusinessResult.operation_state` distinguishes an unresolved command (`pending`)
from an acknowledged transaction (`committed`). A committed listing submission
can have workflow `state:pending` while its assigned review is outstanding. It
is safe to reload that committed revision. Unresolved operations keep their
original request, private file and reference mounted; selection, pagination and
reload controls remain disabled until resolution or a definitive rejection.

## Bounded directory and person-review reads

The additive GET reads `/v2/businesses`, `/v2/businesses/manage/records`,
`/v2/businesses/{business_id}/memberships`, `/v2/private-reviews` and
`/v2/private-reviews/mine` return `Page<T>` with existing version-one row shapes,
current read permission and deterministic ordering by record identifier after
the primary sort. They accept one-based `page` and `page_size=25`. Totals are
server counts under the same read scope, never a count of a truncated response.
The first directory read alone is public. List reads never include private
files. Missing paging metadata is unavailable, not an invented complete list.

GET `/v2/private-reviews/{review_id}` preserves current applicant/assigned-reviewer
access and returns `PersonReviewHistory`, with `history_total` counted on the
server and at most 25 history rows. `before_revision` requests older rows; a null
`history_before_revision` ends the list. No client-invented total substitutes for
that read. The directory, managed records, membership, review queue and person-history
reads are implemented in the existing module route exports. Their database and
authenticated connected acceptance remain required. The listing-possession and
ordinary staff workspace boundaries still require runtime composition.

## Existing platform membership commands

The version-one membership edit boundary has no current job responsibility
provider. It denies suspension, revocation, capability removal, qualification
removal and scope changes with `responsibilities_unavailable` before mutation.
Such changes require the atomic replacement boundary; platform permission does
not waive that requirement. Identical committed retries still return the stored
receipt after current authorization.

Platform membership forms retain the original serialized request and operation
reference in memory until acknowledgement or definitive rejection. Recovery
replays that exact version-one command with its original Idempotency-Key; it does
not use the version-two lookup. Uncertain results block other platform membership
commands, selection and pagination. Current access changes discard private forms.

## Contact verification recovery

POST `/v1/contacts/challenges/{challenge_id}/verify` requires an Idempotency-Key.
The serialized contact transaction stores successful contact responses and failed verification outcomes in the
existing subject-scoped operation receipt table, bound to the challenge and
normalized code digest. It never stores the code in a receipt. A failed attempt and its receipt commit together;
replaying that reference returns the same error without spending another attempt. Identical replay
checks current signed-in authority before returning that response, even after the
challenge is consumed or expires. Conflicting reference reuse denies without
changing the contact or emitting another event. An uncertain response keeps the
original code, challenge and operation reference in memory; retry uses that exact
request and refreshes current contacts after acknowledgement. A definitive failed
verification allows another code attempt under a new reference. The ten-minute
expiry, five wrong attempts and challenge request limits remain unchanged.

Person-review verdict forms retain their original version-one request and action
reference until acknowledgement or definitive rejection. Retry and recovery replay
that exact request. Unresolved verdicts hold selection, pagination and reassignment;
failed or newer reads cannot replace the mounted verdict form.
