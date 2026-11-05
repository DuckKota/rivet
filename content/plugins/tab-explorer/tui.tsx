/** @jsxImportSource @opentui/solid */

// The `@jsxImportSource` pragma on line 1 tells the compiler that <box> and
// <text> come from @opentui/solid (the terminal renderer), not React.

    //------------------------------------------------------------------- //
   //     Sidebar tab explorer                                           //
  //  Focus, close, and create tabs without hunting the native strip.   //
 //   Native tabs must be enabled; otherwise the slot renders nothing. //
// ------------------------------------------------------------------ //

// SolidJS (solid-js) is a standalone open-source reactive UI library, not an
// OpenCode project: https://www.solidjs.com. The TUI is built on it, so
// components here follow Solid rules: signals hold state, memos cache derived
// values, effects re-run when anything they read changes.
import { For, Show, createEffect, createMemo, createSignal, onCleanup } from "solid-js"
// Runtime-provided by OpenCode: https://opencode.ai/v2/docs/build/plugins/cli
import { Plugin, usePlugin } from "@opencode/plugin/tui"
import { TextAttributes } from "@opentui/core"

// title-label.js handles scrolling and clipping of tab titles
import { labelFor } from "./title-label"
// tab-status.ts holds the Tab shape, status, title and icon
import { getTabIcon, tabStatus, tabTitle, type Tab } from "./tab-status"
// theme.ts holds every colour lookup
import { createTheme } from "./theme"

// Animation and layout constants
const ACTIVE_TAB_INDICATOR = "▎" // The active tab indicator
const SPINNER = ["|", "/", "-", "\\"]
// How many cells the icon column takes. Every icon is one cell wide.
const ICON_WIDTH = 1
const SPINNER_INTERVAL = 100 // 10fps (unit is ms)
const SCROLL_INTERVAL = 100 // 10fps (unit is ms)
// Cells in a row that are not the title:
// padding (4) + rail (1) + close icon (1) + gaps (3) = 9, plus the icon column
const NON_TITLE_WIDTH = 9 + ICON_WIDTH

/**
 * A frame counter for animations: 0, 1, 2, ... advancing every `interval` ms,
 * but only while `active` returns true. An idle sidebar therefore runs no timer.
 *
 * `active` is passed as a function, not a boolean, so this can re-check it on
 * each pass instead of freezing the value from the moment of the call.
 *
 * Returns the getter and a reset, so a caller can start again at frame 0.
 */
function useFrame(active: () => boolean, interval: number) {
  // createSignal(initialValue) returns two functions: a getter and a setter.
  // Here the value starts at 0 and climbs by one on each timer tick. `frame`
  // is the getter, so it is read as frame() rather than frame.
  const [frame, setFrame] = createSignal(0)

  // createEffect runs once now, then re-runs whenever a signal read inside it
  // changes. Reading active() here is what starts and stops the timer.
  createEffect(() => {
    if (!active()) return
    // Functional update: receives the current value, returns the next one.
    const timer = setInterval(() => setFrame((value) => value + 1), interval)
    // Runs before the next effect pass and on unmount, so timers never stack.
    onCleanup(() => clearInterval(timer))
  })

  function reset() {
    setFrame(0)
  }

  return [frame, reset] as const
}

