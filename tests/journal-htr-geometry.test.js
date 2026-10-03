import { describe, expect, it } from "vitest";
import {
  geometryBounds,
  linePolygon,
  paddedCrop,
  rotateGeometry,
  selectedIndex,
  sourceBoundsToNatural,
  sourceToDisplayTransform,
  transformPoints,
} from "../js/journal-htr-geometry.js";

const testImage = { width: 1000, height: 500 };
const lines = [
  { id: "line-a", lineOrder: 0, geometry: { mask: [[100, 50], [900, 50], [900, 90], [100, 90]] } },
  { id: "line-b", lineOrder: 1, geometry: { mask: [[120, 200], [880, 200], [880, 250], [120, 250]] } },
  { id: "line-c", lineOrder: 2, geometry: { mask: [[80, 400], [920, 400], [920, 450], [80, 450]] } },
];

describe("Journal HTR geometry mapping", () => {
  it("maps a known polygon through object-fit contain including letterboxing", () => {
    const transform = sourceToDisplayTransform({
      sourceWidth: testImage.width,
      sourceHeight: testImage.height,
      naturalWidth: testImage.width,
      naturalHeight: testImage.height,
      imageBox: { left: 0, top: 0, width: 800, height: 800 },
    });

    expect(transform).toMatchObject({
      scaleX: 0.8,
      scaleY: 0.8,
      displayedWidth: 800,
      displayedHeight: 400,
      offsetX: 0,
      offsetY: 200,
    });
    expect(transformPoints(linePolygon(lines[1]), transform)).toEqual([
      [96, 360],
      [704, 360],
      [704, 400],
      [96, 400],
    ]);
  });

  it("uses the selected stable lineId for overlay, crop and transcription after sorting", () => {
    const selectedLineId = "line-b";
    const sorted = [lines[2], lines[0], lines[1]];
    const line = sorted[selectedIndex(sorted, selectedLineId)];
    const bounds = geometryBounds(line);
    const naturalBounds = sourceBoundsToNatural(bounds, testImage, testImage);
    const crop = paddedCrop(naturalBounds, testImage.width, testImage.height);

    expect(line.id).toBe(selectedLineId);
    expect(bounds).toMatchObject({ x: 120, y: 200, width: 760, height: 50 });
    expect(crop.x).toBeLessThan(bounds.x);
    expect(crop.y).toBeLessThan(bounds.y);
    expect(crop.x + crop.width).toBeGreaterThan(bounds.x + bounds.width);
  });

  it("recalculates overlay after window resize and scale change", () => {
    const first = sourceToDisplayTransform({
      sourceWidth: 1000,
      sourceHeight: 500,
      naturalWidth: 1000,
      naturalHeight: 500,
      imageBox: { left: 10, top: 20, width: 500, height: 500 },
    });
    const resized = sourceToDisplayTransform({
      sourceWidth: 1000,
      sourceHeight: 500,
      naturalWidth: 2000,
      naturalHeight: 1000,
      imageBox: { left: 30, top: 40, width: 1000, height: 700 },
    });

    expect(first).toMatchObject({ scaleX: 0.5, scaleY: 0.5, offsetX: 10, offsetY: 145 });
    expect(resized).toMatchObject({ scaleX: 1, scaleY: 1, offsetX: 30, offsetY: 140 });
  });

  it("keeps the same line geometry after a 90 degree working-image rotation", () => {
    const rotated = rotateGeometry(lines[0].geometry, 1000, 500, 90);
    expect(rotated.coordinateSpace).toMatchObject({ width: 500, height: 1000 });
    expect(rotated.mask).toEqual([
      [450, 100],
      [450, 900],
      [410, 900],
      [410, 100],
    ]);
    expect(geometryBounds(rotated)).toMatchObject({
      x: 410,
      y: 100,
      width: 40,
      height: 800,
    });
  });
});
