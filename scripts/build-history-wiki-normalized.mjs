import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import {
  aliases,
  archaeologySeeds,
  conversationCorrections,
  erasDraft,
  forcedTopicRoles,
  genealogyEdges,
  journalClaimSeeds,
  journalEntrySeeds,
  mergeDecisions,
  projectPrivacy,
  unfinishedThreads,
} from "./history-wiki-phase2-config.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const sourceRoot = path.join(root, "ChatGPT", "processed", "batches");
const dataRoot = path.join(sourceRoot, "data");
const normalizedRoot = path.join(root, "normalized");
const reportsRoot = path.join(root, "reports");
const docsRoot = path.join(root, "docs", "history-wiki");
const privacyRank = { normal: 0, private: 1, sensitive: 2, third_party_sensitive: 3 };
const allowedIdeaStatuses = new Set(["active", "completed", "abandoned", "revisited", "unclear"]);

function assertCanonicalSource() {
  const canonical = path.resolve(sourceRoot).replaceAll("\\", "/");
  if (!canonical.endsWith("/ChatGPT/processed/batches") || canonical.includes("history_archive")) {
    throw new Error(`Refusing non-canonical History Wiki source: ${canonical}`);
  }
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function readJsonl(filePath) {
  return fs.readFileSync(filePath, "utf8").split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
}

function writeJson(relativePath, value) {
  const target = path.join(normalizedRoot, relativePath);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function writeJsonl(relativePath, values) {
  const target = path.join(normalizedRoot, relativePath);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, `${values.map((value) => JSON.stringify(value)).join("\n")}\n`, "utf8");
}

const dateFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Warsaw", year: "numeric", month: "2-digit", day: "2-digit",
});
const localDate = (timestamp) => dateFormatter.format(new Date(timestamp * 1000));
const uniq = (values) => [...new Set(values.filter(Boolean))];
const maxPrivacy = (levels) => uniq(levels).sort((a, b) => (privacyRank[b] ?? 0) - (privacyRank[a] ?? 0))[0] || "normal";
const provenance = (sourceId, sourcePath) => ({
  source_entity_id: sourceId,
  source_path: sourcePath,
  normalization_version: "history-wiki-phase2@1",
  normalized_at: "2026-09-23",
});
const eraSourceConversations = {
  ER01: ["4dbbca6e-f60e-43c8-8f21-842e728401de", "7cc236e1-9af2-4bd4-9548-06017821cce3", "d2f45f7d-ccef-47a1-b1be-ee0fe7f8c5de"],
  ER02: ["25de93c2-058b-4684-9449-c821cfcd4d88", "e77639b6-6d1f-4cba-bad3-3ccd314acedb", "997ab600-2967-4e89-b796-851bb3a890a7"],
  ER03: ["67d68d10-7ce4-8008-acbc-f1af63d2e58f", "68998475-c514-832e-ad32-cf4ac8f379f2"],
  ER04: ["68f6d20f-98d0-832d-8e96-756717df96b0", "68f740e9-7138-8326-b5aa-924246375ae3", "68f775cf-ee14-832b-91a2-01670171ac7e"],
  ER05: ["69fe3c96-f7d0-83eb-af2e-45c37022289f", "69ff258f-9380-83eb-a882-d4870e281a36", "69ff0fe4-b61c-83eb-acd1-85372c24ca6c"],
  ER06: ["6a4d2099-1c40-83ed-a629-152fa57161ba", "6a82edb0-513c-83eb-9751-9660d13d76ef", "6aabead8-c96c-83eb-bae8-4847acbde723", "6aac47b8-73bc-83ed-b742-e2249fb4a8e1"],
};

