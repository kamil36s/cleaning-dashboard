export function sourceAnchorOrder(book) {
  const order = new Map();
  let index = 0;
  for (const chapter of book?.chapters || []) {
    for (const paragraph of chapter.paragraphs || []) {
      for (const sentence of paragraph.sentences || []) order.set(sentence.id, index++);
    }
  }
  return order;
}

export function buildCommentaryRangeIndex(book, chunks = []) {
  const order = sourceAnchorOrder(book);
  return chunks
    .map((chunk) => ({ ...chunk, startIndex: order.get(chunk.start_source_id), endIndex: order.get(chunk.end_source_id) }))
    .filter((chunk) => Number.isInteger(chunk.startIndex) && Number.isInteger(chunk.endIndex) && chunk.startIndex <= chunk.endIndex)
    .sort((left, right) => left.startIndex - right.startIndex);
}

export function resolveCommentaryChunk(index, anchorId, order) {
  const position = order.get(anchorId);
  if (!Number.isInteger(position) || !index.length) return null;
  let low = 0;
  let high = index.length - 1;
  let candidate = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (index[middle].startIndex <= position) {
      candidate = middle;
      low = middle + 1;
    } else high = middle - 1;
  }
  const chunk = candidate >= 0 ? index[candidate] : null;
  return chunk && position <= chunk.endIndex ? chunk : null;
}

export class ReadingGuideRuntime {
  constructor({ onChange = () => {} } = {}) {
    this.onChange = onChange;
    this.book = null;
    this.order = new Map();
    this.index = [];
    this.currentAnchorId = null;
    this.currentChunkId = null;
    this.manualIndex = -1;
    this.followReading = true;
  }

  load(book, chunks = []) {
    this.book = book;
    this.order = sourceAnchorOrder(book);
    this.index = buildCommentaryRangeIndex(book, chunks);
    this.currentChunkId = null;
    this.manualIndex = -1;
    this.followReading = true;
    this.onChange(null, this);
  }

  setData(book, chunks = []) { this.load(book, chunks); }

  clear() {
    this.load(null, []);
    this.currentAnchorId = null;
  }

  sync(anchorId) {
    this.currentAnchorId = anchorId || null;
    if (!this.followReading) return false;
    return this._show(resolveCommentaryChunk(this.index, anchorId, this.order));
  }

  _show(chunk) {
    const identifier = chunk?.id || null;
    if (identifier === this.currentChunkId) return false;
    this.currentChunkId = identifier;
    this.manualIndex = chunk ? this.index.findIndex((row) => row.id === identifier) : -1;
    this.onChange(chunk || null, this);
    return true;
  }

  move(direction) {
    if (!this.index.length) return false;
    const current = this.manualIndex >= 0 ? this.manualIndex : this.index.findIndex((row) => row.id === this.currentChunkId);
    const next = Math.max(0, Math.min(this.index.length - 1, (current < 0 ? 0 : current) + direction));
    this.followReading = false;
    return this._show(this.index[next]);
  }

  follow() {
    this.followReading = true;
    return this._show(resolveCommentaryChunk(this.index, this.currentAnchorId, this.order));
  }

  previous() { this.move(-1); }
  next() { this.move(1); }

  current() {
    return this.index.find((row) => row.id === this.currentChunkId) || null;
  }
}
