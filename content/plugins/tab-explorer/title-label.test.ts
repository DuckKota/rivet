import { describe, expect, test } from "bun:test"
import { clip, labelFor, scrollWindow } from "./title-label"

describe("labelFor", () => {
  test("does not clip while the width is unknown", () => {
    const title = "a-very-long-session-title-that-will-not-fit"
    expect(labelFor(title, 0, false, 0)).toBe(title)
    expect(labelFor(title, -10, false, 0)).toBe(title)
  })

  test("shows short titles whole", () => {
    expect(labelFor("Fix auth", 20, false, 0)).toBe("Fix auth")
  })

  test("clips long titles with an ellipsis", () => {
    expect(labelFor("a-very-long-session-title", 10, false, 0)).toBe("a-very-lo…")
  })

  test("scrolls only while hovered", () => {
    const title = "a-very-long-session-title"
    expect(labelFor(title, 10, false, 3)).toBe("a-very-lo…")
    expect(labelFor(title, 10, true, 0)).toBe("a-very-lon")
    expect(labelFor(title, 10, true, 1)).toBe("-very-long")
  })
})

describe("helpers", () => {
  test("clip leaves a title that exactly fits", () => {
    expect(clip("abcde", 5)).toBe("abcde")
  })

  test("scrollWindow returns a slice of the requested width", () => {
    expect(scrollWindow("abcdef", 4, 0)).toHaveLength(4)
    expect(scrollWindow("abcdef", 4, 7)).toHaveLength(4)
  })

  test("counts wide characters as two cells", () => {
    expect(clip("修复登录页面错误", 10)).toBe("修复登录…")
    expect(labelFor("修复登录页面错误", 10, true, 0)).toBe("修复登录页")
  })

  test("never splits a surrogate pair", () => {
    expect(clip("👍👍👍👍", 3).isWellFormed()).toBe(true)
  })
})
