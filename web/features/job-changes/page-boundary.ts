'use client';

// Compatibility boundary until the shared page definitions are available.
// Keep the existing layout, root cache and private read behavior unchanged.
export { PageLayout as PageFrame } from '@/shell/page-header';
export { useQuery as usePageRead } from '@tanstack/react-query';
