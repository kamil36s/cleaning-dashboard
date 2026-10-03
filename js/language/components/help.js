const HELP = {
  overview: ['Choose a short session and start with the Daily Core.', 'Use this when you want a next step today.', 'Choose 10, 20, or 30 minutes.', 'Anki due, Cloze practice, and Reader continuation are separate.'],
  'study-session': ['Build a short mix from available study work.', 'Use this when you have a fixed amount of time.', 'Choose a duration and open the first segment.', 'Planned minutes can be less than requested when useful work is unavailable.'],
  reviews: ['Check Anki cards and practice mistakes.', 'Use this when you have reviews to clear.', 'Check the stored due count, then open Anki or Cloze.', 'Anki owns scheduling; Cloze practice is a separate recommendation.'],
  reader: ['Read Norwegian texts and inspect words in context.', 'Use this for sustained reading.', 'Open an analyzed text or add a short one.', 'Only explicit reading activity and knowledge changes create learning evidence.'],
  cloze: ['Practice vocabulary in sentence context.', 'Use this when you want focused recall practice.', 'Start a 10 question session.', 'Suggested practice is not an Anki due queue.'],
  listening: ['Listen to available texts and audio.', 'Use this to practice comprehension.', 'Choose material and a listening mode.', 'Only visible transcripts offer lexical lookup.'],
  vocabulary: ['Browse the words you track.', 'Use this to find or edit a word.', 'Search for a lemma.', 'Knowledge states describe your explicit evidence.'],
  phrasebook: ['Keep useful expressions with source context.', 'Use this to revisit saved phrases.', 'Save an expression from Reader.', 'Phrases are not assigned a mastery score.'],
  curriculum: ['Browse reviewed practical packs.', 'Use this to choose a topic to study.', 'Open a pack.', 'Opening a pack does not add every word to vocabulary.'],
  inbox: ['Import text, audio, and transcripts.', 'Use this when you have material to study.', 'Choose a source type and add content.', 'Processing status describes import work, not proficiency.'],
  topics: ['Group tracked words by topic.', 'Use this to organize your vocabulary.', 'Open or create a topic.', 'Progress covers only mapped words.'],
  grammar: ['Find supported grammar patterns in texts.', 'Use this after analyzing Reader text.', 'Open a pattern or analyze a text.', 'Discovered patterns are not mastered patterns.'],
  generate: ['Create text adjusted to your vocabulary.', 'Use this when you want fresh reading material.', 'Choose length, difficulty, topic, and style.', 'Generated text is checked locally before acceptance.'],
  benchmarks: ['Take occasional checkpoints for vocabulary, Cloze, reading, and listening.', 'Use this to compare performance over time.', 'Run a baseline.', 'These scores are descriptive and are not a CEFR test.'],
  progress: ['See level, XP, streaks, quests, and collections.', 'Use this to review activity trends.', 'Scan the top summary.', 'XP rewards activity; it is not a language proficiency score.'],
  statistics: ['Explore your learning history.', 'Use this when you want detailed trends.', 'Choose a time range.', 'Counts come from recorded activity and tracked words.'],
  goals: ['Set personal weekly study targets.', 'Use this to focus on a chosen activity.', 'Create a goal.', 'Progress uses recorded activity, never estimated work.'],
  settings: ['Manage your study profile and integrations.', 'Use this to adjust preferences or back up data.', 'Choose the section you need.', 'Advanced status describes integrations and does not affect study progress.'],
};

export function renderLanguageHelp(mount, routeName) {
  const [purpose, when, action, numbers] = HELP[routeName] || HELP.overview;
  mount.replaceChildren();
  [['Purpose', purpose], ['When to use', when], ['First action', action], ['What the numbers mean', numbers]].forEach(([heading, copy]) => {
    const section = document.createElement('section');
    const title = document.createElement('h3');
    title.textContent = heading;
    const paragraph = document.createElement('p');
    paragraph.textContent = copy;
    section.append(title, paragraph);
    mount.append(section);
  });
  if (routeName === 'reader') {
    const shortcuts = document.createElement('p');
    shortcuts.textContent = 'Reader: ← / → move between words; 1 New, 2 Learning, 3 Known, 4 Mastered, X Ignore; Enter opens word details; Esc closes.';
    mount.append(shortcuts);
  }
}
