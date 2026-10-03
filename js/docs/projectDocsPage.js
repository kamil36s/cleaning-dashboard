import { DOC_SECTION_HEADINGS, PROJECT_DOCS } from "./projectDocsData.js";
import { escapeHtml } from "../utils.js";

const $ = (id) => document.getElementById(id);

function normalizeId(value) {
  const raw = String(value || "").replace(/^#/, "").trim();
  return PROJECT_DOCS.some((doc) => doc.id === raw) ? raw : PROJECT_DOCS[0]?.id;
}

function getSelectedDoc() {
  const id = normalizeId(window.location.hash);
  return PROJECT_DOCS.find((doc) => doc.id === id) || PROJECT_DOCS[0];
}

function renderNav(selectedId) {
  const nav = $("developer-docs-nav");
  if (!nav) return;

  nav.innerHTML = PROJECT_DOCS.map((doc) => {
    const isActive = doc.id === selectedId;
    return `
      <a
        class="settings-section-link developer-docs-link${isActive ? " is-active" : ""}"
        href="#${escapeHtml(doc.id)}"
        ${isActive ? 'aria-current="page"' : ""}
      >
        <span class="settings-section-link-title">${escapeHtml(doc.title)}</span>
        <span class="settings-section-link-copy">${escapeHtml(doc.category)}</span>
      </a>
    `;
  }).join("");
}

function renderSection(heading, body) {
  const text = String(body || "To be documented later.");
  const isRelatedFiles = heading === "Related files" && text !== "To be documented later.";
  const content = isRelatedFiles
    ? `<ul class="developer-docs-file-list">${
        text.split("\n")
          .filter(Boolean)
          .map((file) => `<li><code>${escapeHtml(file)}</code></li>`)
          .join("")
      }</ul>`
    : `<p>${escapeHtml(text)}</p>`;

  return `
    <section class="developer-docs-section">
      <h3>${escapeHtml(heading)}</h3>
      ${content}
    </section>
  `;
}

function renderDoc(doc) {
  const main = $("developer-docs-content");
  if (!main || !doc) return;

  main.innerHTML = `
    <section class="settings-section settings-section-panel developer-docs-article">
      <div class="settings-section-head">
        <div>
          <div class="settings-kicker">${escapeHtml(doc.category)}</div>
          <h2>${escapeHtml(doc.title)}</h2>
          <p class="meta settings-copy">Placeholder documentation entry for <code>${escapeHtml(doc.id)}</code>.</p>
        </div>
      </div>
      <div class="developer-docs-section-grid">
        ${DOC_SECTION_HEADINGS.map((heading) => renderSection(heading, doc.sections?.[heading])).join("")}
      </div>
    </section>
  `;
}

function renderPage() {
  const doc = getSelectedDoc();
  renderNav(doc?.id);
  renderDoc(doc);
}

document.addEventListener("DOMContentLoaded", () => {
  renderPage();
  window.addEventListener("hashchange", renderPage);
});
