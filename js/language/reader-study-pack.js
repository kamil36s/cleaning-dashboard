export function buildReaderStudyPrompt(document, sentences = [], tokens = []) {
  const input = {
    title: document?.title || 'Reading text',
    sentences: sentences.map((sentence) => ({
      sentenceId: sentence.id,
      source: sentence.exactText,
      tokens: tokens.filter((token) => token.sentenceId === sentence.id && token.tokenKind === 'WORD')
        .map((token) => ({
          tokenId: token.id,
          source: token.surface,
          status: !token.selectedLemmaId || ['AMBIGUOUS', 'UNRESOLVED'].includes(token.resolutionState)
            ? 'UNRESOLVED' : ['IGNORED', 'EXCLUDED'].includes(token.disposition)
              ? token.disposition : token.knowledgeStatus || 'NEW',
        })),
    })),
  };
  return [
    'You are helping an English-speaking learner read Norwegian Bokmål.',
    'For every sentence below, provide a natural complete English translation, contextual English meanings for its vocabulary, and a concise grammar hint.',
    'Every token marked NEW or LEARNING must appear in at least one gloss. Translate its meaning in THIS sentence, not its general dictionary meaning.',
    'A gloss may group several tokens when they form a phrasal verb, idiom, fixed expression, or a meaning that cannot be translated word by word. Include known connector words in tokenIds when needed for the expression. You may also add useful multiword idioms whose tokens are all KNOWN or MASTERED.',
    'For each gloss, list tokenIds in text order. Set source to the exact substring of the Norwegian sentence from the first listed token through the last, preserving the original spelling, spaces, and punctuation. Set english to the meaning of that word or expression in this exact context. Use an empty glosses list only when no NEW or LEARNING tokens need meanings and there is no useful expression.',
    'Preserve every sentenceId and source exactly, including punctuation. Keep the same order. Do not omit or add sentences. Do not invent story facts or claim access to the Reader app.',
    'Return only one JSON object of this shape: {"sentences":[{"sentenceId":"...","source":"...","english":"...","glosses":[{"source":"...","english":"...","tokenIds":["..."]}],"grammarHint":"..."}]}',
    'Use plain text in english, gloss meanings and grammarHint. Keep each grammar hint to one or two useful sentences.',
    '',
    JSON.stringify(input, null, 2),
  ].join('\n');
}

export function parseReaderStudyResponse(raw) {
  let text = String(raw || '').trim();
  if (text.startsWith('```')) text = text.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
  let result;
  try { result = JSON.parse(text); }
  catch { throw new Error('The pasted response is not valid JSON. Paste the complete JSON block from your chat.'); }
  if (!result || typeof result !== 'object' || Array.isArray(result) || !Array.isArray(result.sentences)) {
    throw new Error('Paste a JSON object with a sentences list.');
  }
  return result;
}
