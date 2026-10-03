import { messageState, node, replace, statusPill } from '../components/dom.js';

function progressBar(value, label) {
  const progress = node('progress', { value: Number(value) || 0, attrs: { max: 100, 'aria-label': label } });
  return node('div', { className: 'language-progress-meter' }, [progress, node('span', { text: label })]);
}

function milestoneKey(item) {
  if (item.type === 'CURRICULUM_PACK_PROGRESS') return `${item.type}:${item.packId}:v${item.packVersion}`;
  if (item.type === 'FAST_TRACK_RELIABLE') return `${item.type}:${item.trackKey}`;
  if (item.type === 'TOPIC_KNOWN') return `${item.type}:${item.topicId}`;
  return item.type;
}

function campaignForm(campaign, onSave, collections = []) {
  const defaults = new Map((campaign?.milestones || []).map((item) => [milestoneKey(item), item]));
  const form = node('form', { className: 'language-campaign-form' });
  const name = node('input', { attrs: { name: 'name', required: '', maxlength: '120', value: campaign?.name || 'Norway Spring 2027' } });
  const targetDate = node('input', { attrs: { name: 'targetDate', type: 'date', required: '', value: campaign?.targetDate || '2027-05-01' } });
  const description = node('textarea', { attrs: { name: 'description', maxlength: '1000', rows: '2' } });
  description.value = campaign?.description || 'Practical Norwegian preparation with separate evidence-backed milestones.';
  const choices = [
    ['FAST_TRACK_RELIABLE', 'Fast Track 1 · 25 Reliable', { type: 'FAST_TRACK_RELIABLE', trackKey: 'FAST_TRACK_1', target: 25 }],
    ['READER_TEXTS_COMPLETED', 'Complete 5 Reader texts', { type: 'READER_TEXTS_COMPLETED', target: 5 }],
    ['CLOZE_ATTEMPTS', 'Answer 100 Cloze questions', { type: 'CLOZE_ATTEMPTS', target: 100 }],
    ['LISTENING_ACTIVE_MINUTES', 'Listen actively for 60 minutes', { type: 'LISTENING_ACTIVE_MINUTES', target: 60 }],
    ['LISTENING_TEXTS_COMPLETED', 'Complete 3 texts in Listening', { type: 'LISTENING_TEXTS_COMPLETED', target: 3 }],
    ['STUDY_DAYS', 'Record 30 study days', { type: 'STUDY_DAYS', target: 30 }],
    ...collections.filter((item) => item.kind === 'CURRICULUM_PACK').map((item) => {
      const milestone = {
        type: 'CURRICULUM_PACK_PROGRESS', packId: item.packId,
        packVersion: item.packVersion, target: 75,
      };
      return [milestoneKey(milestone), `${item.name} v${item.packVersion} · reach 75%`, milestone];
    }),
  ];
  const checks = choices.map(([key, label, milestone]) => {
    const input = node('input', { attrs: { type: 'checkbox', name: 'milestone', value: key } });
    input.checked = defaults.has(key) || (
      !campaign
      && key !== 'STUDY_DAYS'
      && milestone.type !== 'CURRICULUM_PACK_PROGRESS'
      && !milestone.type.startsWith('LISTENING_')
    );
    input.dataset.milestone = JSON.stringify(defaults.get(key) || milestone);
    return node('label', { className: 'language-campaign-check' }, [input, node('span', { text: label })]);
  });
  const enabled = node('input', { attrs: { type: 'checkbox', name: 'enabled' } });
  enabled.checked = campaign?.enabled ?? true;
  const submit = node('button', { className: 'language-button is-primary', type: 'submit', text: campaign ? 'Save campaign' : 'Create campaign' });
  form.append(
    node('label', {}, [node('span', { text: 'Name' }), name]),
    node('label', {}, [node('span', { text: 'Target date' }), targetDate]),
    node('label', { className: 'is-wide' }, [node('span', { text: 'Description' }), description]),
    node('fieldset', { className: 'is-wide' }, [node('legend', { text: 'Available milestones' }), ...checks]),
    node('label', { className: 'language-campaign-check' }, [enabled, node('span', { text: 'Enabled' })]),
    submit,
  );
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const milestones = [...form.querySelectorAll('input[name="milestone"]:checked')]
      .map((input) => JSON.parse(input.dataset.milestone));
    if (!milestones.length) return;
    submit.disabled = true;
    try {
      await onSave?.({
        name: name.value.trim(), targetDate: targetDate.value,
        description: description.value.trim(), enabled: enabled.checked, milestones,
      });
    } finally {
      submit.disabled = false;
    }
  });
  return form;
}

