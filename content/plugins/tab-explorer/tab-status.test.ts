import { describe, expect, test } from "bun:test"
import { getTabIcon, tabStatus, tabTitle, type Tab } from "./tab-status"

const base: Tab = { sessionID: "ses_1234567890", active: false, busy: false, attention: false }

describe("tabStatus", () => {
  test("is idle when nothing is happening", () => {
    expect(tabStatus(base)).toBe("idle")
  })

  test("ranks attention above busy, error and activity", () => {
    expect(tabStatus({ ...base, attention: true, busy: true, unread: "error" })).toBe("attention")
  })

  test("ranks busy above error and activity", () => {
    expect(tabStatus({ ...base, busy: true, unread: "error" })).toBe("busy")
  })

  test("ranks a failed turn above new activity", () => {
    expect(tabStatus({ ...base, unread: "error" })).toBe("error")
    expect(tabStatus({ ...base, unread: "activity" })).toBe("activity")
  })
})

describe("getTabIcon", () => {
  test("maps each status to its icon", () => {
    expect(getTabIcon(base, "*")).toBe("")
    expect(getTabIcon({ ...base, attention: true }, "*")).toBe("?")
    expect(getTabIcon({ ...base, unread: "error" }, "*")).toBe("!")
    expect(getTabIcon({ ...base, unread: "activity" }, "*")).toBe("•")
  })

  test("uses the spinner frame while busy", () => {
    expect(getTabIcon({ ...base, busy: true }, "/")).toBe("/")
  })

  test("attention wins over busy, so no spinner", () => {
    expect(getTabIcon({ ...base, attention: true, busy: true }, "/")).toBe("?")
  })
})

describe("tabTitle", () => {
  test("uses the session title when present", () => {
    expect(tabTitle({ ...base, title: "Fix auth" })).toBe("Fix auth")
  })

  test("trims whitespace and ignores a blank title", () => {
    expect(tabTitle({ ...base, title: "  Fix auth  " })).toBe("Fix auth")
    expect(tabTitle({ ...base, title: "   " })).toBe("ses_1234")
  })

  test("falls back to the session ID prefix", () => {
    expect(tabTitle(base)).toBe("ses_1234")
  })
})
