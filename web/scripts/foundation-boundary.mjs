// The public control migration is explicit; private subpaths stay private.
export const FOUNDATION_ENTRY = '@beirut-time/ui/foundation';
export const LEGACY_ENTRIES = new Set(['@beirut-time/ui', '@/shell/primitives']);
export const FOUNDATION_CONTROLS = new Set([
  'Button', 'ButtonLink', 'buttonVariants', 'Card', 'Input', 'Textarea', 'Label',
  'Checkbox', 'Radio', 'Switch', 'Select', 'SelectOption', 'SelectProps',
  'Badge', 'StatusBadge', 'Segmented', 'SegmentedGroup', 'SegmentedItem',
  'Dialog', 'DialogTrigger', 'DialogClose', 'DialogContent', 'DialogTitle', 'DialogDescription',
  'Sheet', 'SheetTrigger', 'SheetClose', 'SheetContent', 'SheetTitle',
  'Popover', 'PopoverTrigger', 'PopoverContent',
  'DropdownMenu', 'DropdownMenuTrigger', 'DropdownMenuContent', 'DropdownMenuItem',
  'DropdownMenuRadioGroup', 'DropdownMenuRadioItem', 'DropdownMenuSeparator', 'DropdownMenuLabel',
  'ImageFrame', 'Skeleton', 'RowSkeleton', 'State', 'ScrollRegion', 'AnimatedList', 'Toaster', 'toast', 'DirectionProvider',
]);