function achievementCard(item) {
  return node('article', { className: `language-achievement is-${item.state.toLowerCase()}` }, [
    node('div', { className: 'language-achievement-head' }, [
      node('strong', { text: item.name }),
      statusPill(item.state === 'UNLOCKED' ? 'Unlocked' : 'Locked', item.state === 'UNLOCKED' ? 'success' : 'muted'),
    ]),
    node('p', { text: item.description }),
    progressBar(item.progressPercent, `${item.current} of ${item.target} · ${item.progressPercent}%`),
    item.unlockedAt ? node('small', { text: `Unlocked ${new Date(item.unlockedAt).toLocaleDateString('en-GB')}` }) : null,
  ]);
}

export function renderProgress(mount, state, { onCreateCampaign, onUpdateCampaign } = {}) {
  if (state.loading && !state.data) return replace(mount, messageState('loading', 'Loading evidence-driven progress…'));
  if (state.error) return replace(mount, messageState('error', 'Progress is unavailable.', state.error));
  const data = state.data;
  if (!data) return replace(mount, messageState('empty', 'No progress data is available.'));

  const level = data.level;
  const quests = data.today?.items || [];
  const achievements = data.achievements?.items || [];
  const collections = data.collections?.items || [];
  const campaigns = data.campaigns?.items || [];
  const categories = [...new Set(achievements.map((item) => item.category))];

  const levelCard = node('section', { className: 'language-card language-progress-hero' }, [
    node('p', { className: 'language-kicker', text: 'GAMIFICATION · NOT PROFICIENCY' }),
    node('h3', { text: level.label }),
    node('strong', { className: 'language-progress-xp', text: `${level.lifetimeXp} lifetime XP` }),
    progressBar(level.progressPercent, `${level.xpIntoLevel} XP in this level · ${level.xpNeeded} XP to Level ${level.level + 1}`),
    node('p', { className: 'language-definition', text: 'Account level is a motivation layer. It is not CEFR or a claim about Norwegian proficiency.' }),
  ]);

  const todayCard = node('section', { className: 'language-card language-progress-section' }, [
    node('p', { className: 'language-kicker', text: `${data.today.localStudyDate} · ${data.today.timezone}` }),
    node('h3', { text: 'Today' }),
    node('div', { className: 'language-quest-list' }, quests.map((quest) => node('a', {
      className: `language-quest is-${quest.completed ? 'complete' : 'active'}`, attrs: { href: quest.href },
    }, [
      node('span', {}, [node('strong', { text: quest.title }), node('small', { text: quest.reason })]),
      node('span', { text: `${quest.current} / ${quest.target} ${quest.unit}${quest.completed ? ' · Complete' : ''}` }),
      progressBar(quest.progressPercent, `${quest.title}: ${quest.progressPercent}%`),
    ]))),
  ]);

  const consistencyCard = node('section', { className: 'language-card language-progress-section' }, [
    node('p', { className: 'language-kicker', text: 'CANONICAL READER STREAK' }),
    node('h3', { text: 'Consistency' }),
    node('div', { className: 'language-progress-stat-row' }, [
      ['Current', `${data.streak.currentDays || 0} days`],
      ['Best', `${data.streak.bestDays || 0} days`],
      ['Last 7', `${data.streak.studyDaysLast7 || 0} study days`],
      ['Last 30', `${data.streak.studyDaysLast30 || 0} study days`],
    ].map(([label, value]) => node('div', {}, [node('span', { text: label }), node('strong', { text: value })]))),
    node('p', { className: 'language-definition', text: data.noPenaltyPolicy }),
  ]);

  const collectionCard = node('section', { className: 'language-card language-progress-section is-wide' }, [
    node('p', { className: 'language-kicker', text: 'YOUR COLLECTIONS' }),
    node('h3', { text: 'Collections' }),
    node('div', { className: 'language-collection-grid' }, collections.map((item) => node('article', { className: 'language-collection' }, [
      node('div', { className: 'language-achievement-head' }, [node('strong', { text: item.name }), statusPill(item.tier || item.status, item.tier === 'COMPLETE' ? 'success' : 'muted')]),
      progressBar(item.progressPercent, `${item.completed} of ${item.totalEligible} · ${item.progressPercent}%`),
      node('details', { className: 'language-technical-details' }, [
        node('summary', { text: 'How progress is counted' }),
        node('small', { text: item.kind === 'CURRICULUM_PACK'
          ? `${item.denominatorSource} · source ${item.sourceTotal}, approved ${item.approvedTotal}, mapped ${item.mapped}, ambiguous ${item.ambiguous}, unresolved ${item.unresolved}, excluded ${item.excluded}`
          : `${item.denominatorSource} · mapped ${item.mapped}, unresolved ${item.unresolved}, excluded ${item.excluded}` }),
        item.completeTopicDomain === false ? node('small', { text: 'Partial user-mapped topic; not a complete semantic domain.' }) : null,
        item.completionStateRule ? node('small', { text: item.completionStateRule }) : null,
      ]),
    ]))),
    node('details', { className: 'language-technical-details' }, [node('summary', { text: 'Collection policy' }), node('small', { text: data.collections.policyVersion })]),
  ]);

  const achievementCardSection = node('section', { className: 'language-card language-progress-section is-wide' }, [
    node('p', { className: 'language-kicker', text: 'MILESTONES' }),
    node('h3', { text: 'Achievements' }),
    node('p', { className: 'language-definition', text: data.achievements.completionLabel }),
    ...categories.map((category) => node('section', { className: 'language-achievement-category' }, [
      node('h4', { text: category.replaceAll('_', ' ') }),
      node('div', { className: 'language-achievement-grid' }, achievements.filter((item) => item.category === category).map(achievementCard)),
    ])),
  ]);

  const campaignCard = node('section', { className: 'language-card language-progress-section is-wide' }, [
    node('p', { className: 'language-kicker', text: 'PERSONAL CAMPAIGNS' }),
    node('h3', { text: 'Campaigns' }),
    node('p', { className: 'language-definition', text: 'Campaign milestones stay separate. There is no universal Norway readiness score.' }),
    campaigns.length ? node('div', { className: 'language-campaign-list' }, campaigns.map((campaign) => node('article', { className: 'language-campaign' }, [
      node('div', { className: 'language-achievement-head' }, [node('strong', { text: campaign.name }), statusPill(campaign.enabled ? campaign.dateState : 'Disabled', campaign.enabled ? 'success' : 'muted')]),
      node('p', { text: campaign.description || 'No description.' }),
      node('small', { text: `Target ${campaign.targetDate} · ${campaign.completedMilestones} / ${campaign.milestoneCount} milestones` }),
      node('ul', { className: 'language-campaign-milestones' }, campaign.milestones.map((item) => node('li', {}, [
        node('span', { text: item.type === 'CURRICULUM_PACK_PROGRESS'
          ? `${item.packId} v${item.packVersion}` : item.type.replaceAll('_', ' ') }),
        node('strong', { text: `${item.current}${item.type === 'CURRICULUM_PACK_PROGRESS' ? '%' : ''} / ${item.target}${item.type === 'CURRICULUM_PACK_PROGRESS' ? '%' : ''}${item.completed ? ' · Complete' : ''}` }),
      ]))),
      campaignForm(campaign, (payload) => onUpdateCampaign?.(campaign.id, payload), collections),
    ]))) : node('p', { className: 'language-empty-copy', text: 'No campaign yet. Create an evidence-backed Norway-oriented campaign below.' }),
    campaigns.length ? null : campaignForm(null, onCreateCampaign, collections),
  ]);

  replace(mount, node('div', { className: 'language-progress-view' }, [
    levelCard, todayCard, consistencyCard, collectionCard, achievementCardSection, campaignCard,
  ]));
}
