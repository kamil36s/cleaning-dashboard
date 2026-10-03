import { messageState, node, replace } from '../components/dom.js';

export function renderStudySession(mount, state, { onBuild }) {
  const select = node('select', { id: 'language-session-minutes', attrs: { 'aria-label': 'Session duration' } },
    [10, 20, 30].map((minutes) => node('option', { value: minutes, text: `${minutes} minutes` })));
  select.value = String(state.minutes);
  const button = node('button', { className: 'language-button is-primary', type: 'button', text: 'Build Session' });
  const form = node('form', { className: 'language-session-controls' }, [
    node('label', { text: 'Available time', attrs: { for: select.id } }), select, button,
  ]);
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    onBuild(Number(select.value));
  });
  const content = node('div');
  if (state.loading) content.append(messageState('loading', 'Building a study session…'));
  else if (state.error) content.append(messageState('error', 'Study Session could not be built.', state.error));
  else if (state.plan) {
    const plan = state.plan;
    content.append(node('p', { className: 'language-definition', text:
      `${plan.requestedMinutes} min requested · ${plan.plannedMinutes} min planned · ${plan.segmentCount} segments` }));
    if (!plan.segments.length) content.append(messageState('empty', 'No useful study work is currently available.'));
    else {
      const list = node('ol', { className: 'language-session-list' });
      plan.segments.forEach((segment) => {
        list.append(node('li', { className: 'language-card language-session-card' }, [
          node('div', { className: 'language-session-card-head' }, [
            node('h3', { text: segment.title }),
            node('strong', { text: `${segment.estimatedMinutes} min` }),
          ]),
          node('p', { text: segment.reason }),
          node('small', { text: `Source: ${segment.sourceOwner}` }),
          node('a', { className: 'language-button is-primary', text: 'Start / Open',
            attrs: { href: segment.destinationRoute } }),
        ]));
      });
      content.append(list);
      content.append(node('a', { className: 'language-button', text: 'Start session',
        attrs: { href: plan.segments[0].destinationRoute } }));
    }
    if (plan.unavailableSources?.length) content.append(node('p', { className: 'language-definition',
      text: `Unavailable sources: ${plan.unavailableSources.join(', ')}.${plan.segments.length ? ' The plan uses the remaining work.' : ''}` }));
    content.append(node('details', { className: 'language-technical-details' }, [
      node('summary', { text: 'Plan provenance' }),
      node('small', { className: 'language-session-fingerprint',
        text: `${plan.policyVersion} · ${plan.generatedAtLocalDate} · snapshot ${plan.snapshotFingerprint}` }),
    ]));
  } else content.append(node('p', { className: 'language-definition',
    text: 'Choose a duration to preview a read-only plan from your current study work.' }));
  replace(mount, node('section', { className: 'language-session-builder' }, [
    node('p', { className: 'language-kicker', text: 'STUDY SESSION BUILDER' }),
    node('h3', { text: 'Plan a short session' }), form, content,
  ]));
}
