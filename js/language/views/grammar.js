import { node, replace, statusPill } from '../components/dom.js';
import { formatLanguageRoute } from '../router.js';

function link(text, href) { return node('a', { className: 'language-button', text, attrs: { href } }); }
function parserStatus(parser) {
  return node('p', { text: parser?.state === 'AVAILABLE'
    ? `Grammar parser: models available${parser.loadVerified ? ' · load verified' : ' · loaded on explicit analysis'}`
    : `Grammar unavailable: ${parser?.reason || 'status unavailable'}. Reader remains available.` });
}

export function renderGrammar(mount, data, { onReview = async () => {} } = {}) {
  const root = node('div', { className: 'language-grammar' }, [
    node('h3', { text: data.pattern?.name || 'Core Grammar' }),
    node('p', { text: 'Explore supported patterns found in your texts. Discovery does not mean mastery.' }),
    node('details', { className: 'language-technical-details' }, [
      node('summary', { text: 'Pattern scope and parser status' }),
      node('p', { text: data.bucketMeaning || 'A1/A2/B1 are practical scope buckets, not certified CEFR levels.' }),
      parserStatus(data.parser),
    ]),
  ]);
  if (data.pattern) {
    const pattern = data.pattern;
    root.append(link('All patterns', '#grammar'), statusPill(`${pattern.bucket} · ${pattern.status} · ${pattern.state}`),
      node('p', { text: pattern.explanation }),
      node('details', { className: 'language-technical-details' }, [
        node('summary', { text: 'Detection rule and limitations' }),
        node('p', { text: `Detector ${pattern.detectorId} v${pattern.detectorVersion} · pattern v${pattern.patternVersion}` }),
        node('p', { text: pattern.rule }), node('p', { text: `Limitations: ${pattern.limitations}` }),
      ]),
      node('p', { text: `${pattern.authoritativeCount} authoritative / ${pattern.occurrenceCount} occurrences` }));
    if (!data.examples?.length) root.append(node('p', { text: pattern.status === 'DEFERRED' ? 'Deferred: this detector is not available.' : 'No examples yet. Open an analyzed Reader text and choose Analyze Grammar.' }));
    for (const example of data.examples || []) {
      const sentence = [...example.exactText];
      const start = example.sourceStart - example.sentenceStart;
      const end = example.sourceEnd - example.sentenceStart;
      const quote = node('blockquote', {}, [sentence.slice(0, start).join(''), node('mark', { text: sentence.slice(start, end).join('') }), sentence.slice(end).join('')]);
      const card = node('article', { className: 'language-card' }, [
        node('h4', { text: example.title }),
        statusPill(`${example.sourceProvenance?.kind || example.sourceType} · ${example.state}`), quote,
        link('Open source sentence', formatLanguageRoute({ name: 'readerText', textId: example.textDocumentId, sentenceId: example.sentenceId })),
      ]);
      const details = node('details', {}, [node('summary', { text: 'Exact token evidence and provenance' })]);
      for (const [role, token] of Object.entries(example.evidence || {})) {
        const surface = sentence.slice(token.start - example.sentenceStart, token.end - example.sentenceStart).join('');
        details.append(node('p', { text: `${role}: ${surface} · [${token.start}, ${token.end}) · token ${token.tokenId} · ${token.relation} → ${token.headTokenId || 'ROOT'} · ${JSON.stringify(token.morphology)}` }));
      }
      details.append(node('pre', { text: JSON.stringify({ parser: example.parserProvenance, analyzer: example.analyzerProvenance, source: example.sourceProvenance, runId: example.runId, evidence: example.evidenceStatus }, null, 2) }));
      const status = node('p', { text: `Detector review: ${example.reviewState}`, attrs: { role: 'status' } });
      const actions = node('div', { className: 'language-reader-actions' });
      for (const [label, decision] of [['Confirm detector', 'CONFIRMED'], ['Reject detector', 'REJECTED'], ['Clear review', 'UNREVIEWED']]) {
        const button = node('button', { type: 'button', className: 'language-button', text: label });
        button.addEventListener('click', async () => {
          const buttons = actions.querySelectorAll('button');
          buttons.forEach((item) => { item.disabled = true; });
          try { await onReview(example.id, decision); status.textContent = `Detector review: ${decision}`; }
          catch (error) { status.textContent = error.message || 'Review could not be saved.'; }
          finally { buttons.forEach((item) => { item.disabled = false; }); }
        });
        actions.append(button);
      }
      card.append(details, node('p', { text: 'Review checks the detector, not your knowledge.' }), status, actions);
      root.append(card);
    }
    if (data.hasMore) root.append(node('p', { text: 'Showing the first 200 examples. Counts include all occurrences.' }));
  } else {
    for (const bucket of ['A1', 'A2', 'B1']) {
      const group = node('section', { className: 'language-grammar-group' }, [node('h3', { text: `${bucket} practical scope` })]);
      for (const pattern of data.items || []) {
        if (pattern.bucket !== bucket) continue;
        const preview = data.previews?.find((item) => item.patternId === pattern.patternId);
        group.append(node('article', { className: 'language-card language-grammar-catalogue-row' }, [
          node('div', {}, [link(pattern.name, formatLanguageRoute({ name: 'grammarPattern', patternId: pattern.patternId })),
            node('p', { text: pattern.explanation })]),
          node('div', {}, [statusPill(`${pattern.status} · ${pattern.state}`),
            node('small', { text: `${pattern.authoritativeCount} found` })]),
          preview ? node('details', { className: 'language-technical-details' }, [
            node('summary', { text: 'Example' }), node('p', { text: preview.exactText }),
          ]) : null,
        ]));
      }
      root.append(group);
    }
  }
  replace(mount, root);
}

