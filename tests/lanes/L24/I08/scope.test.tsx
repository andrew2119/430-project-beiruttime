import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { usePageRead } from '../../../../web/lib/page-speed/read';
import { AnswerArrival } from '../../../../web/lib/page-speed/arrival';
import { PageReadProvider } from '../../../../web/lib/page-speed/provider';
import { auditRead } from '../../../../web/features/audit-references/read';

function ReadProbe() {
  usePageRead(auditRead('synthetic', 'trust', {
    schema_version: 'audit-references.v1',
    operation_id: '10000000-0000-4000-8000-000000000001',
    organization_id: '20000000-0000-4000-8000-000000000001',
    after: '2026-11-01T00:00:00Z', before: '2026-11-02T00:00:00Z',
    offset: 0, limit: 20,
  }));
  return null;
}

describe('shared read composition prerequisite', () => {
  it('composes the real read and arrival under the canonical scope', () => {
    const html = renderToStaticMarkup(<PageReadProvider>
      <AnswerArrival view="audit-references"><ReadProbe/>Records</AnswerArrival>
    </PageReadProvider>);
    expect(html).toContain('data-page-answer');
    expect(html).toContain('Records');
  });
  it('requires the real shared scope before a read can reach an owner', () => {
    expect(() => renderToStaticMarkup(<ReadProbe/>)).toThrow('Page reads require the shared page scope');
  });
  it('requires the same scope for answer arrival', () => {
    expect(() => renderToStaticMarkup(<AnswerArrival view="audit-references">Records</AnswerArrival>))
      .toThrow('Page reads require the shared page scope');
  });
});
