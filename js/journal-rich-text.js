import { escapeHtml } from "./utils.js";

const ALLOWED_TAGS = new Set([
  "A", "B", "BLOCKQUOTE", "BR", "DIV", "EM", "H1", "H2", "H3", "I", "LI", "OL", "P",
  "PRE", "S", "STRIKE", "STRONG", "U", "UL",
]);

const DROP_WITH_CONTENT = new Set(["SCRIPT", "STYLE", "IFRAME", "OBJECT", "EMBED", "SVG", "MATH"]);
const MAX_ILLUSTRATION_BYTES = 2 * 1024 * 1024;
const MAX_ILLUSTRATION_EDGE = 1600;

function safeLink(value) {
  const link = String(value || "").trim();
  if (/^(?:https?:|mailto:)/i.test(link) || /^(?:\/|\.\/|\.\.\/|#)/.test(link)) return link;
  return "";
}

export function sanitizeJournalHtml(value, documentRef = document) {
  const template = documentRef.createElement("template");
  template.innerHTML = String(value || "");

  const clean = (parent) => {
    [...parent.childNodes].forEach((child) => {
      if (child.nodeType === 8) {
        child.remove();
        return;
      }
      if (child.nodeType === 3) {
        child.nodeValue = child.nodeValue.replace(/\u00a0/g, " ");
        return;
      }
      if (child.nodeType !== 1) return;
      if (DROP_WITH_CONTENT.has(child.tagName)) {
        child.remove();
        return;
      }
      if (!ALLOWED_TAGS.has(child.tagName)) {
        clean(child);
        child.replaceWith(...child.childNodes);
        return;
      }

      const originalHref = child.tagName === "A" ? child.getAttribute("href") : "";
      [...child.attributes].forEach((attribute) => child.removeAttribute(attribute.name));
      if (child.tagName === "A") {
        const href = safeLink(originalHref || "");
        if (href) {
          child.setAttribute("href", href);
          child.setAttribute("rel", "noopener noreferrer");
          if (/^https?:/i.test(href)) child.setAttribute("target", "_blank");
        }
      }
      clean(child);
    });
  };

  clean(template.content);
  return template.innerHTML;
}

function bbCodeToHtml(value) {
  let output = escapeHtml(value);
  output = output
    .replace(/\[b\]/gi, "<strong>").replace(/\[\/b\]/gi, "</strong>")
    .replace(/\[i\]/gi, "<em>").replace(/\[\/i\]/gi, "</em>")
    .replace(/\[u\]/gi, "<u>").replace(/\[\/u\]/gi, "</u>")
    .replace(/\[s\]/gi, "<s>").replace(/\[\/s\]/gi, "</s>")
    .replace(/\[quote\]/gi, "<blockquote>").replace(/\[\/quote\]/gi, "</blockquote>")
    .replace(/\[list(?:=1)?\]/gi, (tag) => tag.includes("=") ? "<ol>" : "<ul>")
    .replace(/\[\/list\]/gi, (tag, offset, source) => {
      const before = source.slice(0, offset);
      return before.lastIndexOf("<ol>") > before.lastIndexOf("<ul>") ? "</ol>" : "</ul>";
    })
    .replace(/\[\*\]/g, "<li>").replace(/\[\/\*\]/g, "</li>")
    .replace(/\[url=([^\]]+)\]([\s\S]*?)\[\/url\]/gi, (_match, href, label) => {
      const safeHref = safeLink(href.replaceAll("&quot;", '"').replaceAll("&amp;", "&"));
      return safeHref ? `<a href="${escapeHtml(safeHref)}">${label}</a>` : label;
    })
    .replace(/\[url\]([\s\S]*?)\[\/url\]/gi, (_match, href) => {
      const plainHref = href.replace(/<[^>]+>/g, "").replaceAll("&amp;", "&");
      const safeHref = safeLink(plainHref);
      return safeHref ? `<a href="${escapeHtml(safeHref)}">${href}</a>` : href;
    });
  return output.replace(/\r?\n/g, "<br>");
}

function plainTextToHtml(value) {
  return escapeHtml(value)
    .split(/\r?\n\s*\r?\n/)
    .map((paragraph) => `<p>${paragraph.replace(/\r?\n/g, "<br>")}</p>`)
    .join("");
}

export function journalMarkupToHtml(value, documentRef = document) {
  const source = String(value || "").trim();
  if (!source) return "";
  if (/\[(?:b|i|u|s|quote|list|url)(?:=|\])/i.test(source)) {
    return sanitizeJournalHtml(bbCodeToHtml(source), documentRef);
  }
  if (/<\/?[a-z][\s\S]*>/i.test(source)) return sanitizeJournalHtml(source, documentRef);
  return sanitizeJournalHtml(plainTextToHtml(source), documentRef);
}

export function journalHtmlToText(value, documentRef = document) {
  const container = documentRef.createElement("div");
  container.innerHTML = sanitizeJournalHtml(value, documentRef)
    .replace(/<\/(?:blockquote|div|h2|h3|li|ol|p|ul)>/gi, "$& ");
  return String(container.textContent || "").replace(/\s+/g, " ").trim();
}

export function journalEntryText(entry, documentRef = document) {
  return entry?.contentFormat === "html"
    ? journalHtmlToText(entry.content, documentRef)
    : String(entry?.content || "").replace(/\s+/g, " ").trim();
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Nie udało się odczytać ilustracji."));
    reader.readAsDataURL(file);
  });
}

function loadImage(dataUrl) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Nie udało się otworzyć ilustracji."));
    image.src = dataUrl;
  });
}

function canvasToBlob(canvas, type, quality) {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
}

export async function prepareJournalIllustration(file) {
  if (!file || !/^image\/(?:jpeg|png|webp|gif)$/i.test(file.type || "")) {
    throw new Error("Wybierz obraz JPG, PNG, WebP lub GIF.");
  }
  if (file.size <= MAX_ILLUSTRATION_BYTES && file.type === "image/gif") return readFileAsDataUrl(file);

  const original = await readFileAsDataUrl(file);
  const image = await loadImage(original);
  const scale = Math.min(1, MAX_ILLUSTRATION_EDGE / Math.max(image.naturalWidth, image.naturalHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Ta przeglądarka nie może przygotować ilustracji.");
  context.drawImage(image, 0, 0, canvas.width, canvas.height);

  let quality = 0.86;
  let blob = await canvasToBlob(canvas, "image/webp", quality);
  while (blob && blob.size > MAX_ILLUSTRATION_BYTES && quality > 0.48) {
    quality -= 0.08;
    blob = await canvasToBlob(canvas, "image/webp", quality);
  }
  if (!blob || blob.size > MAX_ILLUSTRATION_BYTES) {
    throw new Error("Ilustracja jest zbyt duża. Wybierz obraz mniejszy niż 2 MB.");
  }
  return readFileAsDataUrl(blob);
}

export const JOURNAL_ILLUSTRATION_MAX_BYTES = MAX_ILLUSTRATION_BYTES;
