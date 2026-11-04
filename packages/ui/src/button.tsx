"use client";

import * as React from "react";
import type { VariantProps } from "class-variance-authority";
import { buttonVariants } from './button-variants';
import { cn } from "./utils";

/**
 * Base recipes live in styles/ui.css as zero-specificity `:where(.ui-btn*)`
 * classes so a vocabulary class passed through `className` (pg-*, department
 * classes) restyles the button, while utilities still win over everything.
 */
type ButtonProps = React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    chonk?: boolean;
  };

function Button({
  className,
  variant,
  size,
  chonk,
  children,
  ...props
}: ButtonProps) {
  variant ??= className?.includes('button-secondary') ? 'outline' : className?.includes('icon-button') ? 'ghost' : 'default';
  size ??= className?.includes('icon-button') ? 'icon' : 'default';
  const isChonk = chonk === true && size !== "icon";
  const chonkTone =
    variant === "destructive"
      ? "pg-chonk-destructive"
      : variant === "outline" || variant === "ghost"
        ? "pg-chonk-neutral"
        : "pg-chonk-primary";

  return (
    <button
      className={
        isChonk
          ? cn(
              "ui-chonk pg-chonk",
              chonkTone,
              size === "sm" && "pg-chonk-sm",
              className
            )
          : cn(buttonVariants({ variant, size, className }))
      }
      {...props}
    >
      {isChonk ? <span>{children}</span> : children}
    </button>
  );
}

export { Button, buttonVariants };
