# Dealer import page contract

Proposed route: `/seller/import`. The inactive `route-entry.tsx` adapter is deliberately not a page entry; route activation remains deferred. The first frame is the shared page header and empty private form. There is no initial remote read, public preview, automatic submission or speculative success. The server supplies the initial locale and theme through the existing root shell.

The operation read key is `(dealer-import.v1, access fingerprint, organization, operation reference, offset, 50)`. Reads happen only after an explicit import or pagination request. No private operation is warmed on hover or before access checks. Code warming remains with shared navigation; no second cache or provider is introduced.

The last successful answer remains in mounted memory during pagination and failed refresh, with server totals and an error next action. Identity or selected-organization changes remount the form and clear its private state. There is no browser-storage retention. Unknown submissions retain their exact operation reference and immutable body for retry. Language selection and same-route language links change the mounted locale without submitting or remounting the form.

The six speed methods have these boundaries: shared code readiness; no speculative private data on intent; mounted answer retention; content during refresh; first-load-only pending state; shared arrival motion without an added fade. Page size and first-frame timing remain unmeasured.

The shared page registry currently accepts only internal routes and its frozen migration list cannot grow. Registering this new public route requires its owner to extend the shared schema and register the exact page, private read policy and unmeasured proof status. Those files are outside this module's ownership. Until that change lands, the inactive adapter is excluded from route discovery. Rename it to the page entry only together with the shared registration change. The focused page-contract check can pass without claiming an active import route or connected page proof.