export function mountReaderGrammar(mount, { api, textId, profileId, windowRef = window, pollMs = 1000 }) {
  let stopped = false; let timer;
  const status = node('span', { text: 'Grammar: checking status…', attrs: { role: 'status' } });
  const analyze = node('button', { type: 'button', className: 'language-button', text: 'Analyze Grammar', disabled: true });
  const examples = node('details', { hidden: true });
  replace(mount, status, analyze, link('Open Grammar', '#grammar'), examples);
  async function refresh() {
    try {
      const data = await api.textGrammar(textId, profileId);
      if (stopped) return;
      const pending = ['QUEUED', 'RUNNING'].includes(data.status);
      status.textContent = `Grammar: ${data.status}${data.job?.errorMessage ? ` · ${data.job.errorMessage}` : ''}${data.parser?.state !== 'AVAILABLE' ? ` · ${data.parser?.reason || 'parser unavailable'}` : ''}`;
      analyze.disabled = pending || data.parser?.state !== 'AVAILABLE';
      examples.replaceChildren();
      const seen = new Set();
      const links = node('div', { className: 'language-reader-actions' });
      for (const example of data.examples || []) {
        if (seen.has(example.patternId)) continue;
        seen.add(example.patternId);
        links.append(link(example.patternId.replaceAll('_', ' '), formatLanguageRoute({ name: 'grammarPattern', patternId: example.patternId })));
      }
      examples.hidden = seen.size === 0;
      examples.append(node('summary', { text: `Grammar evidence: ${seen.size} patterns` }), links);
      if (pending) timer = windowRef.setTimeout(refresh, pollMs);
    } catch (error) { if (!stopped) status.textContent = `Grammar unavailable: ${error.message}`; }
  }
  analyze.addEventListener('click', async () => {
    analyze.disabled = true;
    status.textContent = 'Grammar: queuing analysis…';
    try { await api.analyzeGrammar(textId, profileId); if (!stopped) await refresh(); }
    catch (error) { if (!stopped) { status.textContent = error.message; analyze.disabled = false; } }
  });
  refresh();
  return () => { stopped = true; windowRef.clearTimeout(timer); };
}
