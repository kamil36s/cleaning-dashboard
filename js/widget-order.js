const DEFAULT_ORDER = {
  weather: 10,
  aqi: 20,
  cleaning: 30,
  reading: 40,
  quote: 45,
  bm365: 50,
  oscars: 60,
  habits: 70,
  events: 80,
  sensors: 90,
  "habits-timeline": 100,
};

const DEFAULT_CONFIG = {
  order: DEFAULT_ORDER,
  visible: {},
};

async function loadOrder() {
  try {
    const res = await fetch("./data/widget-order.json", { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      if (data && typeof data === "object") {
        return {
          order: data.order || DEFAULT_ORDER,
          visible: data.visible || {},
        };
      }
    }
  } catch {}
  return DEFAULT_CONFIG;
}

function applyOrder(orderMap) {
  const dash = document.querySelector(".dash");
  if (!dash) return;
  const items = Array.from(dash.children).filter((el) =>
    el.classList.contains("card")
  );
  const originalIndex = new Map(items.map((el, i) => [el, i]));
  const weight = (el) => {
    const key = el.dataset.widget || "";
    const val = orderMap[key];
    return Number.isFinite(val) ? val : 1000;
  };

  items
    .slice()
    .sort((a, b) => {
      const diff = weight(a) - weight(b);
      if (diff !== 0) return diff;
      return originalIndex.get(a) - originalIndex.get(b);
    })
    .forEach((el) => dash.appendChild(el));
}

function applyVisibility(visibleMap) {
  const dash = document.querySelector(".dash");
  if (!dash) return;
  const items = Array.from(dash.children).filter((el) =>
    el.classList.contains("card")
  );
  items.forEach((el) => {
    const key = el.dataset.widget || "";
    const show = visibleMap[key] !== false;
    if (key === "quote") {
      el.dataset.enabled = show ? "true" : "false";
      el.setAttribute("hidden", "");
      el.style.gridRowEnd = "";
      return;
    }
    if (show) {
      el.removeAttribute("hidden");
      el.style.gridRowEnd = "";
    } else {
      el.setAttribute("hidden", "");
      el.style.gridRowEnd = "";
    }
  });
}

let resizeRaf = 0;
let stableTimer = 0;
let windowLoaded = false;

function getPendingRequests() {
  return Number.isFinite(window.__pendingRequests)
    ? window.__pendingRequests
    : 0;
}

function scheduleLayoutStable() {
  if (!windowLoaded) return;
  if (stableTimer) clearTimeout(stableTimer);
  stableTimer = setTimeout(() => {
    if (getPendingRequests() > 0) {
      scheduleLayoutStable();
      return;
    }
    window.__dashboardStable = true;
    document.dispatchEvent(new CustomEvent("dashboard:stable"));
  }, 2000);
}

function scheduleMasonryResize() {
  if (resizeRaf) cancelAnimationFrame(resizeRaf);
  resizeRaf = requestAnimationFrame(resizeMasonry);
}

function resizeMasonry() {
  const grid = document.querySelector(".dash");
  if (!grid) return;
  const styles = getComputedStyle(grid);
  const rowHeight = parseInt(styles.getPropertyValue("grid-auto-rows"), 10);
  const rowGap = parseInt(styles.getPropertyValue("gap"), 10);
  if (!rowHeight) return;

  const items = Array.from(grid.children).filter((el) =>
    el.classList.contains("card") && !el.hasAttribute("hidden")
  );
  items.forEach((item) => {
    const h = item.getBoundingClientRect().height;
    const span = Math.ceil((h + rowGap) / (rowHeight + rowGap));
    item.style.gridRowEnd = `span ${span}`;
  });

  placeQuoteInGap(grid, rowHeight, rowGap);
  grid.classList.add("layout-ready");
  scheduleLayoutStable();
}

function placeQuoteInGap(grid, rowHeight, rowGap) {
  const quote = document.getElementById("quote-card");
  if (!quote) return;
  if (quote.dataset.enabled === "false") {
    quote.setAttribute("hidden", "");
    return;
  }
  if (quote.dataset.ready !== "true") {
    quote.setAttribute("hidden", "");
    return;
  }

  quote.style.gridColumn = "";
  quote.style.gridRowStart = "";
  quote.style.gridRowEnd = "";
  quote.style.alignSelf = "";
  quote.style.minHeight = "";
  quote.style.height = "";

  const anchor = grid.querySelector('.card[data-widget="habits-timeline"]');
  if (!anchor || anchor.hasAttribute("hidden")) {
    quote.setAttribute("hidden", "");
    return;
  }

  const gridRect = grid.getBoundingClientRect();
  const anchorRect = anchor.getBoundingClientRect();
  const anchorTop = anchorRect.top - gridRect.top;

  const candidates = Array.from(grid.children).filter(
    (el) =>
      el.classList.contains("card") &&
      !el.hasAttribute("hidden") &&
      el !== quote &&
      el !== anchor
  );
  if (candidates.length === 0) {
    quote.setAttribute("hidden", "");
    return;
  }

  const columnsMap = new Map();
  candidates.forEach((card) => {
    const rect = card.getBoundingClientRect();
    const left = Math.round(rect.left - gridRect.left);
    if (!columnsMap.has(left)) columnsMap.set(left, []);
    columnsMap.get(left).push({ card, rect });
  });

  const colLefts = Array.from(columnsMap.keys()).sort((a, b) => a - b);
  if (colLefts.length < 2) {
    quote.setAttribute("hidden", "");
    return;
  }

  const rowUnit = rowHeight + rowGap;
  const minGapRows = 2;
  const anchorRowStart = Math.round(anchorTop / rowUnit) + 1;

  let best = null;
  colLefts.forEach((left, index) => {
    const entries = columnsMap.get(left) || [];
    if (entries.length === 0) return;

    let maxRowEnd = 1;
    entries.forEach(({ card, rect }) => {
      const top = rect.top - gridRect.top;
      const rowStart = Math.round(top / rowUnit) + 1;
      if (rowStart >= anchorRowStart) return;

      let span = 1;
      const inlineEnd = card.style.gridRowEnd || "";
      const match = inlineEnd.match(/span\s+(\d+)/);
      if (match) {
        span = parseInt(match[1], 10) || 1;
      } else {
        span = Math.ceil((rect.height + rowGap) / rowUnit);
      }
      const rowEnd = rowStart + span;
      if (rowEnd > maxRowEnd) maxRowEnd = rowEnd;
    });

    const gapRows = anchorRowStart - maxRowEnd;
    if (gapRows < minGapRows) return;
    if (!best || gapRows > best.gapRows) {
      best = { index, gapRows, rowStart: maxRowEnd };
    }
  });

  if (!best) {
    quote.setAttribute("hidden", "");
    return;
  }

  if (!best || best.gapRows < minGapRows) {
    quote.setAttribute("hidden", "");
    return;
  }

  const gapRowStart = best.rowStart;
  const span = anchorRowStart - gapRowStart;
  if (span < 1) {
    quote.setAttribute("hidden", "");
    return;
  }

  quote.style.gridColumn = `${best.index + 1}`;
  quote.style.gridRowStart = `${gapRowStart}`;
  quote.style.gridRowEnd = `${anchorRowStart}`;
  quote.style.alignSelf = "stretch";
  quote.style.minHeight = "0";
  quote.style.height = "100%";
  quote.removeAttribute("hidden");
}

function watchGrid() {
  const grid = document.querySelector(".dash");
  if (!grid) return;

  const mo = new MutationObserver(() => scheduleMasonryResize());
  mo.observe(grid, { childList: true, subtree: true, characterData: true });

  if ("ResizeObserver" in window) {
    const ro = new ResizeObserver(() => scheduleMasonryResize());
    Array.from(grid.children).forEach((el) => {
      if (el.classList.contains("card")) ro.observe(el);
    });
  }

  window.addEventListener("resize", scheduleMasonryResize);
  window.addEventListener("load", () => {
    windowLoaded = true;
    scheduleMasonryResize();
    scheduleLayoutStable();
  });

  document.addEventListener("quote:ready", scheduleMasonryResize);
  document.addEventListener("dashboard:net", scheduleLayoutStable);
}

document.addEventListener("DOMContentLoaded", async () => {
  const config = await loadOrder();
  applyVisibility(config.visible || {});
  applyOrder(config.order || DEFAULT_ORDER);
  scheduleMasonryResize();
  watchGrid();
});