function SidebarTabs() {
  // The plugin's handle on the running OpenCode session
  const opencode = usePlugin()

  // openTabs is a memoized read of the current tab list.
  // It re-runs whenever the tab list changes, so the UI updates automatically.
  const openTabs = createMemo(() => opencode.ui.tabs.list() as readonly Tab[])

  // Signals for tracking local UI states
  const [getHoveredTabID, setHoveredTabID] = createSignal<string>()
  const [getHoveredCloseTabID, setHoveredCloseTabID] = createSignal<string>()
  const [getHoveredNewButton, setHoveredNewButton] = createSignal(false)
  const [getIsCollapsed, setIsCollapsed] = createSignal(false)

  // Two pieces for one job: knowing how wide the whole card is.
  // getCardElement: the <box> itself, handed over by `ref` once it is on screen.
  // getCardWidth: that box's total width in cells, copied out after layout and on
  // every resize. This is the outer width, padding and rail included; the title
  // gets what is left after NON_TITLE_WIDTH.
  const [getCardElement, setCardElement] = createSignal<{ width: number }>()
  const [getCardWidth, setCardWidth] = createSignal(0)

  // Timers run only when needed:
  // The spinner runs while a tab is busy
  // The title scroll runs while a row is hovered
  const isBusy = () => !getIsCollapsed() && openTabs().some((tab) => tab.busy)
  const isHovering = () => !getIsCollapsed() && getHoveredTabID() !== undefined
  const [spinnerFrame] = useFrame(isBusy, SPINNER_INTERVAL)
  const [scrollFrame, resetScrollFrame] = useFrame(isHovering, SCROLL_INTERVAL)

  // Start the scroll at the first character whenever a different row is
  // hovered, so a title does not resume mid-way from the last hover.
  createEffect(() => {
    getHoveredTabID()
    resetScrollFrame()
  })

  // Theme reads are wrapped in functions so they re-evaluate when the theme changes
  const { accent,
          muted,
          raised,
          text,
          panel,
          success,
          warning,
          error,
          iconColor
        } = createTheme(() => opencode.theme)

  // ---- Layout -------------------------------------------------------------

  // Copies the card's current width into the getCardWidth signal. Runs once
  // after mounting and again on every terminal resize, so long titles always
  // clip against the width on screen rather than the width at mount.
  function measure() {
    setCardWidth(getCardElement()?.width ?? 0)
  }

  createEffect(() => {
    // opencode.renderer is the OpenTUI renderer; "resize" is its terminal event.
    const renderer = opencode.renderer
    if (!renderer?.on) return

    // Wait one tick before reading the width. The new width is only set once
    // the renderer has laid the card out again, which happens after this code
    // runs; reading straight away would return the old size. The zero-delay
    // timer just means "after the current work finishes".
    const onResize = () => setTimeout(measure, 0)
    renderer.on("resize", onResize)
    setTimeout(measure, 0)
    onCleanup(() => renderer.off("resize", onResize))
  })

  // ---- Row helpers --------------------------------------------------------

  // Width left for the title: the card width minus padding, rail, icon, close
  // icon and gaps. Zero until the first layout pass; labelFor leaves the title
  // alone then.
  function getTitleWidth() {
    const width = getCardWidth()
    return width > 0 ? Math.max(6, Math.floor(width - NON_TITLE_WIDTH)) : 0
  }

  // Active wins over hover and attention so the focused row always reads as
  // focused. Hover brightens the title instead of painting a background.
  function getTitleColor(tab: Tab) {
    if (tab.active) return accent()
    if (isRowHovered(tab)) return text()
    if (tab.attention) return warning()
    return muted()
  }

  // Icon colour comes from tabStatus() via theme.ts, so the priority chain and
  // the palette each live in one place.
  function getTabIconColor(tab: Tab) {
    return iconColor(tabStatus(tab))
  }

  // The spinner character for the current frame, used as the busy icon.
  function getCurrentSpinner() {
    return SPINNER[spinnerFrame() % SPINNER.length]
  }

  // Is this row the one under the pointer?
  function isRowHovered(tab: Tab) {
    return getHoveredTabID() === tab.sessionID
  }

  // The row's title, fitted to the current width and scrolled while hovered.
  function rowLabel(tab: Tab) {
    return labelFor(tabTitle(tab), getTitleWidth(), isRowHovered(tab), scrollFrame())
  }

  // Spread onto every cell in a row, so moving across the title, icon or close
  // icon keeps the row highlighted.
  function rowHoverHandlers(tab: Tab) {
    return {
      onMouseOver: () => setHoveredTabID(tab.sessionID),
      onMouseOut: () => setHoveredTabID(undefined),
    }
  }

  // ---- Actions ------------------------------------------------------------

  // The header row is the collapse button. Clearing the hover state matters:
  // the rows unmount without a mouse-out event, so a row could otherwise stay
  // highlighted after expanding again.
  function toggleCollapsed() {
    setIsCollapsed(!getIsCollapsed())
    setHoveredTabID(undefined)
    setHoveredCloseTabID(undefined)
  }

  // The close icon lives inside the row, which also focuses the tab on click.
  // Stopping propagation keeps one click from doing both.
  function closeTab(event: { stopPropagation(): void }, tab: Tab) {
    event.stopPropagation()
    opencode.ui.tabs.close(tab.sessionID)
  }

  // Show renders its children only while `when` is truthy; with no fallback it
  // renders nothing. Tabs disabled means the card disappears instead of showing
  // an empty box.
  return (
    <Show when={opencode.ui.tabs.enabled()}>
      {/* <box> and <text> are OpenTUI renderables. Layout props are flexbox
          (Yoga), the same vocabulary as CSS. The ref callback receives the
          renderable instance, which is how the card gets measured. */}
      <box
        ref={(element) => setCardElement(element)}
        backgroundColor={raised()}
        paddingLeft={2}
        paddingRight={2}
        paddingTop={1}
        paddingBottom={1}
        gap={1}
      >
        {/* The header row is the collapse button. */}
        <box flexDirection="row" justifyContent="space-between" onMouseDown={toggleCollapsed}>
          {/* selectable={false} on every <text>: text is selectable by default,
              and a drag-select would otherwise swallow mouse clicks on rows. */}
          <text selectable={false} fg={accent()} attributes={TextAttributes.BOLD}>
            {getIsCollapsed() ? "▸ Tabs" : "▾ Tabs"}
          </text>
          <text selectable={false} fg={muted()}>{openTabs().length}</text>
        </box>
        <Show when={!getIsCollapsed()}>
          {/* Nested Show: the empty-state text is the fallback, not a sibling. */}
          <Show when={openTabs().length > 0} fallback={<text selectable={false} fg={muted()}>No open tabs</text>}>
            <box>
              {/* For renders one row per item and passes the item itself (not
                  an index); each row's expressions track that tab's fields. */}
              <For each={openTabs()}>
                {(tab) => (
                  // The row acts as a button: click focuses, hover brightens the
                  // title and reveals the close icon.
                  <box
                    flexDirection="row"
                    gap={1}
                    onMouseDown={() => opencode.ui.tabs.focus(tab.sessionID)}
                    {...rowHoverHandlers(tab)}
                  >
                    <text selectable={false} fg={accent()} width={1} {...rowHoverHandlers(tab)}>
                      {tab.active ? ACTIVE_TAB_INDICATOR : " "}
                    </text>
                    <text
                      selectable={false}
                      fg={getTabIconColor(tab)}
                      width={ICON_WIDTH}
                      {...rowHoverHandlers(tab)}
                    >
                      {getTabIcon(tab, getCurrentSpinner())}
                    </text>
                    {/* flexGrow takes the row's remaining width. title-label.ts
                        already clipped to that width; truncate is a second
                        guard for the first frame, before width is measured. */}
                    <text
                      selectable={false}
                      flexGrow={1}
                      wrapMode="none"
                      truncate
                      fg={getTitleColor(tab)}
                      attributes={tab.active ? TextAttributes.BOLD : undefined}
                      {...rowHoverHandlers(tab)}
                    >
                      {rowLabel(tab)}
                    </text>
                    {/* The close icon only shows while the row is hovered. The
                        cell stays in place either way, so it remains a hit
                        target and the row keeps its width. stopPropagation in
                        closeTab keeps this click from also focusing the tab. */}
                    <text
                      selectable={false}
                      fg={getHoveredCloseTabID() === tab.sessionID ? error() : muted()}
                      onMouseDown={(event) => closeTab(event, tab)}
                      onMouseOver={() => {
                        setHoveredTabID(tab.sessionID)
                        setHoveredCloseTabID(tab.sessionID)
                      }}
                      onMouseOut={() => {
                        setHoveredTabID(undefined)
                        setHoveredCloseTabID(undefined)
                      }}
                    >
                      {isRowHovered(tab) ? "×" : " "}
                    </text>
                  </box>
                )}
              </For>
            </box>
          </Show>
          {/* Dispatch the built-in command rather than creating a session here,
              so keybindings, defaults and session rules stay in one place. */}
          <box
            width="100%"
            flexDirection="row"
            justifyContent="center"
            backgroundColor={getHoveredNewButton() ? accent() : undefined}
            onMouseOver={() => setHoveredNewButton(true)}
            onMouseOut={() => setHoveredNewButton(false)}
            onMouseDown={() => opencode.keymap.dispatch("session.new")}
          >
            <text
              selectable={false}
              fg={getHoveredNewButton() ? panel() : accent()}
              attributes={TextAttributes.BOLD}
              onMouseOver={() => setHoveredNewButton(true)}
              onMouseOut={() => setHoveredNewButton(false)}
            >
              + New tab
            </text>
          </box>
        </Show>
      </box>
    </Show>
  )
}

// setup() runs once when OpenCode loads the plugin.
export default Plugin.define({
  id: "tab-explorer",
  setup(opencode) {
    opencode.ui.slot({
      // Prepend into the sidebar's content area; the host owns position and size.
      prepend: "sidebar.content",
      // Called as a component; its JSX is mounted into the slot.
      render: () => <SidebarTabs />,
    })
  },
})
