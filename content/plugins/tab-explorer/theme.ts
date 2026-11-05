// Every colour the card uses. Theme token paths live here, in one list, because
// they are the part most likely to change between OpenCode releases.

import type { TabStatus } from "./tab-status"

/**
 * Reads a theme token defensively. Theme shapes drift between OpenCode
 * releases; a missing colour means "no colour", never a throw.
 *
 * A token can be a CSS colour string or a renderer Colour object, so the object
 * branch casts it to string: `fg` and `backgroundColor` accept both. Candidate
 * paths are tried in order, first hit wins.
 */
export function themeToken(theme: unknown, ...paths: string[]): string | undefined {
  for (const path of paths) {
    let value: unknown = theme
    for (const key of path.split(".")) {
      value = (value as Record<string, unknown> | undefined)?.[key]
    }
    if (typeof value === "string") return value
    if (value && typeof value === "object") return value as unknown as string
  }
  return undefined
}

/**
 * Builds the card's colour getters from a theme accessor. They stay functions
 * so they re-read the theme instead of freezing the colour at mount.
 */
export function createTheme(theme: () => unknown) {
  const token = (...paths: string[]) => themeToken(theme(), ...paths)

  const accent = () => token("text.action.primary.base", "text.action.primary", "hue.blue.500")
  const muted = () => token("text.muted", "text.subdued", "textMuted")
  const raised = () => token("background.raised.high", "background.raised.base", "background.surface.offset")
  const text = () => token("text.base", "text.primary", "textMuted")
  const panel = () => token("background.base", "background.raised.base")
  const success = () => token("text.feedback.success.base", "text.feedback.success")
  const warning = () => token("text.feedback.warning.base", "text.feedback.warning")
  const error = () => token("text.feedback.error.base", "text.feedback.error")

  // Icon colour per tab status. Attention and error share a colour family on
  // purpose: both need a look, one is a question, one is a failure.
  const iconColors: Record<TabStatus, () => string | undefined> = {
    attention: warning,
    busy: success,
    error,
    activity: accent,
    idle: accent,
  }

  return {
    accent,
    muted,
    raised,
    text,
    panel,
    success,
    warning,
    error,
    iconColor: (status: TabStatus) => iconColors[status](),
  }
}
