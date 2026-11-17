# A new page, from the shared foundation

Start an unlisted read-free page from the repository root:

```
pnpm --filter beirut-time-web new:page -- notes "Collector notes" "ملاحظات الجامع" "Your English content" "المحتوى العربي" "This page has no server data."
```

The command creates a thin bilingual page with branded metadata, the actual shared PageFrame/PageHeader/PageBody composition, and its delivery-contract row. The internal area's shared loading and error boundaries apply. Existing destinations are never replaced. Review the generated copy; do not put invented market answers into an unfinished feature. The internal prefix is the current adoption boundary, not an access control.

For a server-backed page, follow the working composition in `web/internal/page/view.tsx`, its single neutral definition in `reads.ts`, and the registered `page-demo` warm in `web/lib/page-speed/pages.ts`. A new real question needs its own reviewed definition, safe/open-only policy and page entry. The mounted view and the warm must use exactly the same key/call; never call a mutation or audited read on intent. Do not copy the synthetic example endpoint into a feature. Session/access fences still apply even to an answer already on its way.

Every page starts with:

1. One shared frame/header, genuine loading/empty/error faces and an explicit title in both languages.
2. Full destination code and server payload prefetch, never loading-boundary-only readiness.
3. First reads on intent, one access-partitioned memory cache, retained content while refreshing, and a placeholder only without an answer.
4. One answer arrival per view/access; no refresh, filter, revisit or keyboard replay. No route/locale key around editable children.
5. A row in the shared page table with the exact source, content selector, read policy and a reason for no reads. Measurements start as **owed**. No new page can opt into frozen migration debt.
6. Named focused tests, zero-warning lint/types/source/page-contract checks, the shared worst-case data, and the production page-size comparison. Browser, device, emitted-chunk and press-time measurements remain owed until separately performed.

Draw new elements on the component board first. Reuse that approved composition directly; a second private recipe is not a starting template. Sprint 1 pages remain in `web/tests/page-migration.json` with exact bytes and their rebuild reason, not passing speed verdicts.
