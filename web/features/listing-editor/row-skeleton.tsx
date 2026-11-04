import { RowSkeleton } from '@beirut-time/ui';
export function ListingSkeleton({ label }: { label: string }) {
  return <div className="le-row-skeletons" role="status" aria-label={label}>
    {Array.from({ length: 5 }, (_, index) => <RowSkeleton key={index} media="cover"/>)}
    <span className="sr-only">{label}</span>
  </div>;
}
