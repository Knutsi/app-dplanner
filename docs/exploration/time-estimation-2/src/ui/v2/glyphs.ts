/**
 * Arrow glyphs that fill an area to say which way it moved — placed one by one, never tiled
 * with an SVG `<pattern>`, so no glyph is ever cut in half at an edge.
 *
 * The grammar is fixed across v2: **vertical** arrows (▲ ▼) only ever mean scope — more or
 * less work, on an axis in days — and **horizontal** arrows (◀ ▶) only ever mean time —
 * earlier or later. The direction on the chart, the direction of the arrow and the meaning
 * agree, which is what lets the eye read an area before the legend.
 */

export type Direction = "up" | "down" | "left" | "right";

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Glyph {
  x: number; // Centre.
  y: number;
  size: number; // Base width; the height is 5/6 of it.
}

const CELL_W = 14;
const CELL_H = 12;
const GLYPH = 6;
const MARGIN = 2;
const EDGE_GLYPH = 8;
const SMALL_W = 16;
const SMALL_H = 10;

/**
 * Glyphs on a grid anchored to the chart's origin — every other row offset by half a cell,
 * so they read as a texture rather than columns — keeping only those that fit whole inside a
 * rect with a margin. A rect too small to hold that texture gets one larger glyph on its
 * left edge, where the change happened.
 */
export function placeGlyphs(rects: readonly Rect[]): Glyph[] {
  const found: Glyph[] = [];
  const half = GLYPH / 2;
  for (const rect of rects) {
    if (rect.width < SMALL_W || rect.height < SMALL_H) {
      if (rect.width >= 4 && rect.height >= 4) {
        found.push({
          x: rect.x + Math.min(EDGE_GLYPH, rect.width) / 2 + 1,
          y: rect.y + rect.height / 2,
          size: EDGE_GLYPH,
        });
      }
      continue;
    }
    const firstRow = Math.floor(rect.y / CELL_H);
    const lastRow = Math.ceil((rect.y + rect.height) / CELL_H);
    for (let row = firstRow; row <= lastRow; row += 1) {
      const y = row * CELL_H + CELL_H / 2;
      if (y - half < rect.y + MARGIN || y + half > rect.y + rect.height - MARGIN) continue;
      const shift = row % 2 ? CELL_W / 2 : 0;
      const firstColumn = Math.floor((rect.x - shift) / CELL_W);
      const lastColumn = Math.ceil((rect.x + rect.width - shift) / CELL_W);
      for (let column = firstColumn; column <= lastColumn; column += 1) {
        const x = column * CELL_W + CELL_W / 2 + shift;
        if (x - half < rect.x + MARGIN || x + half > rect.x + rect.width - MARGIN) continue;
        found.push({ x, y, size: GLYPH });
      }
    }
  }
  return found;
}

/** Glyphs along a horizontal segment — a date that moved — or one arrowhead when few fit. */
export function alongSegment(from: number, to: number, y: number, spacing = 10): Glyph[] {
  const [left, right] = [Math.min(from, to), Math.max(from, to)];
  const count = Math.floor((right - left - 4) / spacing);
  if (count < 2) {
    return right - left >= 4 ? [{ x: to - Math.sign(to - from) * 4, y, size: GLYPH }] : [];
  }
  const start = left + (right - left - (count - 1) * spacing) / 2;
  return Array.from(
    { length: count },
    (_, index) => ({ x: start + index * spacing, y, size: GLYPH }),
  );
}

/** An SVG path for one glyph: a filled triangle pointing its way. */
export function glyphPath(glyph: Glyph, direction: Direction): string {
  const w = glyph.size / 2;
  const h = (glyph.size * 5) / 12;
  const [x, y] = [glyph.x, glyph.y];
  const round = (value: number) => Math.round(value * 10) / 10;
  const points: [number, number][] = direction === "up"
    ? [[x, y - h], [x + w, y + h], [x - w, y + h]]
    : direction === "down"
    ? [[x, y + h], [x + w, y - h], [x - w, y - h]]
    : direction === "right"
    ? [[x + h, y], [x - h, y - w], [x - h, y + w]]
    : [[x - h, y], [x + h, y - w], [x + h, y + w]];
  return `M${points.map(([px, py]) => `${round(px)},${round(py)}`).join(" L")} Z`;
}
