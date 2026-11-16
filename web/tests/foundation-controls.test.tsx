import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { KeyboardEvent, KeyboardEventHandler } from 'react';
import { readFileSync } from 'node:fs';
import { Avatar, Badge, Button, ButtonLink, Card, Checkbox, Fold, ImageFrame, Input, Radio, RowSkeleton, Skeleton, State, Switch, Textarea, initialsOf } from '@beirut-time/ui/foundation';
import { usableImageSource } from '../../packages/ui/src/foundation/initials';
import { NAMES, TEXT } from './fixtures/worst-case';

const css = readFileSync(new URL('../styles/bt-components.css',import.meta.url),'utf8');
describe('canonical controls use named native semantics and stable state boxes', () => {
  it('keeps the same label and parts for idle, pending, disabled and success', () => {
    for (const state of ['idle','busy','disabled','success']) {
      const html = renderToStaticMarkup(<Button busy={state === 'busy'} disabled={state === 'disabled'} success={state === 'success'}>{TEXT.expandedLabel}</Button>);
      expect(html).toContain(TEXT.expandedLabel);
      expect(html).toContain('class="bt-button bt-pressable"');
      expect(html).toContain('bt-button-progress');
      expect(html).toContain('bt-button-result');
      expect(html).toContain('type="button"');
      if (state === 'busy') expect(html).toContain('aria-busy="true"');
      if (state === 'busy' || state === 'disabled') expect(html).toContain('disabled=""');
    }
    expect(css).toContain(':where(.bt-button[data-busy] .bt-button-label) { opacity: 0; }');
    expect(css).not.toContain('visibility: hidden');
  });
  it('disabled action links block activation without trapping Tab after a pointer focus', () => {
    const action = ButtonLink({href:'#preview',children:'Unavailable',disabled:true}), key = action.props.onKeyDown as KeyboardEventHandler<HTMLAnchorElement>, preventDefault = vi.fn(), currentTarget = {dataset:{}} as HTMLAnchorElement;
    key({key:'Tab',currentTarget,preventDefault} as unknown as KeyboardEvent<HTMLAnchorElement>);expect(preventDefault).not.toHaveBeenCalled();
    key({key:'Enter',currentTarget,preventDefault} as unknown as KeyboardEvent<HTMLAnchorElement>);expect(preventDefault).toHaveBeenCalledOnce();
  });
  it('requires named input/textarea fields with associated hints/errors and real input modes', () => {
    const input = renderToStaticMarkup(<Input id="bid" label="قيمة العرض" value="123.45" inputMode="decimal" error="تحقق من القيمة" hint="USD" />);
    expect(input).toContain('for="bid"');expect(input).toContain('id="bid"');
    expect(input).toContain('aria-describedby="bid-hint bid-error"');
    expect(input).toContain('aria-invalid="true"');expect(input).toContain('role="alert"');
    expect(input).toContain('inputMode="decimal"');
    const textarea = renderToStaticMarkup(<Textarea id="notes" label="Description" value={TEXT.description} readOnly />);
    expect(textarea).toContain(TEXT.description);expect(textarea).toContain('readOnly=""');
    expect(css).toContain('@media (max-width: 48rem), (pointer: coarse)');
    expect(css).toContain('font-size: max(1rem, 16px)');
  });
  it('checkbox, radio and switch use native inputs with linked labels and an actual full-size hit area', () => {
    const checkbox = renderToStaticMarkup(<Checkbox id="accept" label={TEXT.expandedLabel} checked />);
    expect(checkbox).toContain('type="checkbox"');expect(checkbox).toContain('for="accept"');expect(checkbox).toContain('checked=""');
    expect(renderToStaticMarkup(<Radio name="delivery" label="Collection" checked />)).toContain('type="radio"');
    expect(renderToStaticMarkup(<Switch label="تنبيهات" checked />)).toContain('role="switch"');
    expect(css).toContain(':where(.bt-check-control)');
    expect(css).toContain('inline-size: var(--bt-hit-target); block-size: var(--bt-hit-target)');
    expect(css).toContain('.bt-check:focus-visible + .bt-check-drawing');
  });
  it('empty stays quiet, loading is status and canonical errors are alerts', () => {
    expect(renderToStaticMarkup(<State title="No watches" body={TEXT.arabicTitle} />)).not.toContain('role="alert"');
    expect(renderToStaticMarkup(<State kind="loading" title="Loading" body="Please wait" />)).toContain('role="status"');
    const error = renderToStaticMarkup(<State kind="error" title="تعذر التحميل" body={TEXT.literalMarkup}><Button>Retry</Button></State>);
    expect(error).toContain('role="alert"');expect(error).toContain('&lt;b&gt;');expect(error).not.toContain('<h1');
  });
  it('fold starts at the declared state with keyboard accessibility and no second layout recipe', () => {
    const closed = renderToStaticMarkup(<Fold label="Details" open={false} onOpenChange={()=>{}}><p>{TEXT.description}</p></Fold>);
    expect(closed).toContain('aria-expanded="false"');expect(closed).toContain('inert=""');expect(closed).toContain('class="bt-fold-content"');
    expect(css).not.toContain('grid-template-rows: 0fr');
    expect(renderToStaticMarkup(<Card><Badge>Ready</Badge><Skeleton/><RowSkeleton/></Card>)).toContain('aria-hidden="true"');
  });
});

