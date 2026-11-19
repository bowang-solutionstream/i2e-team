export function normalizeLabels(labels: readonly string[]): string[] {
  return labels.map(label => label.trim().replace(/\s+/gu, " "));
}
