const finite = (value) => Number.isFinite(Number(value));

export function normalizePoints(points) {
  if (!Array.isArray(points)) return [];
  return points
    .filter((point) => Array.isArray(point) && point.length >= 2 && finite(point[0]) && finite(point[1]))
    .map((point) => [Number(point[0]), Number(point[1])]);
}

export function linePolygon(lineOrGeometry, baselinePadding = 24) {
  const geometry = lineOrGeometry?.geometry || lineOrGeometry || {};
  const mask = normalizePoints(geometry.mask);
  if (mask.length >= 3) return mask;
  const baseline = normalizePoints(geometry.baseline);
  if (baseline.length < 2) return [];
  const bounds = pointsBounds(baseline);
  return [
    [bounds.x, bounds.y - baselinePadding],
    [bounds.right, bounds.y - baselinePadding],
    [bounds.right, bounds.bottom + baselinePadding],
    [bounds.x, bounds.bottom + baselinePadding],
  ];
}

export function pointsBounds(points) {
  const normalized = normalizePoints(points);
  if (!normalized.length) return null;
  const xs = normalized.map(([x]) => x);
  const ys = normalized.map(([, y]) => y);
  const x = Math.min(...xs);
  const y = Math.min(...ys);
  const right = Math.max(...xs);
  const bottom = Math.max(...ys);
  return { x, y, right, bottom, width: right - x, height: bottom - y };
}

export function geometryBounds(lineOrGeometry) {
  const polygon = linePolygon(lineOrGeometry);
  if (polygon.length) return pointsBounds(polygon);
  return pointsBounds(lineOrGeometry?.geometry?.baseline || lineOrGeometry?.baseline);
}

export function containTransform({
  sourceWidth,
  sourceHeight,
  containerWidth,
  containerHeight,
  containerLeft = 0,
  containerTop = 0,
}) {
  const sw = Math.max(1, Number(sourceWidth) || 1);
  const sh = Math.max(1, Number(sourceHeight) || 1);
  const cw = Math.max(0, Number(containerWidth) || 0);
  const ch = Math.max(0, Number(containerHeight) || 0);
  const scale = Math.min(cw / sw, ch / sh);
  const displayedWidth = sw * scale;
  const displayedHeight = sh * scale;
  return {
    scaleX: scale,
    scaleY: scale,
    displayedWidth,
    displayedHeight,
    offsetX: Number(containerLeft) + (cw - displayedWidth) / 2,
    offsetY: Number(containerTop) + (ch - displayedHeight) / 2,
  };
}

export function sourceToDisplayTransform({
  sourceWidth,
  sourceHeight,
  naturalWidth,
  naturalHeight,
  imageBox,
}) {
  const render = containTransform({
    sourceWidth: naturalWidth,
    sourceHeight: naturalHeight,
    containerWidth: imageBox.width,
    containerHeight: imageBox.height,
    containerLeft: imageBox.left,
    containerTop: imageBox.top,
  });
  return {
    ...render,
    scaleX: render.scaleX * (Number(naturalWidth) / Math.max(1, Number(sourceWidth))),
    scaleY: render.scaleY * (Number(naturalHeight) / Math.max(1, Number(sourceHeight))),
  };
}

export function transformPoints(points, transform) {
  return normalizePoints(points).map(([x, y]) => [
    transform.offsetX + x * transform.scaleX,
    transform.offsetY + y * transform.scaleY,
  ]);
}

export function sourceBoundsToNatural(bounds, sourceSize, naturalSize) {
  if (!bounds) return null;
  const scaleX = Number(naturalSize.width) / Math.max(1, Number(sourceSize.width));
  const scaleY = Number(naturalSize.height) / Math.max(1, Number(sourceSize.height));
  return {
    x: bounds.x * scaleX,
    y: bounds.y * scaleY,
    width: bounds.width * scaleX,
    height: bounds.height * scaleY,
  };
}

export function paddedCrop(bounds, imageWidth, imageHeight, padding = 0.3) {
  if (!bounds) return null;
  const verticalPadding = Math.max(12, bounds.height * padding);
  const horizontalPadding = Math.max(16, bounds.height * padding);
  const x = Math.max(0, bounds.x - horizontalPadding);
  const y = Math.max(0, bounds.y - verticalPadding);
  const right = Math.min(Number(imageWidth), bounds.x + bounds.width + horizontalPadding);
  const bottom = Math.min(Number(imageHeight), bounds.y + bounds.height + verticalPadding);
  return {
    x,
    y,
    width: Math.max(1, right - x),
    height: Math.max(1, bottom - y),
  };
}

export function expandPolygon(points, amount, imageWidth = Infinity, imageHeight = Infinity) {
  const polygon = normalizePoints(points);
  const bounds = pointsBounds(polygon);
  if (!bounds) return [];
  const delta = Math.max(0, Number(amount) || 0);
  const centerX = bounds.x + bounds.width / 2;
  const centerY = bounds.y + bounds.height / 2;
  return polygon.map(([x, y]) => [
    Math.max(0, Math.min(imageWidth, x + (x <= centerX ? -delta : delta))),
    Math.max(0, Math.min(imageHeight, y + (y <= centerY ? -delta : delta))),
  ]);
}

export function rotatePoint([x, y], width, height, angle) {
  const normalized = ((Number(angle) % 360) + 360) % 360;
  if (normalized === 90) return [height - y, x];
  if (normalized === 180) return [width - x, height - y];
  if (normalized === 270) return [y, width - x];
  return [x, y];
}

export function rotateGeometry(geometry, width, height, angle) {
  const result = { ...(geometry || {}) };
  for (const key of ["mask", "baseline"]) {
    if (Array.isArray(result[key])) {
      result[key] = normalizePoints(result[key]).map((point) =>
        rotatePoint(point, width, height, angle)
      );
    }
  }
  const normalized = ((Number(angle) % 360) + 360) % 360;
  result.coordinateSpace = {
    ...(result.coordinateSpace || {}),
    width: normalized === 90 || normalized === 270 ? height : width,
    height: normalized === 90 || normalized === 270 ? width : height,
    variant: "working",
  };
  return result;
}

export function selectedIndex(lines, selectedLineId) {
  if (!Array.isArray(lines) || !lines.length) return -1;
  const index = lines.findIndex((line) => line.id === selectedLineId);
  return index >= 0 ? index : 0;
}
