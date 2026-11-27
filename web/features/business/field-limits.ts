/** The shared input keeps its drawing; native constraints attach on hydration. */
export function fieldLimits(node: HTMLInputElement | null, minimum: number | undefined, maximum: number) {
  if (!node) return;
  node.minLength = minimum ?? 0;
  node.maxLength = maximum;
}
