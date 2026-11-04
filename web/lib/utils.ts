import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
// CP inventory 8D: generic composition, independent of product policy.
export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)); }
