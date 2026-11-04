import { cn } from "./utils";

/**
 * A list-row skeleton that RESERVES the image slot of the row it stands in
 * for (ADR-0031): the avatar or cover box is already there when the rows
 * arrive, so the image frame's placeholder and the decoded picture land in a
 * box that never moves. `media` picks the slot's shape: a round 40 px avatar,
 * a rounded-square 40 px draft avatar, or a 56 px campaign cover. The row
 * keeps the `pg-skeleton` marker every settle wait looks for; its media box
 * (`::before` of the row) and two text lines (`::before`/`::after` of the copy
 * column) are CSS pseudo-elements (styles/campaigns.css, shimmer beside
 * `.pg-skeleton` in styles/motion.css), so the row costs two elements and only
 * the list routes that render it carry this module (the shell imports
 * `Skeleton` alone).
 */
export function RowSkeleton({
  media = "avatar",
  className,
}: {
  media?: "avatar" | "avatar-square" | "cover";
  className?: string;
}) {
  return (
    <div className={cn("pg-skeleton pg-skeleton-row pg-skeleton-row-composed", `pg-skeleton-media-${media}`, className)} aria-hidden>
      <div className="pg-skeleton-copy" />
    </div>
  );
}
