const FINALE_TARGET_TOTAL = 365;
const RATING_SCALE = Array.from({ length: 10 }, (_, index) => (index + 1) / 2);

function finiteNumber(value) {
  return Number.isFinite(value) ? value : null;
}

function average(values) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
}

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function formatRating(value) {
  if (!Number.isFinite(value)) return "-";
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function formatRatingFixed(value) {
  return Number.isFinite(value) ? value.toFixed(2) : "-";
}

function formatMinutes(totalMinutes) {
  if (!Number.isFinite(totalMinutes) || totalMinutes <= 0) return "-";
  const hours = Math.floor(totalMinutes / 60);
  const minutes = Math.round(totalMinutes % 60);
  if (!hours) return `${minutes}m`;
  return minutes ? `${hours}h ${minutes}m` : `${hours}h`;
}

function albumTitle(row) {
  const artist = String(row?.artist || "").trim() || "-";
  const album = String(row?.album || "").trim() || "-";
  return `${artist} - ${album}`;
}

function parseDate(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

function daySpan(start, end) {
  const first = parseDate(start);
  const last = parseDate(end);
  if (!first || !last) return null;
  const diff = last.getTime() - first.getTime();
  return Math.max(1, Math.round(diff / 86400000) + 1);
}

function sortByRatingThenDate(a, b) {
  const ratingDiff = (finiteNumber(b.rating) ?? -Infinity) - (finiteNumber(a.rating) ?? -Infinity);
  if (ratingDiff) return ratingDiff;
  const minuteDiff = (finiteNumber(b.minutes) ?? -Infinity) - (finiteNumber(a.minutes) ?? -Infinity);
  if (minuteDiff) return minuteDiff;
  return String(a.date || "").localeCompare(String(b.date || ""));
}

function topBy(list, compare, limit = 5) {
  return [...list].sort(compare).slice(0, limit);
}

function addArtist(map, row) {
  const artist = String(row.artist || "").trim() || "-";
  const entry = map.get(artist) || {
    artist,
    count: 0,
    totalRating: 0,
    ratedCount: 0,
    totalMinutes: 0,
    bestAlbum: null
  };

  entry.count += 1;
  if (Number.isFinite(row.rating)) {
    entry.totalRating += row.rating;
    entry.ratedCount += 1;
    if (!entry.bestAlbum || row.rating > entry.bestAlbum.rating) {
      entry.bestAlbum = { album: row.album, rating: row.rating };
    }
  }
  if (Number.isFinite(row.minutes)) entry.totalMinutes += row.minutes;
  map.set(artist, entry);
}

export function computeBm365FinaleStats(rows) {
  const sourceRows = Array.isArray(rows) ? rows : [];
  const total = sourceRows.length;
  const doneRows = sourceRows.filter((row) => row.listened);
  const ratedRows = sourceRows.filter((row) => Number.isFinite(row.rating));
  const timeRows = sourceRows.filter((row) => Number.isFinite(row.minutes));
  const ratings = ratedRows.map((row) => row.rating);
  const minutes = timeRows.map((row) => row.minutes);
  const dates = sourceRows.map((row) => String(row.date || "")).filter(Boolean).sort();
  const years = new Map();
  const artists = new Map();
  const distribution = new Map(RATING_SCALE.map((rating) => [String(rating), 0]));

  ratedRows.forEach((row) => {
    const key = String(row.rating);
    distribution.set(key, (distribution.get(key) || 0) + 1);
  });

  sourceRows.forEach((row) => {
    const year = String(row.date || "").slice(0, 4);
    if (year) years.set(year, (years.get(year) || 0) + 1);
    addArtist(artists, row);
  });

  const artistList = Array.from(artists.values()).map((entry) => ({
    ...entry,
    averageRating: entry.ratedCount ? entry.totalRating / entry.ratedCount : null
  }));

  const firstDate = dates[0] || "";
  const lastDate = dates[dates.length - 1] || "";
  const spanDays = daySpan(firstDate, lastDate);
  const totalMinutes = minutes.reduce((sum, value) => sum + value, 0);
  const avgRating = average(ratings);
  const maxRating = ratings.length ? Math.max(...ratings) : null;
  const minRating = ratings.length ? Math.min(...ratings) : null;
  const perfectRows = ratedRows.filter((row) => row.rating === 5);
  const ratingDistribution = RATING_SCALE.map((rating) => ({
    rating,
    count: distribution.get(String(rating)) || 0,
    percent: ratedRows.length ? Math.round(((distribution.get(String(rating)) || 0) / ratedRows.length) * 100) : 0
  })).reverse();

  const topYear = Array.from(years.entries())
    .sort((a, b) => (b[1] !== a[1] ? b[1] - a[1] : a[0].localeCompare(b[0])))[0] || null;
  const signatureRating = ratingDistribution
    .filter((item) => item.count > 0)
    .sort((a, b) => (b.count !== a.count ? b.count - a.count : b.rating - a.rating))[0] || null;

  return {
    total,
    done: doneRows.length,
    left: Math.max(0, total - doneRows.length),
    pct: total ? Math.round((doneRows.length / total) * 100) : 0,
    ratedCount: ratedRows.length,
    unratedCount: Math.max(0, total - ratedRows.length),
    avgRating,
    medianRating: median(ratings),
    minRating,
    maxRating,
    perfectCount: perfectRows.length,
    firstDate,
    lastDate,
    spanDays,
    totalMinutes,
    timeCount: timeRows.length,
    avgMinutes: average(minutes),
    longestAlbum: topBy(timeRows, (a, b) => b.minutes - a.minutes, 1)[0] || null,
    shortestAlbum: topBy(timeRows, (a, b) => a.minutes - b.minutes, 1)[0] || null,
    topAlbums: topBy(ratedRows, sortByRatingThenDate, 8),
    deepestCuts: topBy(ratedRows, (a, b) => sortByRatingThenDate(b, a), 5),
    longestAlbums: topBy(timeRows, (a, b) => b.minutes - a.minutes, 5),
    ratingDistribution,
    signatureRating,
    totalArtists: artists.size,
    topArtistsByCount: topBy(
      artistList,
      (a, b) => (b.ratedCount !== a.ratedCount ? b.ratedCount - a.ratedCount : (b.averageRating || 0) - (a.averageRating || 0)),
      6
    ),
    topArtistsByAverage: topBy(
      artistList.filter((item) => item.ratedCount > 0),
      (a, b) => ((b.averageRating || 0) !== (a.averageRating || 0) ? (b.averageRating || 0) - (a.averageRating || 0) : b.ratedCount - a.ratedCount),
      6
    ),
    topArtistsByTime: topBy(artistList, (a, b) => b.totalMinutes - a.totalMinutes, 6),
    uniqueYears: years.size,
    topYear: topYear ? { year: topYear[0], count: topYear[1] } : null,
    allRows: sourceRows
  };
}

export function isBm365FinaleReady(rowsOrStats, targetTotal = FINALE_TARGET_TOTAL) {
  const stats = Array.isArray(rowsOrStats) ? computeBm365FinaleStats(rowsOrStats) : rowsOrStats;
  if (!stats) return false;
  const left = Number.isFinite(stats.left) ? stats.left : Math.max(0, stats.total - stats.done);
  const unratedCount = Number.isFinite(stats.unratedCount)
    ? stats.unratedCount
    : Math.max(0, stats.total - stats.ratedCount);
  return (
    stats.total === targetTotal &&
    stats.done === stats.total &&
    left === 0 &&
    stats.ratedCount === stats.total &&
    unratedCount === 0 &&
    stats.pct === 100
  );
}

function createEl(doc, tag, className, text) {
  const node = doc.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function addStat(doc, parent, label, value, tone = "") {
  const item = createEl(doc, "div", `bm365-finale-stat${tone ? ` ${tone}` : ""}`);
  item.appendChild(createEl(doc, "span", "", label));
  item.appendChild(createEl(doc, "strong", "", value));
  parent.appendChild(item);
  return item;
}

async function addCoverTile(doc, parent, row, resolveCover, index) {
  const tile = createEl(doc, "div", "bm365-finale-cover-tile");
  const imageWrap = createEl(doc, "div", "bm365-finale-cover");
  const url = typeof resolveCover === "function" ? await resolveCover(row) : "";
  if (url) {
    const img = createEl(doc, "img");
    img.alt = "";
    img.src = url;
    img.loading = "lazy";
    img.decoding = "async";
    imageWrap.appendChild(img);
  } else {
    imageWrap.appendChild(createEl(doc, "span", "", "BM"));
  }
  tile.appendChild(imageWrap);
  tile.appendChild(createEl(doc, "b", "", `#${index + 1}`));
  tile.appendChild(createEl(doc, "span", "", albumTitle(row)));
  parent.appendChild(tile);
}

async function fillCoverMosaic(doc, parent, rows, resolveCover, limit) {
  const list = rows.slice(0, limit);
  for (let index = 0; index < list.length; index += 1) {
    await addCoverTile(doc, parent, list[index], resolveCover, index);
  }
}

function appendRatingBars(doc, parent, stats) {
  stats.ratingDistribution.forEach((item) => {
    const row = createEl(doc, "div", "bm365-finale-bar-row");
    row.appendChild(createEl(doc, "span", "", formatRating(item.rating)));
    const track = createEl(doc, "div", "bm365-finale-bar-track");
    const fill = createEl(doc, "i");
    fill.style.width = `${item.percent}%`;
    track.appendChild(fill);
    row.appendChild(track);
    row.appendChild(createEl(doc, "b", "", String(item.count)));
    parent.appendChild(row);
  });
}

function appendArtistRows(doc, parent, artists, mode) {
  artists.slice(0, 5).forEach((artist, index) => {
    const row = createEl(doc, "div", "bm365-finale-list-row");
    row.appendChild(createEl(doc, "b", "", `#${index + 1}`));
    const copy = createEl(doc, "span", "", artist.artist);
    row.appendChild(copy);
    const score =
      mode === "time"
        ? formatMinutes(artist.totalMinutes)
        : mode === "count"
          ? `${artist.ratedCount}x`
          : formatRatingFixed(artist.averageRating);
    row.appendChild(createEl(doc, "strong", "", score));
    parent.appendChild(row);
  });
}

export async function renderBm365FinaleWidget(container, rows, options = {}) {
  if (!container) return null;
  const doc = options.document || container.ownerDocument || document;
  const stats = computeBm365FinaleStats(rows);
  if (!isBm365FinaleReady(stats, options.targetTotal || FINALE_TARGET_TOTAL)) return null;

  container.innerHTML = "";
  container.classList.remove("skeleton-block", "skeleton-lg");
  container.classList.add("bm365-finale-mount");

  const panel = createEl(doc, "section", "bm365-finale-widget");
  panel.appendChild(createEl(doc, "div", "bm365-finale-rune", "BM"));
  panel.appendChild(createEl(doc, "div", "bm365-finale-kicker", "Challenge complete"));
  panel.appendChild(createEl(doc, "h4", "", `${stats.done} / ${stats.total}`));

  const statGrid = createEl(doc, "div", "bm365-finale-widget-stats");
  addStat(doc, statGrid, "Avg", formatRatingFixed(stats.avgRating), "is-hot");
  addStat(doc, statGrid, "Time", formatMinutes(stats.totalMinutes));
  addStat(doc, statGrid, "Artists", stats.totalArtists);
  addStat(doc, statGrid, "Top", stats.signatureRating ? formatRating(stats.signatureRating.rating) : "-");
  panel.appendChild(statGrid);

  const mosaic = createEl(doc, "div", "bm365-finale-widget-covers");
  panel.appendChild(mosaic);
  container.appendChild(panel);
  await fillCoverMosaic(doc, mosaic, stats.topAlbums, options.resolveCover, 4);
  return panel;
}

export async function renderBm365FinalePage(container, rows, options = {}) {
  if (!container) return null;
  const doc = options.document || container.ownerDocument || document;
  const stats = computeBm365FinaleStats(rows);
  if (!isBm365FinaleReady(stats, options.targetTotal || FINALE_TARGET_TOTAL)) return null;

  container.innerHTML = "";

  const page = createEl(doc, "section", "bm365-finale-page");
  const hero = createEl(doc, "div", "bm365-finale-page-hero");
  hero.appendChild(createEl(doc, "div", "bm365-finale-rune", "BM365"));
  hero.appendChild(createEl(doc, "p", "bm365-finale-kicker", "The final reckoning"));
  hero.appendChild(createEl(doc, "h2", "", `${stats.done} albums. ${stats.pct} percent.`));
  hero.appendChild(createEl(doc, "p", "bm365-finale-lede", "A private end-screen for the whole campaign, unlocked only after the last rated album."));

  const heroStats = createEl(doc, "div", "bm365-finale-hero-stats");
  addStat(doc, heroStats, "Average rating", formatRatingFixed(stats.avgRating), "is-hot");
  addStat(doc, heroStats, "Total time", formatMinutes(stats.totalMinutes));
  addStat(doc, heroStats, "Artists", stats.totalArtists);
  addStat(doc, heroStats, "Perfect scores", stats.perfectCount);
  hero.appendChild(heroStats);
  page.appendChild(hero);

  const mosaic = createEl(doc, "div", "bm365-finale-cover-wall");
  page.appendChild(mosaic);
  await fillCoverMosaic(doc, mosaic, stats.topAlbums, options.resolveCover, 8);

  const grid = createEl(doc, "div", "bm365-finale-grid");
  const timeline = createEl(doc, "article", "bm365-finale-panel");
  timeline.appendChild(createEl(doc, "h3", "", "Runes of the run"));
  addStat(doc, timeline, "First date", stats.firstDate || "-");
  addStat(doc, timeline, "Last date", stats.lastDate || "-");
  addStat(doc, timeline, "Span", stats.spanDays ? `${stats.spanDays} days` : "-");
  addStat(doc, timeline, "Biggest year", stats.topYear ? `${stats.topYear.year} (${stats.topYear.count})` : "-");

  const ratings = createEl(doc, "article", "bm365-finale-panel");
  ratings.appendChild(createEl(doc, "h3", "", "Score altar"));
  addStat(doc, ratings, "Median", formatRatingFixed(stats.medianRating));
  addStat(doc, ratings, "Highest", formatRating(stats.maxRating));
  addStat(doc, ratings, "Lowest", formatRating(stats.minRating));
  const bars = createEl(doc, "div", "bm365-finale-bars");
  appendRatingBars(doc, bars, stats);
  ratings.appendChild(bars);

  const artists = createEl(doc, "article", "bm365-finale-panel");
  artists.appendChild(createEl(doc, "h3", "", "Artist sigils"));
  appendArtistRows(doc, artists, stats.topArtistsByCount, "count");
  appendArtistRows(doc, artists, stats.topArtistsByAverage, "average");

  const time = createEl(doc, "article", "bm365-finale-panel");
  time.appendChild(createEl(doc, "h3", "", "Time crypt"));
  addStat(doc, time, "Average length", formatMinutes(stats.avgMinutes));
  addStat(doc, time, "Longest", stats.longestAlbum ? `${albumTitle(stats.longestAlbum)} (${formatMinutes(stats.longestAlbum.minutes)})` : "-");
  addStat(doc, time, "Shortest", stats.shortestAlbum ? `${albumTitle(stats.shortestAlbum)} (${formatMinutes(stats.shortestAlbum.minutes)})` : "-");
  appendArtistRows(doc, time, stats.topArtistsByTime, "time");

  grid.appendChild(timeline);
  grid.appendChild(ratings);
  grid.appendChild(artists);
  grid.appendChild(time);
  page.appendChild(grid);

  container.appendChild(page);
  return page;
}