describe('whole-character initials and reserved decoded image frames', () => {
  it('keeps complete first/last lettered graphemes, ignores leading emoji and preserves emoji-only names', () => {
    expect(initialsOf(NAMES.long)).toEqual(['A','M']);
    expect(initialsOf(NAMES.arabic)).toEqual(['ن','ا']);
    expect(initialsOf(NAMES.emojiFirst)).toEqual(['P','N']);
    expect(initialsOf(NAMES.emojiOnly)).toEqual([NAMES.emojiOnly]);
    expect(initialsOf('e\u0301lan Smith')).toEqual(['E\u0301','S']);
    expect(initialsOf('ßeta')).toEqual(['S']);
    expect(initialsOf(NAMES.oneLetter)).toEqual(['J']);expect(initialsOf('   ')).toEqual([]);
  });
  it('rejects unsafe or unapproved transport without requesting a broken fallback', () => {
    for (const source of ['javascript:alert(1)','data:image/png;base64,AAAA','//example.com/a.png','http://example.com/a.png']) expect(usableImageSource(source)).toBeUndefined();
    expect(usableImageSource('/demo/watches/a.webp')).toBe('/demo/watches/a.webp');
    expect(usableImageSource('https://example.com/a.webp')).toBe('https://example.com/a.webp');
    expect(usableImageSource('http://127.0.0.1/a.webp')).toBe('http://127.0.0.1/a.webp');
  });
  it('reserves an aspect box and keeps pixels invisible until decode, with a visible named fallback', () => {
    const html = renderToStaticMarkup(<ImageFrame src="/demo/watches/a.webp" alt="Watch" width={480} height={360} placeholder={<span>Photo</span>} />);
    expect(html).toContain('aspect-ratio:480 / 360');expect(html).toContain('aria-label="Watch"');
    expect(html).toContain('data-image-state="loading"');expect(html).toContain('loading="lazy"');expect(html).toContain('decoding="async"');
    expect(html).toContain('width="480"');expect(html).toContain('height="360"');expect(html).not.toContain('data-ready');
    const empty = renderToStaticMarkup(<Avatar name={NAMES.emojiOnly} label={NAMES.emojiOnly} size="compact"/>);
    expect(empty).toContain(NAMES.emojiOnly);expect(empty).not.toContain('<img');
    expect(css).toContain('@container bt-avatar (max-width: 27px)');
    expect(css).toContain('font-size: var(--bt-text-caption)');
  });
});
