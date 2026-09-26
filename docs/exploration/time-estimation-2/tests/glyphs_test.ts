/** The arrow glyphs: whole, inside their area, and one on the edge when the area is small. */

import { alongSegment, glyphPath, placeGlyphs } from "../src/ui/glyphs.ts";
import { assert, assertEquals } from "./helpers.ts";

Deno.test("every glyph sits whole inside its area, with a margin", () => {
  const rect = { x: 3, y: 5, width: 120, height: 40 };
  const glyphs = placeGlyphs([rect]);
  assert(glyphs.length > 10);
  for (const glyph of glyphs) {
    assert(glyph.x - 3 >= rect.x + 2 && glyph.x + 3 <= rect.x + rect.width - 2, `x ${glyph.x}`);
    assert(glyph.y - 3 >= rect.y + 2 && glyph.y + 3 <= rect.y + rect.height - 2, `y ${glyph.y}`);
  }
});

Deno.test("every other row is offset by half a cell, so the glyphs read as a texture", () => {
  const glyphs = placeGlyphs([{ x: 0, y: 0, width: 140, height: 48 }]);
  const rows = [...new Set(glyphs.map((glyph) => glyph.y))].sort((a, b) => a - b);
  const firstX = (y: number) =>
    Math.min(...glyphs.filter((glyph) => glyph.y === y).map((glyph) => glyph.x));
  assertEquals(Math.abs(firstX(rows[1]) - firstX(rows[0])), 7);
});

Deno.test("the grid is anchored to the chart, so neighbouring areas line up", () => {
  const [a, b] = [
    placeGlyphs([{ x: 0, y: 0, width: 70, height: 36 }]),
    placeGlyphs([{ x: 70, y: 0, width: 70, height: 36 }]),
  ];
  const both = placeGlyphs([{ x: 0, y: 0, width: 140, height: 36 }]);
  assert(a.length + b.length <= both.length);
});

Deno.test("an area too small for a texture gets one larger glyph on its left edge", () => {
  assertEquals(placeGlyphs([{ x: 10, y: 20, width: 40, height: 6 }]), [{ x: 15, y: 23, size: 8 }]);
  assertEquals(placeGlyphs([{ x: 10, y: 20, width: 2, height: 2 }]), []);
});

Deno.test("a moved date carries arrows along it, or one arrowhead when it is short", () => {
  assertEquals(alongSegment(0, 60, 5).length, 5);
  assertEquals(alongSegment(0, 12, 5), [{ x: 8, y: 5, size: 6 }]);
  assertEquals(alongSegment(12, 0, 5), [{ x: 4, y: 5, size: 6 }]);
});

Deno.test("a glyph points its way", () => {
  assertEquals(glyphPath({ x: 10, y: 10, size: 6 }, "up"), "M10,7.5 L13,12.5 L7,12.5 Z");
  assertEquals(glyphPath({ x: 10, y: 10, size: 6 }, "right"), "M12.5,10 L7.5,7 L7.5,13 Z");
});
