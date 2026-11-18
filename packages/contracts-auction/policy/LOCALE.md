# In-place locale preservation seam

Foundation extension v3; existing design components, token classes and provider API remain compatible. This is a state-preservation repair, not a new visual foundation.

Client pages read `useLocale()` and invoke `useChangeLocale()(next)` from `web/shell/locale-context.tsx`. Keep account/resource component keys independent of locale. The provider retains the same query client, child tree, operation refs and form nodes; direction and live shell labels change in place. A shared language button is reachable on the existing sidebar, including the phone menu, without navigating away from a draft.

Only the locale preference cookie and localized address are updated. Current query text and hash remain exact. There is no route refresh, form serialization, private draft cache, password storage or file-byte persistence. Native history replacement contains no form payload. Identity/access changes still clear private queries and owning feature scopes; locale preservation is never cross-person restoration.

Existing dedicated `a.locale-control` links on the same origin/page are intercepted at window capture, before old per-form navigation/save listeners. Modified clicks and unrelated destinations keep normal browser behavior. Settings uses the same action. Route focus compares the non-locale path so switching language does not reset focus or scroll.

The auction studio already consumes the live locale context and keeps unsaved private reserve, amounts, increment bands, interpreted Beirut schedule and pending operation in memory. Other page owners should consume this same hook instead of relying on an initial server locale prop or adding another language-navigation mechanism. This seam does not claim that every older page's copy has been migrated.

Focused transition tests verify exact address preservation, no serialized private payload, dedicated-link interception and modifier/unrelated-link behavior. Type and focused lint checks pass. They are not real-browser proof of file-input identity, keyboard/phone geometry or all-page bilingual copy. Those checks remain deferred under the heavy-proof hold.
