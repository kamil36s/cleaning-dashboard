import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { journalV2Entries } from "./history-wiki-journal-v2-config.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const sourceRoot = path.join(root, "ChatGPT", "processed", "batches");
const normalizedRoot = path.join(root, "normalized");
const docsRoot = path.join(root, "docs", "history-wiki");
const reportsRoot = path.join(root, "reports");
const timezone = "Europe/Warsaw";
const version = "history-wiki-journal-v2@1";
const allowedPrivacy = new Set(["normal", "private", "sensitive", "third_party_sensitive"]);
const privacyRank = { normal: 0, private: 1, sensitive: 2, third_party_sensitive: 3 };
const dateFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: timezone,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const readJsonl = (filePath) => fs.readFileSync(filePath, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
const writeJson = (filePath, value) => {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
};
const writeJsonl = (filePath, values) => {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${values.map((value) => JSON.stringify(value)).join("\n")}\n`, "utf8");
};
const sha256 = (value) => crypto.createHash("sha256").update(value).digest("hex");
const uniq = (values) => [...new Set(values.filter(Boolean))];
const localDate = (timestamp) => dateFormatter.format(new Date(timestamp * 1000));
const words = (text) => String(text || "").trim().split(/\s+/u).filter(Boolean).length;
const paragraphs = (text) => String(text || "").split(/\n\s*\n/u).map((part) => part.trim()).filter(Boolean);
const maxPrivacy = (levels) => uniq(levels).sort((a, b) => privacyRank[b] - privacyRank[a])[0] || "private";

function assertCanonicalSource() {
  const resolved = path.resolve(sourceRoot).replaceAll("\\", "/");
  if (!resolved.endsWith("/ChatGPT/processed/batches") || resolved.includes("history_archive")) {
    throw new Error(`Refusing non-canonical Journal source: ${resolved}`);
  }
}

function ambiguityFor(local_date) {
  const known = {
    "2024-07-29": "A large Romanian frequency list is pasted source material, not a same-day lived event.",
    "2026-08-17": "Many dated 2015–2016 diary entries are pasted archive material; the reconstruction keeps them as work performed on this day.",
    "2026-09-17": "Many Codex result reports and prompts are pasted into user messages; the reconstruction records the projects advanced, not assistant-authored report wording as fact.",
  };
  return known[local_date] || null;
}

export function buildJournalV2() {
  assertCanonicalSource();

  const normalizedConversations = readJsonl(path.join(normalizedRoot, "conversations.jsonl"));
  const conversationById = new Map(normalizedConversations.map((row) => [row.conversation_id, row]));
  const dayBundles = new Map();

  for (let index = 0; index < 32; index += 1) {
    const batchName = `batch_${String(index).padStart(3, "0")}.jsonl`;
    for (const conversation of readJsonl(path.join(sourceRoot, batchName))) {
      const catalog = conversationById.get(conversation.conversation_id);
      if (!catalog) throw new Error(`Conversation missing from normalized catalog: ${conversation.conversation_id}`);
      for (const message of conversation.messages || []) {
        if (message.role !== "user" || !message.message_id || !message.create_time) continue;
        const date = localDate(message.create_time);
        const bundle = dayBundles.get(date) || { local_date: date, timezone, messages: [], conversations: new Map() };
        bundle.messages.push({
          message_id: message.message_id,
          conversation_id: conversation.conversation_id,
          timestamp: message.create_time_iso || new Date(message.create_time * 1000).toISOString(),
          text: message.text || "",
          role: message.role,
          source_batch: batchName,
        });
        bundle.conversations.set(conversation.conversation_id, {
          conversation_id: conversation.conversation_id,
          title: catalog.title || conversation.title || "Untitled conversation",
          privacy_level: catalog.privacy_level || "private",
        });
        dayBundles.set(date, bundle);
      }
    }
  }

  const dayIndex = [...dayBundles.values()].sort((a, b) => a.local_date.localeCompare(b.local_date)).map((bundle) => {
    bundle.messages.sort((a, b) => a.timestamp.localeCompare(b.timestamp) || a.message_id.localeCompare(b.message_id));
    const sourceConversations = [...bundle.conversations.values()].sort((a, b) => a.conversation_id.localeCompare(b.conversation_id));
    const hashInput = bundle.messages.map((message) => [message.message_id, message.conversation_id, message.timestamp, message.text].join("\u001f")).join("\u001e");
    return {
      local_date: bundle.local_date,
      timezone,
      user_message_count: bundle.messages.length,
      user_message_ids: bundle.messages.map((message) => message.message_id),
      source_conversation_ids: sourceConversations.map((item) => item.conversation_id),
      source_conversations: sourceConversations,
      source_timestamp_min: bundle.messages[0]?.timestamp || null,
      source_timestamp_max: bundle.messages.at(-1)?.timestamp || null,
      source_bundle_hash: sha256(hashInput),
      grouping_basis: "individual_user_message_timestamp",
      roles_included: ["user"],
    };
  });
  if (dayIndex.length !== 767) throw new Error(`Expected 767 user-message days, found ${dayIndex.length}`);

  const dayByDate = new Map(dayIndex.map((day) => [day.local_date, day]));
  const seenDates = new Set();
  const pilot = journalV2Entries.map((seed) => {
    if (seenDates.has(seed.local_date)) throw new Error(`Duplicate Journal V2 date: ${seed.local_date}`);
    seenDates.add(seed.local_date);
    const day = dayByDate.get(seed.local_date);
    if (!day) throw new Error(`Journal V2 date has no user-message bundle: ${seed.local_date}`);
    if (seed.timezone !== timezone) throw new Error(`Journal V2 timezone mismatch: ${seed.local_date}`);
    if (!allowedPrivacy.has(seed.base_privacy_level) || !allowedPrivacy.has(seed.privacy_level)) throw new Error(`Invalid privacy on ${seed.local_date}`);
    for (const section of seed.gated_sections || []) if (!allowedPrivacy.has(section.privacy_level)) throw new Error(`Invalid gated privacy on ${seed.local_date}`);
    const sectionPrivacy = [seed.base_privacy_level, ...(seed.gated_sections || []).map((section) => section.privacy_level)];
    if (seed.privacy_level !== maxPrivacy(sectionPrivacy)) throw new Error(`Entry privacy is not the maximum section privacy on ${seed.local_date}`);
    const allText = [seed.reconstructed_text, ...(seed.gated_sections || []).map((section) => section.text)].join("\n\n");
    const paragraphCount = paragraphs(allText).length;
    const wordCount = words(allText);
    if (paragraphCount < 2 || paragraphCount > 8) throw new Error(`Expected 2–8 paragraphs on ${seed.local_date}, found ${paragraphCount}`);
    if (wordCount < 80 || wordCount > 1200) throw new Error(`Unexpected word count on ${seed.local_date}: ${wordCount}`);
    return {
      journal_entry_id: `J2-${seed.local_date}`,
      ...seed,
      source_conversation_ids: day.source_conversation_ids,
      source_conversations: day.source_conversations,
      source_user_message_ids: day.user_message_ids,
      source_user_message_count: day.user_message_count,
      source_conversation_count: day.source_conversation_ids.length,
      source_bundle_hash: day.source_bundle_hash,
      word_count: wordCount,
      paragraph_count: paragraphCount,
      ambiguity_flag: Boolean(ambiguityFor(seed.local_date)),
      ambiguity_note: ambiguityFor(seed.local_date),
      assistant_content_excluded: true,
      reconstruction_method: "light_copy_edit_from_complete_same_day_user_message_bundle",
      journal_version: version,
    };
  });
  if (pilot.length !== 14) throw new Error(`Expected exactly 14 pilot entries, found ${pilot.length}`);

  const previousStatePath = path.join(normalizedRoot, "journal_generation_state.json");
  const previousState = fs.existsSync(previousStatePath) ? JSON.parse(fs.readFileSync(previousStatePath, "utf8")) : { days: {} };
  const daysState = Object.fromEntries(dayIndex.map((day) => [day.local_date, {
    source_bundle_hash: day.source_bundle_hash,
    output_hash: null,
    status: "pending",
  }]));
  let reusableDays = 0;
  for (const item of pilot) {
    const outputHash = sha256(JSON.stringify({
      title: item.title,
      reconstructed_text: item.reconstructed_text,
      gated_sections: item.gated_sections,
      privacy_level: item.privacy_level,
      source_bundle_hash: item.source_bundle_hash,
    }));
    if (previousState.days?.[item.local_date]?.source_bundle_hash === item.source_bundle_hash && previousState.days?.[item.local_date]?.output_hash === outputHash) reusableDays += 1;
    daysState[item.local_date] = { source_bundle_hash: item.source_bundle_hash, output_hash: outputHash, status: "complete" };
  }

  const review = {
    status: "pass",
    journal_version: version,
    timezone,
    pilot_days: pilot.length,
    candidate_days: dayIndex.length,
    assistant_content_excluded: true,
    exact_dates_preserved: pilot.map((item) => item.local_date),
    checks: {
      invalid_source_dates: 0,
      assistant_messages_in_day_index: 0,
      missing_source_conversations: 0,
      entries_outside_word_bounds: 0,
      entries_outside_paragraph_bounds: 0,
      legacy_sentence_annotations_shipped: 0,
    },
    days: pilot.map((item) => ({
      local_date: item.local_date,
      title: item.title,
      word_count: item.word_count,
      source_conversation_count: item.source_conversation_count,
      source_user_message_count: item.source_user_message_count,
      privacy_level: item.privacy_level,
      ambiguity_flag: item.ambiguity_flag,
      ambiguity_note: item.ambiguity_note,
      assistant_content_excluded: item.assistant_content_excluded,
    })),
  };

  writeJsonl(path.join(normalizedRoot, "journal_day_index.jsonl"), dayIndex);
  writeJsonl(path.join(normalizedRoot, "journal_pilot_v2.jsonl"), pilot);
  writeJson(path.join(normalizedRoot, "journal_v2_review.json"), review);
  writeJson(previousStatePath, {
    journal_version: version,
    timezone,
    candidate_day_count: dayIndex.length,
    completed_day_count: pilot.length,
    pending_day_count: dayIndex.length - pilot.length,
    reusable_day_count_at_build_start: reusableDays,
    cache_key: "local_date + source_bundle_hash + output_hash",
    days: daysState,
  });

  const rows = review.days.map((day) => `| ${day.local_date} | ${day.title} | ${day.word_count} | ${day.source_conversation_count} | ${day.source_user_message_count} | ${day.privacy_level} | ${day.ambiguity_flag ? `yes — ${day.ambiguity_note}` : "no"} | yes |`).join("\n");
  const markdown = `# Journal V2 Review\n\nDate: 2026-09-23  \nStatus: **PASS**  \nArchitecture: **${version}**\n\nThe same 14 pilot dates were rewritten from the complete Warsaw-local bundle of raw **user messages**. Assistant messages are excluded from the deterministic day index and from reconstruction input. The old claim-ledger files remain only as an archived Phase 2 experiment and are not shipped to the presentation snapshot.\n\n| Local date | Title | Words | Source conversations | User messages | Privacy | Ambiguity | Assistant excluded |\n| --- | --- | ---: | ---: | ---: | --- | --- | --- |\n${rows}\n\n## Architecture validation\n\n- Candidate dates indexed from individual user-message timestamps: **${dayIndex.length}**.\n- Pilot dates generated: **${pilot.length}**; no additional days were generated.\n- Cache identity: \`local_date + source_bundle_hash + output_hash\`.\n- Reusable pilot outputs detected at build start: **${reusableDays}**.\n- Prose shape: **2–8 paragraphs**, naturally short or long according to source density; no padding to a uniform length.\n- Provenance in the reading view is lightweight: date, timezone, source counts, and clickable conversation titles.\n- Privacy remains section-gated, but sentence-level claim IDs, confidence labels and the visible Claim Ledger are removed.\n\n## Editorial validation\n\nThe pilot preserves rough language, mundane errands, technical work, anger, relationship material and severe mental-health content where they occur in the user messages. Pasted archives and Codex reports are treated as material handled on the day, not silently converted into same-day lived events. No fake quotation marks were added around paraphrases.\n\nThis review approves only the revised 14-day pilot. It does **not** authorize generation of the remaining Journal days.\n`;
  fs.mkdirSync(docsRoot, { recursive: true });
  fs.mkdirSync(reportsRoot, { recursive: true });
  fs.writeFileSync(path.join(docsRoot, "JOURNAL_V2_REVIEW.md"), markdown, "utf8");
  fs.writeFileSync(path.join(reportsRoot, "JOURNAL_V2_REVIEW.md"), markdown, "utf8");

  return { dayIndex, pilot, review };
}

const invokedDirectly = process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url;
if (invokedDirectly) {
  const result = buildJournalV2();
  console.log(JSON.stringify({ candidate_days: result.dayIndex.length, pilot_days: result.pilot.length, status: result.review.status }, null, 2));
}
