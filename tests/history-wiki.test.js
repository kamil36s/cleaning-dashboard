import fs from "node:fs";
import { Window } from "happy-dom";
import { describe, expect, it } from "vitest";

const indexHtml = fs.readFileSync("apps/history-wiki/index.html", "utf8");
const dataScript = fs.readFileSync("apps/history-wiki/data/history-wiki-data.js", "utf8");
const appScript = fs.readFileSync("apps/history-wiki/history-wiki.js", "utf8");

function createWiki(hash = "#overview", protocol = "http") {
  const url = protocol === "file" ? `file:///C:/history-wiki/index.html${hash}` : `http://localhost/apps/history-wiki/${hash}`;
  const window = new Window({ url });
  const inertHtml = indexHtml.replace(/<link rel="stylesheet"[^>]*>/g, "").replace(/<script src="[^"]+"><\/script>/g, "");
  window.document.write(inertHtml);
  window.eval(dataScript);
  window.eval(appScript);
  return window;
}

const readJson = (file) => JSON.parse(fs.readFileSync(file, "utf8"));
const readJsonl = (file) => fs.readFileSync(file, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);

describe("History Wiki V2", () => {
  it("renders the source-complete normalized overview without raw message arrays", () => {
    const window = createWiki();
    const text = window.document.querySelector("#wiki-content")?.textContent || "";
    expect(text).toContain("2875");
    expect(text).toContain("Phase 2");
    expect(dataScript).not.toMatch(/"messages"\s*:\s*\[/);
  });

  it("uses reviewed project privacy and reveals private projects only when enabled", () => {
    const window = createWiki("#projects");
    const content = window.document.querySelector("#wiki-content");
    expect(content?.textContent).not.toContain("Personal operating system / stateful assistant");
    const privacy = window.document.querySelector("#privacy-mode");
    privacy.value = "private";
    privacy.dispatchEvent(new window.Event("change"));
    expect(content?.textContent).toContain("Personal operating system / stateful assistant");
  });

  it("shows the 14-day message-timestamp Journal pilot and keeps gated prose out of the DOM", () => {
    const window = createWiki("#journal");
    const content = window.document.querySelector("#wiki-content");
    expect(content?.textContent).toContain("14 celowo zróżnicowanych dni");
    expect(content?.querySelectorAll(".journal-index a")).toHaveLength(14);

    window.location.hash = "#journal/2025-03-16";
    window.dispatchEvent(new window.HashChangeEvent("hashchange"));
    expect(content?.textContent).toContain("fragmenty ukryte");
    expect(content?.textContent).not.toContain("chcę się zabić");

    let privacy = window.document.querySelector("#privacy-mode");
    privacy.value = "private";
    privacy.dispatchEvent(new window.Event("change"));
    expect(content?.textContent).toContain("Rano próbuję rozłożyć sprzątanie");
    expect(content?.textContent).not.toContain("chcę się zabić");

    privacy = window.document.querySelector("#privacy-mode");
    privacy.value = "sensitive";
    privacy.dispatchEvent(new window.Event("change"));
    expect(content?.textContent).toContain("chcę się zabić");
    expect(content?.querySelectorAll(".journal-sources a").length).toBeGreaterThan(0);
    expect(content?.querySelectorAll(".claim-chip, .claim-ledger")).toHaveLength(0);
  });

  it("publishes the human merge ledger and passing lightweight Journal validation", () => {
    const qualityWindow = createWiki("#quality");
    expect(qualityWindow.document.querySelector("#wiki-content")?.textContent).toContain("do_not_merge");
    expect(qualityWindow.document.querySelectorAll("#wiki-content tbody tr")).toHaveLength(6);

    const journalWindow = createWiki("#journal");
    const text = journalWindow.document.querySelector("#wiki-content")?.textContent || "";
    expect(text).toContain("Assistant content included");
    expect(text).toContain("Legacy sentence annotations shipped");
    expect(text).toContain("Message-level candidate days");
    expect(text).toContain("767");
  });

  it("keeps normalized IDs, provenance, topic roles and genealogy endpoints valid", () => {
    const canonicalProjects = readJson("ChatGPT/processed/batches/data/projects.json");
    const canonicalTopics = readJson("ChatGPT/processed/batches/data/topics.json");
    const normalizedProjects = readJson("normalized/projects.json");
    const normalizedTopics = readJson("normalized/topics.json");
    const genealogy = readJson("normalized/project_genealogies.json");
    const projectIds = new Set(canonicalProjects.map((item) => item.project_id));

    expect(normalizedProjects.map((item) => item.project_id)).toEqual(canonicalProjects.map((item) => item.project_id));
    expect(normalizedTopics.map((item) => item.topic_id)).toEqual(canonicalTopics.map((item) => item.topic_id));
    expect(normalizedProjects.every((item) => item.provenance?.source_entity_id === item.project_id && Array.isArray(item.aliases))).toBe(true);
    expect(normalizedTopics.every((item) => ["section", "topic", "tag"].includes(item.navigation_role) && item.provenance?.source_entity_id === item.topic_id)).toBe(true);
    expect(genealogy.every((edge) => projectIds.has(edge.from) && projectIds.has(edge.to) && Array.isArray(edge.evidence_ids) && Array.isArray(edge.conversation_ids) && edge.rationale)).toBe(true);
  });

  it("indexes only same-day user messages and attaches complete bundles to Journal V2", () => {
    const messages = new Map();
    for (let index = 0; index < 32; index += 1) {
      const batch = readJsonl(`ChatGPT/processed/batches/batch_${String(index).padStart(3, "0")}.jsonl`);
      batch.forEach((conversation) => (conversation.messages || []).forEach((message) => messages.set(message.message_id, message)));
    }
    const formatter = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Warsaw", year: "numeric", month: "2-digit", day: "2-digit" });
    const dayIndex = readJsonl("normalized/journal_day_index.jsonl");
    const entries = readJsonl("normalized/journal_pilot_v2.jsonl");
    const generationState = readJson("normalized/journal_generation_state.json");
    const days = new Map(dayIndex.map((day) => [day.local_date, day]));

    expect(dayIndex).toHaveLength(767);
    expect(Object.keys(generationState.days)).toHaveLength(767);
    expect(generationState.completed_day_count).toBe(14);
    expect(generationState.pending_day_count).toBe(753);
    for (const day of dayIndex) {
      expect(day.roles_included).toEqual(["user"]);
      expect(day.user_message_count).toBe(day.user_message_ids.length);
      for (const messageId of day.user_message_ids) {
        const message = messages.get(messageId);
        expect(message?.role).toBe("user");
        expect(formatter.format(new Date(message.create_time * 1000))).toBe(day.local_date);
      }
    }
    expect(entries).toHaveLength(14);
    for (const entry of entries) {
      const day = days.get(entry.local_date);
      expect(entry.assistant_content_excluded).toBe(true);
      expect(entry.source_user_message_ids).toEqual(day.user_message_ids);
      expect(entry.source_conversation_ids).toEqual(day.source_conversation_ids);
      expect(entry.word_count).toBeGreaterThanOrEqual(80);
      expect(entry.paragraph_count).toBeGreaterThanOrEqual(2);
      expect(entry.paragraph_count).toBeLessThanOrEqual(8);
      expect(JSON.stringify(entry)).not.toMatch(/JC\d+|claim_ids|confidence/);
    }
  });

  it("opens a Journal source as a conversation detail page", () => {
    const window = createWiki("#journal/2026-09-17");
    const privacy = window.document.querySelector("#privacy-mode");
    privacy.value = "sensitive";
    privacy.dispatchEvent(new window.Event("change"));
    const link = window.document.querySelector(".journal-sources a");
    expect(link?.getAttribute("href")).toMatch(/^#conversation\//);
    window.location.hash = link.getAttribute("href");
    window.dispatchEvent(new window.HashChangeEvent("hashchange"));
    expect(window.document.querySelector("#wiki-content")?.textContent).toContain("Provenance");
  });

  it("operates as a direct-file offline page", () => {
    const window = createWiki("#journal", "file");
    expect(window.document.querySelector("#wiki-content")?.textContent).toContain("kontrolowany pilot");
    expect(window.document.querySelectorAll(".journal-index a")).toHaveLength(14);
  });
});
