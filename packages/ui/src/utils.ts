import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
// Generic composition, independent of product policy.
export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)); }
