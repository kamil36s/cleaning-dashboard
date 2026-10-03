import { createJournalEntry, fetchJournalEntries } from "./journal-api.js";
import { journalEntryText } from "./journal-rich-text.js";

function node(tag, className = "", text = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text) element.textContent = text;
  return element;
}

function journalDisplayDate(value) {
  const raw = String(value || "");
  const date = /^\d{4}-\d{2}-\d{2}$/.test(raw) ? new Date(`${raw}T00:00:00`) : new Date(raw);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("pl-PL", { day: "2-digit", month: "long", year: "numeric" });
}

function latestDate(entries) {
  if (!entries.length) return "Brak";
  return journalDisplayDate(entries[0].entryDate);
}

export async function initJournalWidget(root, dependencies = {}) {
  if (!root) return null;
  const fetchEntries = dependencies.fetchEntries || fetchJournalEntries;
  const createEntry = dependencies.createEntry || createJournalEntry;

  root.innerHTML = `
    <div class="journal-widget-stats">
      <div><strong id="journal-widget-count">—</strong><span>Wpisy</span></div>
      <div><strong id="journal-widget-voice">—</strong><span>Z głosu</span></div>
      <div><strong id="journal-widget-latest">—</strong><span>Ostatni</span></div>
    </div>
    <form class="journal-widget-compose" id="journal-widget-compose">
      <input name="title" maxlength="160" placeholder="Tytuł (opcjonalnie)" aria-label="Tytuł wpisu">
      <textarea name="content" rows="3" maxlength="1000000" required placeholder="Zapisz krótką myśl…" aria-label="Treść wpisu"></textarea>
      <button class="journal-widget-save" type="submit">Zapisz</button>
    </form>
    <div class="journal-widget-status" id="journal-widget-status" aria-live="polite"></div>
    <div class="journal-widget-recent" id="journal-widget-recent"></div>
  `;
  const form = root.querySelector("#journal-widget-compose");
  const status = root.querySelector("#journal-widget-status");
  const count = root.querySelector("#journal-widget-count");
  const voice = root.querySelector("#journal-widget-voice");
  const latest = root.querySelector("#journal-widget-latest");
  const recent = root.querySelector("#journal-widget-recent");
  const submit = form.querySelector("button");
  let entries = [];

  const render = () => {
    const journalEntries = entries.filter((entry) => entry.entryKind !== "poem");
    count.textContent = String(journalEntries.length);
    voice.textContent = String(journalEntries.filter((entry) => entry.sourceType === "voice-journal").length);
    latest.textContent = latestDate(journalEntries);
    recent.replaceChildren(...journalEntries.slice(0, 2).map((entry) => {
      const item = node("a", "journal-widget-recent-item");
      item.href = "./journal.html";
      const copy = node("span");
      copy.append(
        node("strong", "", entry.title || "* * *"),
        node("small", "", journalEntryText(entry).slice(0, 110)),
      );
      item.append(
        node("time", "", journalDisplayDate(entry.entryDate)),
        copy,
      );
      return item;
    }));
    if (!journalEntries.length) recent.append(node("p", "journal-widget-empty", "Pierwsza czysta strona czeka na wpis."));
  };

  const load = async () => {
    try {
      entries = await fetchEntries();
      render();
      status.textContent = "";
    } catch (error) {
      status.textContent = error?.message || "Dziennik jest chwilowo niedostępny.";
    }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = form.elements.content.value.trim();
    if (!content) return;
    submit.disabled = true;
    status.textContent = "Zapisywanie…";
    try {
      await createEntry({
        entryKind: "journal",
        title: form.elements.title.value.trim(),
        content,
        entryDate: new Date().toISOString(),
        tags: [],
      });
      form.reset();
      await load();
      status.textContent = "Zapisano w Dzienniku.";
    } catch (error) {
      status.textContent = error?.message || "Nie udało się zapisać wpisu.";
    } finally {
      submit.disabled = false;
    }
  });

  await load();
  return { load };
}

if (typeof document !== "undefined") {
  const root = document.getElementById("journal-widget-root");
  if (root) initJournalWidget(root);
}
