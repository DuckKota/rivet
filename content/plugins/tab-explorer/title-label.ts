// Pure title-fitting logic, split out so the width-zero case can be tested
// without a live TUI.
//
// The sidebar slot hands the card its width only after the first layout pass,
// so a render can happen while the width is still unknown. In that case the
// title must be passed through untouched and left to the renderable's own
// truncation; clipping against a guessed width is what cut titles short.

const segmenter = new Intl.Segmenter(undefined, { granularity: "grapheme" })

/**
 * Terminal cells, not code units: a CJK glyph is two cells wide. Bun provides
 * the real measurement; the length fallback only keeps the module usable
 * outside Bun (where it under-counts wide glyphs).
 */
function cellWidth(value: string): number {
  return typeof Bun === "undefined" ? value.length : Bun.stringWidth(value)
}

/**
 * Whole user-perceived characters, so emoji and accents are never split. A
 * grapheme can span several code points (e.g. "e" + combining accent, or an
 * emoji built from a ZWJ sequence) and must stay together.
 */
function graphemes(value: string): string[] {
  return Array.from(segmenter.segment(value), (part) => part.segment)
}

/** Cuts at the last whole grapheme that fits, reserving one cell for "…". */
export function clip(value: string, width: number): string {
  // The title fits, so no clipping is needed.
  if (cellWidth(value) <= width) return value

  const limit = Math.max(0, width - cellWidth("…"))
  let result = ""
  let used = 0
  for (const part of graphemes(value)) {
    const size = cellWidth(part)
    // Stop before exceeding the budget, so a wide glyph never overflows.
    if (used + size > limit) break
    result += part
    used += size
  }

  return `${result}…`
}

/**
 * Returns the visible slice of a padded title, shifted by `frame`. `frame`
 * advances once per scroll step; the modulo makes the slice loop back to the
 * start.
 */
export function scrollWindow(value: string, width: number, frame: number): string {
  const parts = graphemes(`${value}         `)
  const offset = frame % parts.length
  let result = ""
  let used = 0
  for (let index = 0; used < width && index < parts.length; index += 1) {
    // The modulo makes the window wrap around the end of the padded title.
    const part = parts[(offset + index) % parts.length]
    const size = cellWidth(part)
    if (used + size > width) break
    result += part
    used += size
  }
  return result
}

/**
 * The title to draw at a known width, or the whole title when the width is not
 * known yet.
 *
 * - `title`: already-resolved display title (session title or ID prefix).
 * - `width`: cells available; 0 or negative means layout has not run yet.
 * - `scrolling`: true while the row is hovered.
 * - `frame`: current scroll step, only meaningful when scrolling.
 */
export function labelFor(title: string, width: number, scrolling: boolean, frame: number): string {
  // The width is not known yet, so the title must be passed through untouched.
  if (width <= 0) return title
  
  // The row is hovered and the title is too long, so it can be scrolled.
  if (scrolling && cellWidth(title) > width) return scrollWindow(title, width, frame)

  // Display the title clipped to the available width
  return clip(title, width)
}
