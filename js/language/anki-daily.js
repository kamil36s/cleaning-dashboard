export function mainAnkiDecks(items = []) {
  return items.filter((item) => String(item.name || '').trim().toLowerCase() !== 'default'
    && !items.some((parent) => parent !== item && !parent.error
      && item.name.startsWith(`${parent.name}::`)));
}

export function ankiDailyProgress(items = []) {
  const decks = mainAnkiDecks(items).filter((item) => !item.error);
  return {
    done: decks.reduce((sum, item) => sum + (item.reviewsCompletedToday || 0) + (item.newCompletedToday || 0), 0),
    planned: decks.reduce((sum, item) => sum + (item.reviewsPlannedToday || 0) + (item.newPlannedToday || 0), 0),
  };
}

export function ankiAchievement(items = []) {
  const { done, planned } = ankiDailyProgress(items);
  if (!planned) return { state: 'neutral', value: 'No plan', detail: 'No Anki cards planned today', eligible: false };
  const complete = done >= planned && mainAnkiDecks(items).every((item) => !item.error);
  return {
    state: complete ? 'complete' : 'pending',
    value: `${Math.round(done / planned * 100)}%`,
    detail: `${done}/${planned} cards${done > planned ? ` · ${done - planned} extra` : ''}`,
    progress: done / planned * 100,
  };
}
