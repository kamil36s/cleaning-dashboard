export function selectKitchenFootballSlides(slides, settings = {}) {
  const max = Number.isInteger(settings.kitchenMaxSlides)
    ? Math.max(1, Math.min(12, settings.kitchenMaxSlides)) : 6;
  const allowed = (slides || []).filter(slide =>
    (settings.kitchenShowStandings !== false || slide.type !== "standings") &&
    (settings.kitchenShowUpcoming !== false || slide.type !== "next"));
  const priority = { match: 0, next: 1, results: 2, standings: 3 };
  return allowed.map((slide, index) => ({ slide, index }))
    .sort((a, b) => (priority[a.slide.type] ?? 4) - (priority[b.slide.type] ?? 4) || a.index - b.index)
    .slice(0, max)
    .map(item => item.slide);
}