export function buildNormalized() {
  assertCanonicalSource();
  const manifest = readJson(path.join(sourceRoot, "manifest.json"));
  const canonicalConversations = readJsonl(path.join(dataRoot, "conversations.jsonl"));
  const canonicalProjects = readJson(path.join(dataRoot, "projects.json"));
  const canonicalTopics = readJson(path.join(dataRoot, "topics.json"));
  const canonicalIdeas = readJsonl(path.join(dataRoot, "ideas.jsonl"));
  const canonicalEvents = readJsonl(path.join(dataRoot, "events.jsonl"));
  const canonicalRelations = readJsonl(path.join(dataRoot, "relations.jsonl"));
  const canonicalInsights = readJsonl(path.join(dataRoot, "insights.jsonl"));
  const canonicalEvidence = readJsonl(path.join(dataRoot, "evidence.jsonl"));
  const canonicalEventById = new Map(canonicalEvents.map((row) => [row.event_id, row]));
  const normalizedGenealogyEdges = genealogyEdges.map((edge) => ({
    ...edge,
    from: edge.from_project_id,
    to: edge.to_project_id,
    evidence_ids: uniq(edge.event_ids.flatMap((id) => canonicalEventById.get(id)?.evidence_ids || [])),
  }));

  if (canonicalConversations.length !== 2875 || manifest.processed_batches.length !== 32) {
    throw new Error("Canonical source coverage changed; expected 2,875 conversations and 32 batches.");
  }

  const canonicalConversationById = new Map(canonicalConversations.map((row) => [row.conversation_id, row]));
  const projectIds = new Set(canonicalProjects.map((row) => row.project_id));
  const topicIds = new Set(canonicalTopics.map((row) => row.topic_id));
  const eventIds = new Set(canonicalEvents.map((row) => row.event_id));
  const ideaIds = new Set(canonicalIdeas.map((row) => row.idea_id));
  const messageById = new Map();
  const firstUserMessageByConversation = new Map();
  const messageJournalDays = new Map();

  for (let batchIndex = 0; batchIndex < 32; batchIndex += 1) {
    const batchName = `batch_${String(batchIndex).padStart(3, "0")}.jsonl`;
    for (const conversation of readJsonl(path.join(sourceRoot, batchName))) {
      for (const message of conversation.messages || []) {
        if (!message.message_id) continue;
        const indexed = { ...message, conversation_id: conversation.conversation_id, source_batch: batchName };
        messageById.set(message.message_id, indexed);
        if (message.role === "user" && !firstUserMessageByConversation.has(conversation.conversation_id)) {
          firstUserMessageByConversation.set(conversation.conversation_id, message.message_id);
        }
        if (message.role !== "user" || !message.create_time) continue;
        const dayKey = localDate(message.create_time);
        const sourceCatalog = canonicalConversationById.get(conversation.conversation_id);
        const day = messageJournalDays.get(dayKey) || {
          date: dayKey,
          timezone: "Europe/Warsaw",
          user_message_count: 0,
          message_ids: [],
          conversation_ids: [],
          source_timestamps: [],
          privacy_levels: [],
        };
        day.user_message_count += 1;
        day.message_ids.push(message.message_id);
        day.conversation_ids.push(conversation.conversation_id);
        day.source_timestamps.push(message.create_time_iso || new Date(message.create_time * 1000).toISOString());
        day.privacy_levels.push(sourceCatalog?.privacy_level || "private");
        messageJournalDays.set(dayKey, day);
      }
    }
  }

  for (const [conversationId, correction] of Object.entries(conversationCorrections)) {
    if (!canonicalConversationById.has(conversationId)) throw new Error(`Unknown corrected conversation: ${conversationId}`);
    for (const id of correction.evidence_message_ids || []) {
      if (!messageById.has(id)) throw new Error(`Unknown correction evidence message: ${id}`);
    }
    for (const id of correction.project_ids || []) if (!projectIds.has(id)) throw new Error(`Unknown correction project: ${id}`);
    for (const id of correction.topic_ids || []) if (!topicIds.has(id)) throw new Error(`Unknown correction topic: ${id}`);
  }

  const conversations = canonicalConversations.map((conversation) => {
    const correction = conversationCorrections[conversation.conversation_id] || {};
    return {
      ...conversation,
      ...Object.fromEntries(Object.entries(correction).filter(([key]) => !["review_decision", "evidence_message_ids"].includes(key))),
      normalized: true,
      review_decision: correction.review_decision || (conversation.legacy_classification ? "retained_after_bounded_legacy_review" : "not_in_review_queue"),
      review_evidence_message_ids: correction.evidence_message_ids || [firstUserMessageByConversation.get(conversation.conversation_id)].filter(Boolean),
      provenance: provenance(conversation.conversation_id, `ChatGPT/processed/batches/data/conversations.jsonl#${conversation.conversation_id}`),
    };
  });
  const conversationById = new Map(conversations.map((row) => [row.conversation_id, row]));

  const conversationReviews = conversations
    .filter((row) => row.legacy_classification || conversationCorrections[row.conversation_id])
    .map((row) => ({
      conversation_id: row.conversation_id,
      review_decision: row.review_decision,
      previous_project_ids: canonicalConversationById.get(row.conversation_id).project_ids || [],
      normalized_project_ids: row.project_ids || [],
      previous_topic_ids: canonicalConversationById.get(row.conversation_id).topic_ids || [],
      normalized_topic_ids: row.topic_ids || [],
      previous_privacy_level: canonicalConversationById.get(row.conversation_id).privacy_level,
      normalized_privacy_level: row.privacy_level,
      supporting_message_ids: row.review_evidence_message_ids,
      reviewed_at: "2026-09-23",
    }));

  const projects = canonicalProjects.map((project) => {
    const conversationsForProject = conversations.filter((row) => (row.project_ids || []).includes(project.project_id));
    const review = projectPrivacy[project.project_id];
    const privacyLevel = review?.[0] || project.privacy_level || "private";
    return {
      ...project,
      privacy_level: privacyLevel,
      privacy_review: review ? { decision: privacyLevel, rationale: review[1], confidence: "high", reviewed_at: "2026-09-23" } : { decision: privacyLevel, rationale: "Retained canonical reviewed value.", confidence: "high", reviewed_at: "2026-09-23" },
      aliases: aliases.filter((alias) => alias.canonical_id === project.project_id || alias.related_id === project.project_id || alias.contexts?.some((context) => context.project_id === project.project_id)).map((alias) => alias.alias),
      last_seen: conversationsForProject.map((row) => row.date).sort().at(-1) || project.first_seen,
      source_project_ids: [project.project_id],
      status: project.status || "unclear",
      genealogy_edge_ids: normalizedGenealogyEdges.filter((edge) => edge.from_project_id === project.project_id || edge.to_project_id === project.project_id).map((edge) => edge.edge_id),
      unfinished_thread_ids: unfinishedThreads.filter((thread) => thread.project_ids.includes(project.project_id)).map((thread) => thread.thread_id),
      provenance: provenance(project.project_id, `ChatGPT/processed/batches/data/projects.json#${project.project_id}`),
    };
  });

  const topicConversationCounts = new Map();
  for (const conversation of conversations) for (const id of conversation.topic_ids || []) topicConversationCounts.set(id, (topicConversationCounts.get(id) || 0) + 1);
  const topicIdeaCounts = new Map();
  for (const idea of canonicalIdeas) for (const id of idea.topic_ids || []) topicIdeaCounts.set(id, (topicIdeaCounts.get(id) || 0) + 1);
  const topics = canonicalTopics.map((topic) => {
    const totalUses = (topicConversationCounts.get(topic.topic_id) || 0) + (topicIdeaCounts.get(topic.topic_id) || 0);
    const navigationRole = forcedTopicRoles[topic.topic_id] || (topic.parent_id === null ? "section" : totalUses <= 2 ? "tag" : "topic");
    return {
      ...topic,
      aliases: aliases.filter((alias) => alias.canonical_id === topic.topic_id || alias.related_id === topic.topic_id).map((alias) => alias.alias),
      navigation_role: navigationRole,
      usage: { conversations: topicConversationCounts.get(topic.topic_id) || 0, ideas: topicIdeaCounts.get(topic.topic_id) || 0, total: totalUses },
      provenance: provenance(topic.topic_id, `ChatGPT/processed/batches/data/topics.json#${topic.topic_id}`),
    };
  });
  const topicNavigation = {
    generated_at: "2026-09-23",
    rule: "Top-level nodes are sections unless explicitly reviewed as topics; leaf nodes with <=2 uses default to tags; explicit human decisions override the rule.",
    counts: Object.fromEntries(["section", "topic", "tag"].map((role) => [role, topics.filter((topic) => topic.navigation_role === role).length])),
    roles: Object.fromEntries(["section", "topic", "tag"].map((role) => [role, topics.filter((topic) => topic.navigation_role === role).map((topic) => topic.topic_id)])),
  };

  const ideas = canonicalIdeas.map((idea) => {
    if (!allowedIdeaStatuses.has(idea.status)) throw new Error(`Invalid idea status: ${idea.idea_id}/${idea.status}`);
    return {
      ...idea,
      aliases: [],
      provenance: {
        ...provenance(idea.idea_id, `ChatGPT/processed/batches/data/ideas.jsonl#${idea.idea_id}`),
        source_batch: idea.source_batch,
        origin: idea.origin || null,
        origin_role: idea.origin_role,
      },
    };
  });

  const events = canonicalEvents.map((event) => ({ ...event, aliases: [], provenance: provenance(event.event_id, `ChatGPT/processed/batches/data/events.jsonl#${event.event_id}`) }));
  const relations = canonicalRelations.map((relation) => ({ ...relation, aliases: [], provenance: provenance(relation.relation_id, `ChatGPT/processed/batches/data/relations.jsonl#${relation.relation_id}`) }));
  const insights = canonicalInsights.map((insight) => ({ ...insight, aliases: [], provenance: provenance(insight.insight_id, `ChatGPT/processed/batches/data/insights.jsonl#${insight.insight_id}`) }));
  const evidence = canonicalEvidence.map((item) => ({ ...item, aliases: [], provenance: provenance(item.evidence_id, `ChatGPT/processed/batches/data/evidence.jsonl#${item.evidence_id}`) }));

  for (const edge of normalizedGenealogyEdges) {
    if (!projectIds.has(edge.from_project_id) || !projectIds.has(edge.to_project_id)) throw new Error(`Invalid genealogy edge ${edge.edge_id}`);
    for (const id of edge.event_ids) if (!eventIds.has(id)) throw new Error(`Unknown genealogy event ${id}`);
    for (const id of edge.conversation_ids) if (!canonicalConversationById.has(id)) throw new Error(`Unknown genealogy conversation ${id}`);
  }

  const ideaById = new Map(ideas.map((idea) => [idea.idea_id, idea]));
  const ideaArchaeology = archaeologySeeds.map(([ideaId, slug]) => {
    const idea = ideaById.get(ideaId);
    if (!idea) throw new Error(`Unknown archaeology idea: ${ideaId}`);
    const laterEvents = events.filter((event) => event.date >= idea.first_seen && (event.project_ids || []).some((id) => idea.project_ids.includes(id))).slice(0, 5);
    return {
      archaeology_id: `IA-${ideaId.slice(1)}`,
      slug,
      idea_id: ideaId,
      first_seen: idea.first_seen,
      first_appearance: { date: idea.first_seen, evidence_ids: idea.evidence_ids || [], source_batch: idea.source_batch },
      current_status: idea.status,
      transformation_note: laterEvents.length ? "Later same-project events are retained as context candidates, not asserted as proof that this idea was completed." : "No later transformation is asserted from the available evidence.",
      linked_event_ids: laterEvents.map((event) => event.event_id),
      latest_relevant_evidence: laterEvents.length ? { event_id: laterEvents.at(-1).event_id, date: laterEvents.at(-1).date, evidence_ids: laterEvents.at(-1).evidence_ids || [] } : { date: idea.first_seen, evidence_ids: idea.evidence_ids || [] },
      project_ids: idea.project_ids,
      confidence: idea.confidence,
      privacy_level: idea.privacy_level,
    };
  });

  const normalizedUnfinishedThreads = unfinishedThreads.map((thread) => {
    const messages = thread.evidence_message_ids.map((id) => {
      const message = messageById.get(id);
      if (!message || message.role !== "user") throw new Error(`Invalid unfinished-thread evidence: ${thread.thread_id}/${id}`);
      return message;
    });
    return { ...thread, conversation_ids: uniq(messages.map((message) => message.conversation_id)), evidence_role: "user" };
  });

  const normalizedEras = erasDraft.map(({ title, description, ...era }) => {
    const sourceConversationIds = eraSourceConversations[era.era_id] || [];
    for (const id of sourceConversationIds) if (!canonicalConversationById.has(id)) throw new Error(`Unknown era source conversation: ${era.era_id}/${id}`);
    return { ...era, working_title: title, summary: description, source_conversation_ids: sourceConversationIds };
  });

  const journalCandidates = [...messageJournalDays.values()].sort((a, b) => a.date.localeCompare(b.date)).map((day) => ({
    date: day.date,
    timezone: day.timezone,
    user_message_count: day.user_message_count,
    conversation_count: uniq(day.conversation_ids).length,
    conversation_ids: uniq(day.conversation_ids),
    max_privacy_level: maxPrivacy(day.privacy_levels),
    source_timestamp_min: day.source_timestamps.sort()[0],
    source_timestamp_max: day.source_timestamps.sort().at(-1),
    grouping_basis: "individual_user_message_timestamp",
  }));

  const claims = journalClaimSeeds.map((seed) => {
    const messages = seed.supporting_message_ids.map((id) => {
      const message = messageById.get(id);
      if (!message) throw new Error(`Unknown Journal supporting message: ${seed.claim_id}/${id}`);
      if (message.role !== "user") throw new Error(`Assistant contamination: ${seed.claim_id}/${id}/${message.role}`);
      if (localDate(message.create_time) !== seed.local_date) throw new Error(`Journal timezone mismatch: ${seed.claim_id}/${id}/${localDate(message.create_time)} != ${seed.local_date}`);
      return message;
    });
    return {
      ...seed,
      conversation_ids: uniq(messages.map((message) => message.conversation_id)),
      source_timestamp: messages.map((message) => message.create_time_iso || new Date(message.create_time * 1000).toISOString()).sort()[0],
      source_timestamps: messages.map((message) => message.create_time_iso || new Date(message.create_time * 1000).toISOString()).sort(),
      source_privacy_levels: uniq(messages.map((message) => conversationById.get(message.conversation_id)?.privacy_level || "private")),
      contradiction_group_id: null,
    };
  });
  const claimById = new Map(claims.map((claim) => [claim.claim_id, claim]));
  const journalPilot = journalEntrySeeds.map((entry) => {
    const claimIds = entry.sections.flatMap((section) => section.sentences.flatMap((sentence) => sentence.claim_ids));
    for (const id of claimIds) {
      const claim = claimById.get(id);
      if (!claim) throw new Error(`Journal sentence references unknown claim ${id}`);
      if (claim.local_date !== entry.local_date) throw new Error(`Journal sentence references wrong-day claim ${id}`);
    }
    return {
      ...entry,
      max_privacy_level: maxPrivacy(entry.sections.map((section) => section.privacy_level)),
      claim_ids: uniq(claimIds),
      source_conversation_ids: uniq(claimIds.flatMap((id) => claimById.get(id).conversation_ids)),
      provenance_note: "Every factual sentence maps to one or more user-message-supported claim IDs; this is reconstruction, not a contemporaneous diary.",
    };
  });

  const usedClaimIds = new Set(journalPilot.flatMap((entry) => entry.claim_ids));
  const unsupportedSentences = journalPilot.flatMap((entry) => entry.sections.flatMap((section) => section.sentences.filter((sentence) => !sentence.claim_ids.length)));
  const unusedClaims = claims.filter((claim) => !usedClaimIds.has(claim.claim_id));
  const localMidnightCrossings = claims.filter((claim) => claim.source_timestamps.some((timestamp) => timestamp.slice(0, 10) !== claim.local_date));
  if (unsupportedSentences.length || unusedClaims.length) throw new Error(`Journal ledger mismatch: ${unsupportedSentences.length} unsupported sentences, ${unusedClaims.length} unused claims.`);

  const validation = {
    status: "pass",
    pilot_days: journalPilot.length,
    claims: claims.length,
    factual_sentences: journalPilot.reduce((sum, entry) => sum + entry.sections.reduce((inner, section) => inner + section.sentences.length, 0), 0),
    unsupported_sentences: unsupportedSentences.length,
    unused_claims: unusedClaims.length,
    assistant_sourced_claims: 0,
    timezone_mismatches: 0,
    local_midnight_crossing_claims: localMidnightCrossings.map((claim) => claim.claim_id),
    candidate_days_from_conversation_creation_time_phase1: 731,
    candidate_days_from_user_message_timestamps_phase2: journalCandidates.length,
    contradictions: [],
    privacy_sections: journalPilot.reduce((sum, entry) => sum + entry.sections.length, 0),
  };

  const normalizedManifest = {
    schema_version: "history-wiki-normalized-v2",
    generated_at: new Date().toISOString(),
    canonical_source: "ChatGPT/processed/batches/data + batch_000..031",
    excluded_source: "ChatGPT/processed/batches/history_archive (historical snapshot only)",
    canonical_archive_revision: manifest.master_revision,
    counts: {
      conversations: conversations.length, projects: projects.length, topics: topics.length, ideas: ideas.length,
      events: events.length, relations: relations.length, insights: insights.length, evidence: evidence.length,
      genealogy_edges: normalizedGenealogyEdges.length, archaeology_records: ideaArchaeology.length,
      unfinished_threads: normalizedUnfinishedThreads.length, eras: normalizedEras.length, journal_candidate_days: journalCandidates.length,
      journal_pilot_days: journalPilot.length, journal_claims: claims.length,
    },
  };

  writeJson("manifest.json", normalizedManifest);
  writeJsonl("conversations.jsonl", conversations);
  writeJsonl("conversation_reviews.jsonl", conversationReviews);
  writeJson("projects.json", projects);
  writeJson("topics.json", topics);
  writeJsonl("ideas.jsonl", ideas);
  writeJsonl("events.jsonl", events);
  writeJsonl("relations.jsonl", relations);
  writeJsonl("insights.jsonl", insights);
  writeJsonl("evidence.jsonl", evidence);
  writeJson("aliases.json", aliases);
  writeJsonl("merge_ledger.jsonl", mergeDecisions);
  writeJson("topic_navigation.json", topicNavigation);
  writeJson("project_genealogies.json", normalizedGenealogyEdges);
  writeJson("idea_archaeology.json", ideaArchaeology);
  writeJson("unfinished_threads.json", normalizedUnfinishedThreads);
  writeJson("eras_draft.json", normalizedEras);
  writeJsonl("journal_candidates.jsonl", journalCandidates);
  writeJsonl("journal_claims_pilot.jsonl", claims);
  writeJsonl("journal_pilot.jsonl", journalPilot);
  writeJson("journal_pilot_validation.json", validation);

  fs.mkdirSync(reportsRoot, { recursive: true });
  fs.mkdirSync(docsRoot, { recursive: true });
  const crossingText = validation.local_midnight_crossing_claims.length ? validation.local_midnight_crossing_claims.join(", ") : "none";
  const validationMarkdown = `# Journal Pilot Validation\n\nDate: 2026-09-23  \nStatus: **PASS**\n\nThe pilot contains **${validation.pilot_days} days**, **${validation.claims} claims**, and **${validation.factual_sentences} factual sentences**. Every factual sentence maps to one or more ledger claims, and every claim is supported only by user-authored messages.\n\n| Check | Result |\n| --- | ---: |\n| Unsupported factual sentences | ${validation.unsupported_sentences} |\n| Unused claims | ${validation.unused_claims} |\n| Assistant-sourced claims | ${validation.assistant_sourced_claims} |\n| Timezone/day mismatches | ${validation.timezone_mismatches} |\n| Explicit contradiction groups | ${validation.contradictions.length} |\n| Privacy-segmented sections | ${validation.privacy_sections} |\n\n## Timestamp finding\n\nPhase 1's conversation-creation-date grouping produced 731 candidate dates. Grouping **individual user messages** in \`Europe/Warsaw\` produces **${validation.candidate_days_from_user_message_timestamps_phase2} candidate dates**. Claims crossing a UTC date boundary while remaining on the validated Warsaw local day: ${crossingText}.\n\n## Editorial verdict\n\nThe pilot deliberately retains ordinary errands, unfinished work, profanity, projects, relationship context and severe emotional material. It does not smooth them into a generic emotional summary. Sensitive and third-party-sensitive passages remain separate renderable sections. This validation authorizes review of the pilot only; it does **not** authorize a full Journal build.\n`;
  fs.writeFileSync(path.join(reportsRoot, "journal_pilot_validation.md"), validationMarkdown, "utf8");
  fs.writeFileSync(path.join(docsRoot, "JOURNAL_PILOT_VALIDATION.md"), validationMarkdown, "utf8");

  return { normalizedManifest, validation, topicNavigation };
}

const invokedDirectly = process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url;
if (invokedDirectly) console.log(JSON.stringify(buildNormalized(), null, 2));
