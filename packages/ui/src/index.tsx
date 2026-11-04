import Link from 'next/link';
import { cn } from './utils';
export function Button({ className, ...props }: React.ComponentProps<'button'>) {
  return <button className={cn('button', className)} {...props} />;
}
export function ButtonLink({ className, ...props }: React.ComponentProps<typeof Link>) {
  return <Link className={cn('button', className)} {...props} />;
}
export function Card({ className, ...props }: React.ComponentProps<'section'>) {
  return <section className={cn('card', className)} {...props} />;
}
export function Input({ className, ...props }: React.ComponentProps<'input'>) {
  return <input className={cn('input', className)} {...props} />;
}
export function State({ title, body, children }: { title: string; body: string; children?: React.ReactNode }) {
  return <div className="state"><span className="state-mark" aria-hidden="true">◇</span><h1>{title}</h1><p>{body}</p>{children}</div>;
}
export function BidiReference({ children }: { children: React.ReactNode }) { return <bdi dir="ltr">{children}</bdi>; }
export function Skeleton({ label }: { label: string }) {
  return <div className="skeleton-page" role="status" aria-label={label}><div className="skeleton skeleton-title" /><div className="skeleton skeleton-body" /><div className="skeleton skeleton-card" /><span className="sr-only">{label}</span></div>;
}
