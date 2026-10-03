(() => {
  "use strict";

  const archive = window.HISTORY_WIKI_DATA;
  const content = document.querySelector("#wiki-content");
  const navigation = document.querySelector("#wiki-navigation");
  const searchInput = document.querySelector("#global-search");
  const privacySelect = document.querySelector("#privacy-mode");
  const privacyKey = "historyWiki.privacyMode.v1";
  const privacyModes = {
    normal: new Set(["normal"]),
    private: new Set(["normal", "private"]),
    sensitive: new Set(["normal", "private", "sensitive", "third_party_sensitive"]),
  };
  if (!archive) {
    content.innerHTML = '<div class="empty-state">Brak lokalnego pliku danych History Wiki.</div>';
    return;
  }

  let privacyMode = localStorage.getItem(privacyKey) || "normal";
  if (!privacyModes[privacyMode]) privacyMode = "normal";
  privacySelect.value = privacyMode;

  const esc = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  const safe = (value, fallback = "—") => esc(value || fallback);
  const num = (value) => new Intl.NumberFormat("pl-PL").format(Number(value || 0));
  const truncate = (value, length = 220) => {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    return text.length > length ? `${text.slice(0, length - 1)}…` : text;
  };
  const visibleLevel = (level) => privacyModes[privacyMode].has(level || "private");
  const visible = (record) => visibleLevel(record?.privacy_level);
  const badge = (level) => `<span class="privacy-badge privacy-${esc(level || "private")}">${esc((level || "private").replaceAll("_", " "))}</span>`;
  const statusBadge = (status) => `<span class="status-badge">${safe(status)}</span>`;
  const pageHeader = (kicker, title, lead, meta = "") => `<div class="page-kicker">${esc(kicker)}</div><h1 class="page-title">${esc(title)}</h1>${lead ? `<p class="page-lead">${esc(lead)}</p>` : ""}${meta ? `<div class="page-meta">${meta}</div>` : ""}`;
  const section = (title, body, intro = "") => `<section class="page-section"><h2 class="section-title">${esc(title)}</h2>${intro ? `<p class="section-intro">${esc(intro)}</p>` : ""}${body}</section>`;
  const empty = (message) => `<div class="empty-state">${esc(message)}</div>`;
  const idLink = (id) => /^P\d+/.test(id) ? `<a class="mono" href="#project/${encodeURIComponent(id)}">${esc(id)}</a>` : `<span class="mono">${esc(id)}</span>`;
  const byId = {
    projects: new Map(archive.projects.map((item) => [item.project_id, item])),
    topics: new Map(archive.topics.map((item) => [item.topic_id, item])),
    conversations: new Map(archive.conversations.map((item) => [item.conversation_id, item])),
    ideas: new Map(archive.ideas.map((item) => [item.idea_id, item])),
    journal: new Map(archive.journal_pilot.map((item) => [item.local_date, item])),
  };

  const getRoute = () => {
    const [route, ...rest] = (location.hash.replace(/^#/, "") || "overview").split("/");
    return { route, id: decodeURIComponent(rest.join("/")) };
  };
  const setActiveNavigation = (route) => navigation.querySelectorAll("[data-route]").forEach((link) => link.classList.toggle("is-active", link.dataset.route === route || (route === "project" && link.dataset.route === "projects") || (route === "conversation" && link.dataset.route === "conversations")));

  function eventRow(event) {
    return `<div class="compact-row"><div class="compact-date">${safe(event.date)}</div><div class="compact-body"><strong>${safe(event.title)}</strong><span>${safe(truncate(event.description, 190))}</span></div><div>${badge(event.privacy_level)}</div></div>`;
  }

  function eraCard(era) {
    const projectLinks = era.project_ids.filter((id) => visible(byId.projects.get(id))).map((id) => `<a href="#project/${encodeURIComponent(id)}">${safe(byId.projects.get(id)?.name || id)}</a>`).join(" · ");
    return `<article class="era-card"><div class="era-dates">${safe(era.start_date)} — ${safe(era.end_date, "open")}</div><h3>${safe(era.working_title)}</h3><p>${safe(era.summary)}</p><div class="era-meta">${badge(era.privacy_level)} ${statusBadge(`${era.confidence} confidence`)}</div>${projectLinks ? `<div class="era-projects">${projectLinks}</div>` : ""}</article>`;
  }

  function genealogyRow(edge) {
    const from = byId.projects.get(edge.from_project_id);
    const to = byId.projects.get(edge.to_project_id);
    if (!visible(from) || !visible(to)) return "";
    return `<div class="genealogy-row"><a href="#project/${encodeURIComponent(edge.from_project_id)}">${safe(from.name)}</a><span class="genealogy-arrow">${safe(edge.relation_type.replaceAll("_", " "))} →</span><a href="#project/${encodeURIComponent(edge.to_project_id)}">${safe(to.name)}</a><p>${safe(edge.rationale)}</p></div>`;
  }

  function renderOverview() {
    const recentEvents = archive.events.filter(visible).sort((a, b) => b.date.localeCompare(a.date)).slice(0, 7);
    const genealogy = archive.project_genealogies.map(genealogyRow).filter(Boolean).slice(0, 5);
    return `${pageHeader("Normalized personal archive", "Historia, która zachowuje bałagan", "Rozmowy są teraz czytane przez role tematów, genealogie projektów, archeologię idei, draft er i kontrolowany pilot Journalu.", `V2 · ${safe(archive.archive_revision)} · ${num(archive.counts.journal_candidate_days)} dni z timestampów wiadomości`)}
      <div class="notice"><strong>Phase 2, nadal przed pełnym Journalem.</strong> Pilot obejmuje ${num(archive.counts.journal_pilot_days)} dni. Pełne 767 dni, final synthesis i final release nie zostały wygenerowane.</div>
      <div class="stat-strip"><div class="stat-item"><strong>${num(archive.counts.conversations)}</strong><span>normalized conversations</span></div><div class="stat-item"><strong>${num(archive.counts.projects)}</strong><span>project dossiers</span></div><div class="stat-item"><strong>${num(archive.counts.genealogy_edges)}</strong><span>reviewed genealogy edges</span></div><div class="stat-item"><strong>${num(archive.counts.journal_pilot_days)}</strong><span>pilot Journal days</span></div></div>
      ${section("Ścieżki czytania", `<div class="reading-paths"><a href="#history"><strong>Ery i historia</strong><span>6 roboczych er oraz punkty zwrotne.</span></a><a href="#projects"><strong>Genealogie projektów</strong><span>Od systemu osobistego do konkretnych aplikacji.</span></a><a href="#ideas"><strong>Archeologia idei</strong><span>Pierwsze pojawienie, późniejszy kontekst i status.</span></a><a href="#journal"><strong>Pilot Journalu</strong><span>14 rekonstruowanych dni z lekką, czytelną proweniencją.</span></a></div>`)}
      ${section("Draft er", `<div class="era-grid">${archive.eras.filter(visible).slice(-3).map(eraCard).join("")}</div>`)}
      ${section("Genealogie — skrót", genealogy.length ? `<div class="genealogy-list">${genealogy.join("")}</div>` : empty("Brak genealogii w tej warstwie prywatności."))}
      ${section("Ostatnie zdarzenia", recentEvents.length ? `<div class="compact-list">${recentEvents.map(eventRow).join("")}</div>` : empty("Brak widocznych zdarzeń."))}
      <p class="footer-note">Filtr prywatności zmienia renderowanie i korpus wyszukiwania. Ukryte sekcje Journalu nie są wstawiane do DOM, ale wygenerowany plik danych nadal jest prywatnym artefaktem lokalnym.</p>`;
  }

  function renderHistory() {
    const eras = archive.eras.filter(visible);
    const years = new Map();
    archive.conversations.filter(visible).forEach((conversation) => years.set(conversation.date.slice(0, 4), (years.get(conversation.date.slice(0, 4)) || 0) + 1));
    return `${pageHeader("My History", "Ery, lata i punkty zwrotne", "Ery są roboczą warstwą interpretacyjną: każda ma zakres dat, confidence, prywatność i jawne event IDs.")}
      <div class="notice"><strong>Draft, nie final synthesis.</strong> Granice er są przeznaczone do przeglądu przed Phase 3.</div>
      ${section("Robocze ery", `<div class="era-grid">${eras.map(eraCard).join("")}</div>`)}
      ${section("Gęstość lat", `<div class="data-table-wrap"><table class="data-table"><thead><tr><th>Rok</th><th>Widoczne rozmowy</th></tr></thead><tbody>${[...years].sort((a, b) => b[0].localeCompare(a[0])).map(([year, count]) => `<tr><td class="table-title">${year}</td><td>${num(count)}</td></tr>`).join("")}</tbody></table></div>`)}
      ${section("Dalej", '<ul class="article-list"><li><a href="#timeline">Oś zdarzeń</a></li><li><a href="#journal">Pilot Journalu</a></li><li><a href="../../timeline.html">Great Timeline</a></li></ul>')}`;
  }

  function renderTimeline() {
    const events = archive.events.filter(visible).sort((a, b) => b.date.localeCompare(a.date));
    return `${pageHeader("My History", "Timeline", "Zdarzenia zachowują swoje źródłowe ID i poziomy prywatności.", `${num(events.length)} visible of ${num(archive.events.length)}`)}${events.length ? `<div class="compact-list page-section">${events.map(eventRow).join("")}</div>` : empty("Brak widocznych zdarzeń.")}`;
  }

  function renderProjects() {
    const projects = archive.projects.filter(visible).sort((a, b) => a.first_seen.localeCompare(b.first_seen));
    const genealogy = archive.project_genealogies.map(genealogyRow).filter(Boolean);
    return `${pageHeader("Knowledge", "Projects i genealogie", "Projekt nie jest scalany tylko dlatego, że wyrósł z wcześniejszego pomysłu. V2 pokazuje pochodzenie, branch i implementację.", `${num(projects.length)} visible of ${num(archive.projects.length)}`)}
      ${section("Reviewed genealogy", genealogy.length ? `<div class="genealogy-list">${genealogy.join("")}</div>` : empty("Brak widocznych krawędzi."))}
      ${section("Project index", `<div class="data-table-wrap"><table class="data-table"><thead><tr><th>Projekt</th><th>Zakres</th><th>Genealogia</th><th>Privacy</th></tr></thead><tbody>${projects.map((project) => `<tr><td><a class="table-title" href="#project/${encodeURIComponent(project.project_id)}">${safe(project.name)}</a><div class="mono">${safe(project.project_id)}</div></td><td>${safe(project.first_seen)} — ${safe(project.last_seen)}</td><td>${num(project.genealogy_edge_ids.length)} edges</td><td>${badge(project.privacy_level)}</td></tr>`).join("")}</tbody></table></div>`)}`;
  }

  function renderProject(projectId) {
    const project = byId.projects.get(projectId);
    if (!project || !visible(project)) return pageHeader("Project", "Niedostępny", "Projekt nie istnieje albo jest ukryty w bieżącej warstwie prywatności.");
    const events = archive.events.filter((item) => visible(item) && item.project_ids?.includes(projectId)).sort((a, b) => a.date.localeCompare(b.date));
    const ideas = archive.ideas.filter((item) => visible(item) && item.project_ids?.includes(projectId));
    const edges = archive.project_genealogies.filter((edge) => edge.from_project_id === projectId || edge.to_project_id === projectId).map(genealogyRow).filter(Boolean);
    const threads = archive.unfinished_threads.filter((thread) => thread.project_ids.includes(projectId));
    const sources = (project.conversations || []).map((item) => byId.conversations.get(typeof item === "string" ? item : item.conversation_id)).filter((item) => item && visible(item)).sort((a, b) => b.date.localeCompare(a.date));
    return `<div class="project-grid"><article class="wiki-article">${pageHeader(`Project dossier · ${project.project_id}`, project.name, project.summary, `${safe(project.first_seen)} — ${safe(project.last_seen)}`)}
      <h2>Origin and provenance</h2><p>Pierwsze pojawienie: <strong>${safe(project.first_seen)}</strong>. Normalized source ID: <span class="mono">${safe(project.source_project_ids.join(", "))}</span>.</p>
      <h2>Genealogy</h2>${edges.length ? `<div class="genealogy-list">${edges.join("")}</div>` : "<p>Brak zatwierdzonej krawędzi genealogii.</p>"}
      <h2>Events</h2>${events.length ? `<div class="compact-list">${events.map(eventRow).join("")}</div>` : "<p>Brak widocznych eventów.</p>"}
      <h2>Subprojects and descendants</h2>${(project.subprojects || []).length ? `<ul class="article-list">${project.subprojects.map((item) => `<li>${safe(typeof item === "string" ? item : item.name || item.title || JSON.stringify(item))}</li>`).join("")}</ul>` : edges.length ? `<p>Jawne potomne i powiązane implementacje są pokazane w genealogii powyżej.</p>` : "<p>Brak jawnych subprojects albo descendants.</p>"}
      <h2>Ideas</h2>${ideas.length ? `<ul class="article-list">${ideas.slice(0, 60).map((idea) => `<li><span class="mono">${safe(idea.idea_id)}</span> ${safe(idea.text)} ${statusBadge(idea.status)} ${badge(idea.privacy_level)}</li>`).join("")}</ul>` : "<p>Brak widocznych idei.</p>"}
      <h2>Unfinished branches</h2>${threads.length ? `<ul class="article-list">${threads.map((thread) => `<li><strong>${safe(thread.title)}</strong> ${statusBadge(thread.status)}<br><span class="table-summary">${safe(thread.next_question)}</span></li>`).join("")}</ul>` : "<p>Brak jawnie zidentyfikowanej otwartej gałęzi.</p>"}
      <h2>Source conversations</h2>${sources.length ? `<div class="data-table-wrap"><table class="data-table"><tbody>${sources.slice(0, 100).map((source) => `<tr><td>${safe(source.date)}</td><td><a class="table-title" href="#conversation/${encodeURIComponent(source.conversation_id)}">${safe(source.title)}</a><div class="table-summary">${safe(truncate(source.summary, 180))}</div></td><td class="mono">${safe(source.conversation_id)}</td></tr>`).join("")}</tbody></table></div>` : "<p>Brak widocznych rozmów.</p>"}
      </article><aside class="infobox"><div class="infobox-title">Metadata</div><dl><div class="infobox-row"><dt>ID</dt><dd>${safe(project.project_id)}</dd></div><div class="infobox-row"><dt>Privacy</dt><dd>${safe(project.privacy_level)}</dd></div><div class="infobox-row"><dt>Review</dt><dd>${safe(project.privacy_review?.rationale)}</dd></div><div class="infobox-row"><dt>Aliases</dt><dd>${safe(project.aliases.join(", "), "none")}</dd></div><div class="infobox-row"><dt>Sources</dt><dd>${num(sources.length)}</dd></div></dl></aside></div>`;
  }

  function renderIdeas() {
    const visibleIdeas = archive.ideas.filter(visible);
    const groups = ["active", "revisited", "completed", "abandoned", "unclear"];
    const archaeology = archive.idea_archaeology.filter((item) => visibleLevel(item.privacy_level));
    const orphanEmerging = visibleIdeas.filter((idea) => !(idea.project_ids || []).length && ["active", "unclear"].includes(idea.status));
    return `${pageHeader("Knowledge", "Ideas i archeologia", "Statusy są zachowane w ścisłym słowniku; wiek idei nie jest dowodem porzucenia.", `${num(archaeology.length)} reviewed archaeology records`)}
      ${section("Idea archaeology", `<div class="archaeology-grid">${archaeology.map((item) => `<article><div class="mono">${safe(item.idea_id)} · ${safe(item.first_appearance.date)}</div><h3>${safe(byId.ideas.get(item.idea_id)?.text)}</h3><p>${safe(item.transformation_note)}</p><div>${statusBadge(item.current_status)} ${badge(item.privacy_level)}</div></article>`).join("")}</div>`)}
      ${section(`Orphan / emerging · ${orphanEmerging.length}`, `<ul class="article-list">${orphanEmerging.slice(0, 100).map((idea) => `<li><span class="mono">${safe(idea.idea_id)}</span> ${safe(idea.text)} ${statusBadge(idea.status)}</li>`).join("") || "<li>None</li>"}</ul>`)}
      ${groups.map((status) => section(`${status} · ${visibleIdeas.filter((idea) => idea.status === status).length}`, `<ul class="article-list">${visibleIdeas.filter((idea) => idea.status === status).slice(0, 100).map((idea) => `<li><span class="mono">${safe(idea.idea_id)}</span> ${safe(idea.text)} ${badge(idea.privacy_level)}</li>`).join("") || "<li>None</li>"}</ul>`)).join("")}`;
  }

  function renderTopics() {
    const roles = ["section", "topic", "tag"];
    return `${pageHeader("Knowledge", "Topics jako nawigacja", "177 topic IDs zostaje bez zmian; V2 nadaje im role prezentacyjne section, topic albo tag.")}${roles.map((role) => section(`${role} · ${archive.topic_navigation.counts[role]}`, `<div class="topic-cloud">${archive.topics.filter((topic) => topic.navigation_role === role).map((topic) => `<span><strong>${safe(topic.name)}</strong><small>${safe(topic.topic_id)} · ${num(topic.usage.total)} uses</small></span>`).join("")}</div>`)).join("")}`;
  }

  function renderConversations() {
    const conversations = archive.conversations.filter(visible).sort((a, b) => b.date.localeCompare(a.date));
    return `${pageHeader("Archive", "Conversations", "Normalized catalog: poprawione podsumowania i klasyfikacje mają jawne review decisions i provenance.", `${num(conversations.length)} visible`)}${section("Catalog", `<div class="data-table-wrap"><table class="data-table"><thead><tr><th>Date</th><th>Conversation</th><th>Classification</th><th>Review</th></tr></thead><tbody>${conversations.slice(0, 500).map((item) => `<tr><td>${safe(item.date)}</td><td><a class="table-title" href="#conversation/${encodeURIComponent(item.conversation_id)}">${safe(item.title)}</a><div class="table-summary">${safe(truncate(item.summary, 190))}</div><div class="mono">${safe(item.conversation_id)}</div></td><td>${safe([...(item.project_ids || []), ...(item.topic_ids || [])].join(", "), "unclassified")}</td><td>${safe(item.review_decision)}</td></tr>`).join("")}</tbody></table></div>`, "Widok ogranicza tabelę do 500 najnowszych rekordów; wyszukiwanie obejmuje cały widoczny katalog.")}`;
  }

  function renderConversation(conversationId) {
    const conversation = byId.conversations.get(conversationId);
    if (!conversation || !visible(conversation)) return pageHeader("Conversation", "Niedostępna", "Rozmowa nie istnieje albo jest ukryta w bieżącej warstwie prywatności.");
    const projectLinks = (conversation.project_ids || []).map((id) => byId.projects.get(id)).filter((item) => item && visible(item)).map((item) => `<a href="#project/${encodeURIComponent(item.project_id)}">${safe(item.name)}</a>`).join(" · ");
    const topicLabels = (conversation.topic_ids || []).map((id) => byId.topics.get(id)?.name || id);
    const journalDates = archive.journal_pilot.filter((entry) => entry.source_conversation_ids.includes(conversationId)).map((entry) => `<a href="#journal/${entry.local_date}">${safe(entry.local_date)} · ${safe(entry.title)}</a>`);
    return `${pageHeader(`Conversation · ${conversation.date}`, conversation.title, conversation.summary, `<a href="#conversations">← katalog</a> · ${badge(conversation.privacy_level)}`)}
      <article class="wiki-article conversation-detail">
        <h2>Powiązania</h2>
        <dl class="conversation-links"><div><dt>Projects</dt><dd>${projectLinks || "—"}</dd></div><div><dt>Topics</dt><dd>${topicLabels.length ? safe(topicLabels.join(" · ")) : "—"}</dd></div><div><dt>Journal</dt><dd>${journalDates.length ? journalDates.join(" · ") : "—"}</dd></div></dl>
        <h2>Provenance</h2><p class="mono">${safe(conversation.conversation_id)}<br>${safe(conversation.provenance?.source_path)}</p>
        <p class="footer-note">To jest znormalizowana karta rozmowy. Widok surowych wiadomości nie jest jeszcze częścią statycznego snapshotu.</p>
      </article>`;
  }

  const prose = (text) => String(text || "").split(/\n\s*\n/).filter(Boolean).map((paragraph) => `<p>${safe(paragraph)}</p>`).join("");

  function renderJournal(dateId = "") {
    if (dateId) {
      const entry = byId.journal.get(dateId);
      if (!entry) return pageHeader("Journal", "Nie znaleziono dnia", "Pilot zawiera tylko wybrane dni.");
      const visibleBlocks = [];
      let hiddenBlocks = 0;
      if (visibleLevel(entry.base_privacy_level)) visibleBlocks.push(`<div class="journal-prose">${prose(entry.reconstructed_text)}</div>`);
      else hiddenBlocks += 1;
      for (const part of entry.gated_sections || []) {
        if (!visibleLevel(part.privacy_level)) { hiddenBlocks += 1; continue; }
        visibleBlocks.push(`<section class="journal-prose journal-prose-continuation">${part.heading ? `<h2>${safe(part.heading)}</h2>` : ""}${prose(part.text)}</section>`);
      }
      const visibleSources = entry.source_conversations.filter((source) => visibleLevel(source.privacy_level));
      const hiddenSources = entry.source_conversations.length - visibleSources.length;
      const sourceLinks = visibleSources.map((source) => `<li><a href="#conversation/${encodeURIComponent(source.conversation_id)}">${safe(source.title)}</a></li>`).join("");
      const gate = hiddenBlocks ? `<div class="privacy-gate journal-gate"><strong>${num(hiddenBlocks)} ${hiddenBlocks === 1 ? "fragment ukryty" : "fragmenty ukryte"}</strong><p>Zmień warstwę prywatności w górnym pasku, aby odsłonić pozostałą część wpisu.</p></div>` : "";
      return `${pageHeader(entry.label, entry.title, `${entry.local_date} · ${entry.timezone}`, `<a href="#journal">← indeks pilota</a> · ${num(entry.word_count)} słów · ${badge(entry.privacy_level)}`)}
        <article class="journal-entry">${visibleBlocks.join("")}${gate}</article>
        <footer class="journal-sources"><strong>Sources: ${num(entry.source_conversation_count)} conversations · ${num(entry.source_user_message_count)} user messages</strong><ul>${sourceLinks}${hiddenSources ? `<li>${num(hiddenSources)} źródeł ukrytych przez filtr prywatności</li>` : ""}</ul></footer>`;
    }
    return `${pageHeader("AI-reconstructed diary entry", "Journal — kontrolowany pilot", "14 celowo zróżnicowanych dni z lat 2023–2026. Każdy wpis powstał z pełnego zestawu wiadomości użytkownika przypisanych do dnia w Europe/Warsaw.", `${num(archive.journal_validation.pilot_days)} dni · validation ${safe(archive.journal_validation.status)}`)}
      <div class="notice"><strong>Stop po pilocie.</strong> Phase 2 nie generuje pozostałych ${num(archive.counts.journal_candidate_days - archive.counts.journal_pilot_days)} candidate days.</div>
      ${section("Pilot days", `<div class="journal-index">${archive.journal_pilot.map((entry) => `<a href="#journal/${entry.local_date}"><time>${safe(entry.local_date)}</time><strong>${safe(entry.title)}</strong><span>${num(entry.word_count)} słów · ${num(entry.source_conversation_count)} rozmów · ${badge(entry.privacy_level)}</span></a>`).join("")}</div>`)}
      ${section("Validation", `<div class="data-table-wrap"><table class="data-table"><tbody><tr><td>Assistant content included</td><td>${archive.journal_validation.assistant_content_excluded ? "no" : "yes"}</td></tr><tr><td>Legacy sentence annotations shipped</td><td>${archive.journal_validation.checks.legacy_sentence_annotations_shipped}</td></tr><tr><td>Pilot days</td><td>${archive.journal_validation.pilot_days}</td></tr><tr><td>Message-level candidate days</td><td>${archive.journal_validation.candidate_days}</td></tr></tbody></table></div>`)}`;
  }

  function renderStatistics() {
    return `${pageHeader("Archive", "Statistics", "Najważniejsza zmiana metodyczna: daty Journalu pochodzą z timestampów wiadomości.")}
      <div class="stat-strip"><div class="stat-item"><strong>2,875</strong><span>canonical conversations</span></div><div class="stat-item"><strong>767</strong><span>message-level candidate days</span></div><div class="stat-item"><strong>108</strong><span>legacy rows reviewed</span></div><div class="stat-item"><strong>0</strong><span>missing normalized summaries</span></div></div>
      ${section("Entity counts", `<div class="data-table-wrap"><table class="data-table"><tbody>${Object.entries(archive.counts).map(([key, value]) => `<tr><td>${safe(key.replaceAll("_", " "))}</td><td>${num(value)}</td></tr>`).join("")}</tbody></table></div>`)}`;
  }

  function renderQuality() {
    return `${pageHeader("Archive", "Data Quality", "Reversible ledgers make semantic decisions reviewable instead of silently rewriting canonical history.")}
      <div class="notice"><strong>Canonical source only.</strong> ${safe(archive.source_path)}. Excluded: ${safe(archive.excluded_source)}.</div>
      ${section("Human-confirmed merge ledger", `<div class="data-table-wrap"><table class="data-table"><thead><tr><th>Candidates</th><th>Decision</th><th>Relation</th><th>Rationale</th></tr></thead><tbody>${archive.merge_ledger.map((item) => `<tr><td>${item.candidate_ids.map(idLink).join(" / ")}</td><td>${statusBadge(item.status)}</td><td>${safe(item.relation_type)}</td><td>${safe(item.rationale)}</td></tr>`).join("")}</tbody></table></div>`)}
      ${section("Normalized audit", `<ul class="article-list"><li>3 missing summaries resolved conservatively.</li><li>4 fully unclassified conversations reviewed.</li><li>11 high-value underclassified conversations reviewed.</li><li>108 legacy classifications passed through the bounded migration review ledger.</li><li>12 legacy project privacy gaps received human-reviewed values.</li><li>${num(archive.topic_navigation.counts.section)} sections, ${num(archive.topic_navigation.counts.topic)} topics, ${num(archive.topic_navigation.counts.tag)} tags.</li></ul>`)}
      ${section("Known uncertainties", `<ul class="article-list"><li>Draft era boundaries remain interpretive and require human review.</li><li>Idea archaeology links later same-project events as context, not automatic proof of completion.</li><li>Assistant-only World Cup briefing has no user-authored source message and is explicitly marked as an exception.</li><li>Journal V2 is editorial reconstruction from complete same-day user-message bundles; the earlier sentence-annotation model is retained only as an archived experiment.</li></ul>`)}`;
  }

  function searchableRecords() {
    const rows = [];
    archive.projects.filter(visible).forEach((item) => rows.push({ type: "Project", title: item.name, text: item.summary, id: item.project_id, href: `#project/${item.project_id}` }));
    archive.ideas.filter(visible).forEach((item) => rows.push({ type: "Idea", title: item.text, text: item.status, id: item.idea_id, href: "#ideas" }));
    archive.conversations.filter(visible).forEach((item) => rows.push({ type: "Conversation", title: item.title, text: item.summary, id: item.conversation_id, href: `#conversation/${item.conversation_id}` }));
    archive.events.filter(visible).forEach((item) => rows.push({ type: "Event", title: item.title, text: item.description, id: item.event_id, href: "#timeline" }));
    archive.eras.filter(visible).forEach((item) => rows.push({ type: "Era", title: item.working_title, text: item.summary, id: item.era_id, href: "#history" }));
    archive.topics.forEach((item) => rows.push({ type: "Topic", title: item.name, text: item.navigation_role, id: item.topic_id, href: "#topics" }));
    archive.journal_pilot.forEach((entry) => {
      const visibleText = [visibleLevel(entry.base_privacy_level) ? entry.reconstructed_text : "", ...(entry.gated_sections || []).filter((part) => visibleLevel(part.privacy_level)).map((part) => part.text)].join(" ");
      if (visibleText.trim()) rows.push({ type: "Journal", title: `${entry.local_date} · ${entry.title}`, text: visibleText, id: entry.journal_entry_id, href: `#journal/${entry.local_date}` });
    });
    return rows;
  }

  function renderSearch(query) {
    const terms = query.toLocaleLowerCase("pl").split(/\s+/).filter(Boolean);
    const results = searchableRecords().filter((item) => terms.every((term) => `${item.title} ${item.text} ${item.id}`.toLocaleLowerCase("pl").includes(term))).slice(0, 100);
    return `${pageHeader("Global search", `Wyniki: “${query}”`, "Przeszukiwane są wyłącznie aktualnie odsłonięte warstwy prywatności.", `${num(results.length)} results`)}<section class="page-section">${results.length ? results.map((item) => `<article class="search-result"><div class="search-result-head"><span class="type-badge">${safe(item.type)}</span><h3><a href="${esc(item.href)}">${safe(item.title)}</a></h3><span class="mono">${safe(item.id)}</span></div><p>${safe(truncate(item.text, 280))}</p></article>`).join("") : empty("Brak widocznych wyników.")}</section>`;
  }

  const renderers = { overview: renderOverview, history: renderHistory, timeline: renderTimeline, projects: renderProjects, ideas: renderIdeas, topics: renderTopics, conversations: renderConversations, statistics: renderStatistics, quality: renderQuality };
  function render() {
    const query = searchInput.value.trim();
    const { route, id } = getRoute();
    setActiveNavigation(query ? "" : route);
    if (query) content.innerHTML = renderSearch(query);
    else if (route === "project") content.innerHTML = renderProject(id);
    else if (route === "conversation") content.innerHTML = renderConversation(id);
    else if (route === "journal") content.innerHTML = renderJournal(id);
    else content.innerHTML = (renderers[route] || renderOverview)();
    content.focus({ preventScroll: true });
    document.title = `${query ? "Search" : route} · History Wiki`;
  }

  privacySelect.addEventListener("change", () => { privacyMode = privacySelect.value; localStorage.setItem(privacyKey, privacyMode); render(); });
  searchInput.addEventListener("input", render);
  window.addEventListener("hashchange", () => { searchInput.value = ""; render(); window.scrollTo({ top: 0, behavior: "instant" }); });
  window.addEventListener("keydown", (event) => {
    if (event.key === "/" && !/input|select|textarea/i.test(document.activeElement?.tagName || "")) { event.preventDefault(); searchInput.focus(); }
    if (event.key === "Escape" && document.activeElement === searchInput) { searchInput.value = ""; searchInput.blur(); render(); }
  });
  render();
})();
