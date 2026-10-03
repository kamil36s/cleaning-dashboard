const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
})[char]);

const SECTION_TITLES = new Set([
  "składniki",
  "przygotowanie",
  "wykonanie",
  "sposób przygotowania",
  "instrukcja",
  "wskazówki",
  "notatki",
]);

function renderInline(value) {
  return escapeHtml(value)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function stripBoldWrapper(value) {
  const text = String(value || "").trim();
  const match = text.match(/^(?:\*\*|__)(.+)(?:\*\*|__)$/);
  return match ? match[1].trim() : text;
}

function isSectionTitle(value) {
  return SECTION_TITLES.has(stripBoldWrapper(value).toLocaleLowerCase("pl-PL").replace(/:$/, ""));
}

function splitTableRow(value) {
  return String(value || "")
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isTableSeparator(value) {
  const cells = splitTableRow(value);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function renderTable(lines, startIndex) {
  const header = splitTableRow(lines[startIndex]);
  const rows = [];
  let index = startIndex + 2;
  while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
    rows.push(splitTableRow(lines[index]));
    index += 1;
  }

  const width = Math.max(header.length, ...rows.map((row) => row.length));
  const normalizedHeader = Array.from({ length: width }, (_, cellIndex) => header[cellIndex] || "");
  const normalizedRows = rows.map((row) => Array.from({ length: width }, (_, cellIndex) => row[cellIndex] || ""));
  return {
    html: `<div class="recipe-table-wrap"><table><thead><tr>${normalizedHeader.map((cell) => `<th>${renderInline(cell)}</th>`).join("")}</tr></thead><tbody>${normalizedRows.map((row) => `<tr>${row.map((cell) => `<td>${renderInline(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`,
    nextIndex: index,
  };
}

export function renderRecipeText(value) {
  const lines = String(value || "").replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      index += 1;
      continue;
    }

    if (index + 1 < lines.length && line.includes("|") && isTableSeparator(lines[index + 1])) {
      const table = renderTable(lines, index);
      blocks.push(table.html);
      index = table.nextIndex;
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      const level = Math.min(3, heading[1].length + 1);
      blocks.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
      index += 1;
      continue;
    }

    if (isSectionTitle(line)) {
      blocks.push(`<h2>${renderInline(stripBoldWrapper(line).replace(/:$/, ""))}</h2>`);
      index += 1;
      continue;
    }

    const ordered = line.match(/^(\d+)[.)]\s+(.+)$/);
    if (ordered) {
      const items = [];
      const start = Number(ordered[1]);
      while (index < lines.length) {
        const item = lines[index].trim().match(/^(\d+)[.)]\s+(.+)$/);
        if (!item) break;
        items.push(`<li>${renderInline(item[2])}</li>`);
        index += 1;
      }
      blocks.push(`<ol${start !== 1 ? ` start="${start}"` : ""}>${items.join("")}</ol>`);
      continue;
    }

    const unordered = line.match(/^[-*]\s+(.+)$/);
    if (unordered) {
      const items = [];
      while (index < lines.length) {
        const item = lines[index].trim().match(/^[-*]\s+(.+)$/);
        if (!item) break;
        items.push(`<li>${renderInline(item[1])}</li>`);
        index += 1;
      }
      blocks.push(`<ul>${items.join("")}</ul>`);
      continue;
    }

    if (/^_{3,}$|^-{3,}$|^\*{3,}$/.test(line)) {
      blocks.push("<hr>");
      index += 1;
      continue;
    }

    const paragraph = [line];
    index += 1;
    while (index < lines.length && lines[index].trim()) {
      const next = lines[index].trim();
      if (
        /^(?:#{1,3}\s+|\d+[.)]\s+|[-*]\s+)/.test(next)
        || isSectionTitle(next)
        || (index + 1 < lines.length && next.includes("|") && isTableSeparator(lines[index + 1]))
      ) break;
      paragraph.push(next);
      index += 1;
    }
    blocks.push(`<p>${renderInline(paragraph.join(" "))}</p>`);
  }

  return blocks.join("");
}
