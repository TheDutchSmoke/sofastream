# Product

<!-- impeccable:product-schema 1 -->

## Platform

Terminal (macOS). Not one of web/ios/android: the interface is a full-screen text UI in the user's own
terminal emulator, drawn by fzf with rows rendered by `app/tui.py` and `app/settings.py`, driven by `app/tv.zsh`.

## Users

Primarily the author (Tristan), watching Twitch on an Apple TV. Others may install it from the public Homebrew
tap, but the design is tuned to the author's own use. Used both from a laptop on the couch (small or half-size
terminal window: open, pick a channel, close) and from a large terminal window at a desk; both must work well.

## Product Purpose

Pick a Twitch channel in a terminal on the Mac and have it play on the Apple TV in VLC, without touching the TV
remote. Streamlink filters ads on the Mac; a relay keeps one stream open to VLC so switching channels happens inside
the same stream. Success: from opening `tv` to the channel playing on the TV in a few keystrokes or one click, and
always knowing what the TV is playing right now.

## Positioning

A terminal remote for the living-room TV: the Mac does the Twitch work (ad filtering, 2K/H.265 with the user's
login, seamless channel switching in one stream), the Apple TV only plays. No browser, no TV-side app beyond VLC.

## Operating Context

- Opened often, for seconds at a time. The common path is: open, see who is live (stars first, then by viewers),
  pick, close. The video keeps playing after the menu closes.
- Live status of the Mac stream is shown continuously in the second row (e.g. `▶ NAAR TV  kanaal · 1440p60 · 2K`),
  refreshed every 2 seconds without contacting the TV.
- Mouse (click, right-click) and keyboard (Enter, Ctrl-F, Ctrl-R, Esc, type-to-search) are both used.
- Stable (`tv`) and development (`tv-dev` / `sofastream@dev`) installs run side by side; dev is marked as DEV.

## Capabilities and Constraints

Views and actions that must remain available:

- Live list: favorites ("sterren") first, then by viewer count; columns channel, game, viewers. Summary of live /
  offline / starred / unknown counts. One- or two-line notice area for results of the last action.
- Offline view and "status unknown" view (stale or missing Twitch data), each with a way back.
- Toggle star (Ctrl-F, right-click, footer button); refresh Twitch status (Ctrl-R, footer button); search by typing;
  Esc clears search, goes back, or closes.
- Manage ("Beheer"): open another streamer by name or Twitch link, add favorite, remove channel, import follows from
  the Streamlink Twitch GUI, stream status, stop the TV stream, view the stream log (in `less`), pair for auto-start
  (PIN shown on the TV), settings.
- Settings: choose/scan Apple TVs, pairing state, auto-start (wake + open VLC) on/off, 2K (1440p, H.265, needs Apple
  TV 4K and a Twitch login) on/off with login state, DEV section in the dev build.
- Progress screens while checking/starting a channel ("Kanaal controleren en openen op Apple TV…").
- UI copy is Dutch.

Technical constraints:

- Runs in any modern macOS terminal (Terminal.app, iTerm2, Ghostty, …); must survive narrow windows (~60 columns)
  and large ones. Uses the alternate screen and restores the terminal on exit.
- fzf 0.74.4+ is the current engine. The redesign may replace or keep it; keeping working controls, import
  safeguards and cancellation behavior is required (see `AGENTS.md`).
- Remote text (channel names, game titles) is sanitized to one row without control sequences.
- CI runs on macOS with fixtures; the design must never contact a real Apple TV.

## Brand Commitments

Name: SofaStream (`tv` command). No logo or confirmed visual identity. The current purple-on-near-black fzf
theme is an incumbent look, not a commitment.

## Evidence on Hand

Real usage only; no testimonials, screenshots or metrics exist. Do not fabricate any.

## Product Principles

1. The fastest path is the default path: open, pick a live channel, done.
2. Always tell the truth about what the TV is doing now; snapshots are dated, live state is live.
3. Never break playback from the menu: closing the UI leaves the stream alone; stop is explicit.
4. Degrade quietly: if Twitch or the network fails, the menu stays usable and marks data as stale.

## Accessibility & Inclusion

Must not rely on color alone for state (live/offline/star/stale); full keyboard and mouse use. The UI paints its own
black background (decided in DESIGN.md, 2026-11-19).
