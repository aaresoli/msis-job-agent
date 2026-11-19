export function matchBand(score: number, degraded = false): string {
  if (degraded) return "Awaiting AI refinement";
  if (score >= 80) return "Strong alignment";
  if (score >= 60) return "Worth a closer look";
  return "Exploratory match";
}
