import { cva } from 'class-variance-authority';
/** Server-safe recipe shared by buttons and navigation links. */
export const buttonVariants = cva('ui-btn', {
  variants: {
    variant: { default: 'ui-btn-default', outline: 'ui-btn-outline', ghost: 'ui-btn-ghost', destructive: 'ui-btn-destructive' },
    size: { default: 'ui-btn-md', sm: 'ui-btn-sm', icon: 'ui-btn-icon pg-iconbtn' },
  },
  defaultVariants: { variant: 'default', size: 'default' },
});
