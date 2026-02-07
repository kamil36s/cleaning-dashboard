const MAX_ATTEMPTS_TOTAL = 6;
const MAX_ATTEMPTS_PER_PROVIDER = 2;

const FALLBACK_QUOTES = [
  { quote: "Small steps, every day.", author: "Dashboard" },
  { quote: "Clarity beats speed.", author: "Dashboard" },
  { quote: "Make it work, then make it nice.", author: "Dashboard" },
];

const PROVIDERS = [
  {
    name: "DummyJSON",
    url: "https://dummyjson.com/quotes/random",
    parse: (data) => ({
      quote: data && data.quote,
      author: data && data.author,
    }),
  },
  {
    name: "Quotable",
    url: "https://api.quotable.io/random",
    parse: (data) => ({
      quote: data && data.content,
      author: data && data.author,
    }),
  },
  {
    name: "RandomQuotes",
    url: "https://random-quotes-freeapi.vercel.app/api/random",
    parse: (data) => ({
      quote: data && data.quote,
      author: data && data.author,
    }),
  },
];

const WORD_RE = /[A-Za-z][A-Za-z'-]*/g;
const LETTER_RE = /[A-Za-z]/;

function isTitleCaseQuote(text) {
  if (!text) return false;
  WORD_RE.lastIndex = 0;
  const words = Array.from(text.matchAll(WORD_RE)).map((m) => m[0]);
  if (words.length < 3) return false;

  const isTitleCaseWord = (word) => {
    const letters = Array.from(word).filter((ch) => LETTER_RE.test(ch));
    if (letters.length === 0) return false;
    const [first, ...rest] = letters;
    const firstIsUpper =
      first === first.toLocaleUpperCase() &&
      first !== first.toLocaleLowerCase();
    if (!firstIsUpper) return false;
    const restHasLower = rest.some(
      (ch) => ch === ch.toLocaleLowerCase() && ch !== ch.toLocaleUpperCase()
    );
    const restHasUpper = rest.some(
      (ch) => ch === ch.toLocaleUpperCase() && ch !== ch.toLocaleLowerCase()
    );
    if (restHasUpper && !restHasLower) return false;
    return true;
  };

  const titleWords = words.filter(isTitleCaseWord).length;
  return titleWords === words.length;
}

function initQuoteWidget() {
  const card = document.getElementById("quote-card");
  const textEl = document.getElementById("quote-text");
  const authorEl = document.getElementById("quote-author");
  const statusEl = document.getElementById("quote-status");
  const refreshBtn = document.getElementById("quote-refresh");

  if (!card || !textEl || !authorEl) return;

  let inFlight = false;

  const setStatus = (msg) => {
    if (statusEl) statusEl.textContent = msg;
  };

  const setLoading = (isLoading) => {
    card.classList.toggle("loading", isLoading);
    if (refreshBtn) refreshBtn.disabled = isLoading;
  };

  const setQuote = ({ quote, author }) => {
    const safeQuote = quote ? String(quote).trim() : "";
    const safeAuthor = author ? String(author).trim() : "";
    textEl.textContent = safeQuote ? `"${safeQuote}"` : "-";
    authorEl.textContent = safeAuthor ? `- ${safeAuthor}` : "-";
  };

  const pickFallback = () =>
    FALLBACK_QUOTES[Math.floor(Math.random() * FALLBACK_QUOTES.length)];

  const loadQuote = async () => {
    if (inFlight) return;
    inFlight = true;
    setLoading(true);
    setStatus("Ladowanie...");
    try {
      let picked = null;
      let sourceName = "";
      let attempts = 0;

      for (const provider of PROVIDERS) {
        let localTries = 0;
        while (
          localTries < MAX_ATTEMPTS_PER_PROVIDER &&
          attempts < MAX_ATTEMPTS_TOTAL
        ) {
          localTries += 1;
          attempts += 1;

          let data = null;
          try {
            const res = await fetch(provider.url, { cache: "no-store" });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            data = await res.json();
          } catch (err) {
            break;
          }

          const parsed = provider.parse(data || {});
          if (!parsed || !parsed.quote) {
            break;
          }
          if (isTitleCaseQuote(parsed.quote)) {
            continue;
          }

          picked = parsed;
          sourceName = provider.name;
          break;
        }
        if (picked) break;
      }

      if (!picked || !picked.quote) throw new Error("Missing quote");
      setQuote({ quote: picked.quote, author: picked.author });
      setStatus(`Zrodlo: ${sourceName}`);
      card.dataset.ready = "true";
      document.dispatchEvent(new Event("quote:ready"));
    } catch (err) {
      setQuote(pickFallback());
      setStatus("Offline? Lokalny cytat.");
      card.dataset.ready = "true";
      document.dispatchEvent(new Event("quote:ready"));
    } finally {
      setLoading(false);
      inFlight = false;
    }
  };

  if (refreshBtn) refreshBtn.addEventListener("click", loadQuote);
  loadQuote();
}

let started = false;
const startQuote = () => {
  if (started) return;
  started = true;
  initQuoteWidget();
};

if (window.__dashboardStable) {
  startQuote();
} else {
  document.addEventListener("dashboard:stable", startQuote, { once: true });
  window.addEventListener("load", () => {
    setTimeout(startQuote, 1500);
  });
}
