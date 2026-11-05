// The API returns tabs as plain objects and exports no Tab type, so this lists
// the fields we use. `readonly` is TypeScript-only: it stops callers from
// mutating objects the host owns.
export type Tab = {
  readonly sessionID: string
  readonly title?: string
  readonly active: boolean
  readonly busy: boolean
  readonly attention: boolean
  readonly unread?: "activity" | "error"
}

export type TabStatus = "attention" | "busy" | "error" | "activity" | "idle"

// One priority chain for every per-tab indicator
export function tabStatus(tab: Tab): TabStatus {
  if (tab.attention) return "attention"
  if (tab.busy) return "busy"
  if (tab.unread === "error") return "error"
  if (tab.unread === "activity") return "activity"
  return "idle"
}

// Icon per status. Busy is absent on purpose: it shows the live spinner frame.
const TAB_ICON: Record<Exclude<TabStatus, "busy">, string> = {
  attention: "?",
  error: "!",
  activity: "•",
  idle: "",
}

// Return the title for a tab, falling back to the session ID if the title is empty
export function tabTitle(tab: Tab): string {
  return tab.title?.trim() || tab.sessionID.slice(0, 8)
}

// Return the status icon for a tab
export function getTabIcon(tab: Tab, spinnerFrame: string): string {
  const status = tabStatus(tab)
  return status === "busy" ? spinnerFrame : TAB_ICON[status]
}
