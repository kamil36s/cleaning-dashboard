import { describe, expect, it } from "vitest";

import {
  journalEntryText,
  journalMarkupToHtml,
  sanitizeJournalHtml,
} from "../js/journal-rich-text.js";

describe("journal rich text", () => {
  it("converts basic BBCode to safe HTML", () => {
    const html = journalMarkupToHtml("[b]Ważne[/b] i [i]spokojne[/i]\n[quote]Myśl[/quote]");

    expect(html).toContain("<strong>Ważne</strong>");
    expect(html).toContain("<em>spokojne</em>");
    expect(html).toContain("<blockquote>Myśl</blockquote>");
  });

  it("removes executable HTML while keeping basic formatting and safe links", () => {
    const html = sanitizeJournalHtml(`
      <p onclick="alert(1)"><strong>Tekst</strong><script>alert(1)</script></p>
      <a href="javascript:alert(1)">zły</a><a href="https://example.com">dobry</a>
    `);

    expect(html).toContain("<strong>Tekst</strong>");
    expect(html).not.toContain("script");
    expect(html).not.toContain("onclick");
    expect(html).not.toContain("javascript:");
    expect(html).toContain('href="https://example.com"');
  });

  it("keeps line blocks created by Enter in the visual editor", () => {
    const html = sanitizeJournalHtml("<div>Pierwsza linia</div><div>Druga linia</div><div><br></div><div>Czwarta linia</div>");

    expect(html).toBe("<div>Pierwsza linia</div><div>Druga linia</div><div><br></div><div>Czwarta linia</div>");
    expect(journalEntryText({ contentFormat: "html", content: html }))
      .toBe("Pierwsza linia Druga linia Czwarta linia");
  });

  it("keeps Tumblr poem headings and preformatted line layouts", () => {
    const html = sanitizeJournalHtml("<h1>Tytuł</h1><pre>wers pierwszy\n  wers drugi</pre>");

    expect(html).toBe("<h1>Tytuł</h1><pre>wers pierwszy\n  wers drugi</pre>");
  });

  it("creates plain search and widget text from formatted entries", () => {
    expect(journalEntryText({ contentFormat: "html", content: "<h2>Dzień</h2><p>Było <b>dobrze</b>.</p>" }))
      .toBe("Dzień Było dobrze.");
  });
});
