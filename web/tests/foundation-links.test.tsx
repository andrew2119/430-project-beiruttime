import { expect, it, vi } from 'vitest';
import { ButtonLink } from '@beirut-time/ui/foundation';

it('canonical destination controls retain explicit full prefetch and native click handling', () => {
  const clicked = vi.fn();
  const link = ButtonLink({href:'/en/about',children:'About',prefetch:true,onClick:clicked,'aria-current':'page'});
  expect(link.props.prefetch).toBe(true);
  expect(link.props['aria-current']).toBe('page');
  const event = {preventDefault:vi.fn()};
  link.props.onClick(event as never);
  expect(clicked).toHaveBeenCalledWith(event);
  expect(event.preventDefault).not.toHaveBeenCalled();
  const disabled = ButtonLink({href:'/en/about',children:'About',prefetch:true,disabled:true,onClick:clicked});
  expect(disabled.props.prefetch).toBe(false);
  disabled.props.onClick(event as never);
  expect(event.preventDefault).toHaveBeenCalledOnce();
  expect(clicked).toHaveBeenCalledOnce();
});
