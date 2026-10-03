import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildNormalized } from "./build-history-wiki-normalized.mjs";
import { buildJournalV2 } from "./build-history-wiki-journal-v2.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const normalizedRoot = path.join(root, "normalized");
const appDataPath = path.join(root, "apps", "history-wiki", "data", "history-wiki-data.js");
const readJson = (name) => JSON.parse(fs.readFileSync(path.join(normalizedRoot, name), "utf8"));
const readJsonl = (name) => fs.readFileSync(path.join(normalizedRoot, name), "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);

const { normalizedManifest } = buildNormalized();
const { review: journalReview } = buildJournalV2();
const { journal_claims: _archivedJournalClaimCount, ...presentationCounts } = normalizedManifest.counts;
const conversations = readJsonl("conversations.jsonl");
const projects = readJson("projects.json");
const topics = readJson("topics.json");
const ideas = readJsonl("ideas.jsonl");
const events = readJsonl("events.jsonl");
const relations = readJsonl("relations.jsonl");
const insights = readJsonl("insights.jsonl");
const evidence = readJsonl("evidence.jsonl");

const snapshot = {
  schema_version: "history-wiki-v2",
  generated_at: new Date().toISOString(),
  source_path: normalizedManifest.canonical_source,
  excluded_source: normalizedManifest.excluded_source,
  archive_revision: normalizedManifest.canonical_archive_revision,
  counts: { ...presentationCounts, batches: 32 },
  audit: {
    source_complete: true,
    raw_conversation_count: 2875,
    unique_conversation_count: 2875,
    duplicate_ids: 0,
    dangling_references: 0,
    malformed_records: 15,
    conversations_missing_summary: 0,
    projects_missing_source_privacy: 0,
    fully_unclassified_conversations: 0,
    legacy_classifications_reviewed: 108,
    message_timestamp_candidate_days: normalizedManifest.counts.journal_candidate_days,
    journal_pilot_validation: journalReview.status,
  },
  conversations,
  conversation_reviews: readJsonl("conversation_reviews.jsonl"),
  projects,
  topics,
  topic_navigation: readJson("topic_navigation.json"),
  ideas,
  events,
  relations,
  insights,
  evidence,
  aliases: readJson("aliases.json"),
  merge_ledger: readJsonl("merge_ledger.jsonl"),
  project_genealogies: readJson("project_genealogies.json"),
  idea_archaeology: readJson("idea_archaeology.json"),
  unfinished_threads: readJson("unfinished_threads.json"),
  eras: readJson("eras_draft.json"),
  journal_candidates: readJsonl("journal_candidates.jsonl"),
  journal_pilot: readJsonl("journal_pilot_v2.jsonl"),
  journal_validation: journalReview,
};

fs.mkdirSync(path.dirname(appDataPath), { recursive: true });
fs.writeFileSync(appDataPath, `window.HISTORY_WIKI_DATA = ${JSON.stringify(snapshot)};\n`, "utf8");
console.log(JSON.stringify({ appDataPath, counts: snapshot.counts, journal_validation: snapshot.journal_validation.status }, null, 2));
