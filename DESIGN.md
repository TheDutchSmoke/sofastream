---
name: SofaStream tv
description: Teletekst page 101 for your own TV — a terminal menu that puts a Twitch channel on the Apple TV.
colors:
  ground: "#000000"
  text: "#ffffff"
  info: "#00ffff"
  value: "#ffff00"
  on-tv: "#00ff00"
  error: "#ff0000"
  band: "#0000ff"
  quiet: "#008787"
  dev: "#ff00ff"
typography:
  body:
    fontFamily: "the user's terminal font (monospace)"
    fontWeight: 400
  strong:
    fontFamily: "the user's terminal font (monospace)"
    fontWeight: 700
components:
  title-band:
    backgroundColor: "{colors.band}"
    textColor: "{colors.value}"
  title-band-danger:
    backgroundColor: "{colors.error}"
    textColor: "{colors.ground}"
  title-band-dev:
    backgroundColor: "{colors.dev}"
    textColor: "{colors.ground}"
  cursor-row:
    backgroundColor: "{colors.band}"
    textColor: "{colors.text}"
---

# Design System: SofaStream `tv`

Status: implemented on the `feature/tui-redesign` branch, 2026-11-19 (chosen by the owner from three directions;
the other two are summarised in `docs/design/directions-short.md`, all three shown in colour in
`docs/design/directions.html`). Where the code deviates from this text, the code and the notes below win:

- The input check on pages 201/202 runs in `app/tui-check.sh` (POSIX sh), not in `tui.py`: starting Python on
  every keystroke made pasting a link take seconds. `test_tui.py` checks that it agrees with `normalize_channel`.
  `tui.py --dialog` renders the band and instruction once.
- An empty notice row is a single space: fzf drops an empty header line, which shifted the list by one row.
- With `NO_COLOR` the two border lines are visible (fzf's `bw` palette draws them); labels and rows have no colour.

UI copy is Dutch and is quoted exactly. Everything else in this file is English, like `PRODUCT.md`.

## Overview

**Teletekst.** The menu is the text page of your own TV. A black page, the fixed Teletekst colours, a page
number and a running clock in the top row, a blue title band, dotted leaders to the numbers, and four coloured
buttons in the bottom row. Every view is a page with a number: 101 live, 102 offline, 103 status unknown, 200
manage, 300 settings. Typing the number goes there.

What the world lends, and nothing more: the palette, the density, the page row with its clock, and the page
numbers. Layout, navigation and controls stay those of a terminal list: type to search, Enter or click to
open, Esc to go back, a bottom row of buttons.

Rules that hold on every screen:

1. **No frame.** No border box, no margin, no padding. A window of 64 × 20 shows 11 channels (the old menu: 5).
2. **One job per colour.** White is a name, cyan is information about it, yellow is a number or
   a star, green is "this goes to the TV" or "it worked", red is an error or the way out, blue is a band.
   Nothing is coloured for decoration.
3. **State never rests on colour.** Every state has a glyph or a word (see the glyph table).
4. **Live is live, snapshots are dated.** The stream row is polled every 2 s. The Twitch list carries the time
   of its snapshot (`stand 21:04`). A status message starts with its time (`Op 21:04:31 · …`).
5. **Small motion only.** A clock, one glyph that alternates, one counter on the wait screen. See Motion.

The scene that decided dark: a laptop on the couch in the evening, next to a TV that is on. The page is black.

## Colors

One set of values for every terminal. All nine are xterm-256 cube colours, so the 256-colour code and the hex
value are the same colour: Terminal.app (no truecolor) and Ghostty or iTerm2 (truecolor) show the same page.
Always emit the 256-colour form (`38;5;N`, `48;5;N`). Do not emit 24-bit sequences.

| Role | 256 | Hex | Used for |
|---|---|---|---|
| ground | 16 | `#000000` | page background; the two invisible border lines |
| text | 231 | `#ffffff` | channel names, labels, instructions, typed query |
| info | 51 | `#00ffff` | game, duration, date, stream quality, prompt, `[Beheer]`, `[Instellingen]` |
| value | 226 | `#ffff00` | viewer counts, page numbers, stars, clock, band title, pointer, `[Favoriet]` |
| on-tv | 46 | `#00ff00` | `▶ NAAR TV`, the `▶` row marker, success notices, `[Verversen]`, confirm button |
| error | 196 | `#ff0000` | error notices, `[Sluiten]`, `[Terug]`, `[Annuleren]`, the band of the remove page |
| band | 21 | `#0000ff` | background of the title band and of the cursor row. Never a text colour |
| quiet | 30 | `#008787` | leaders, column heads, key hints, ghost text, info line, default hint, `■ GEEN STREAM` |
| dev | 201 | `#ff00ff` | development build only: band background, `DEV` chip, `◆` |

fzf `--color` (one string, used by every fzf call):

```
bg:16,fg:231,bg+:21,fg+:231:bold,hl:-1:underline,hl+:-1:underline,border:16,input-border:16,label:231,input-label:231,header:231,footer:231,prompt:51,query:231:regular,disabled:231:regular,ghost:30:regular,pointer:226,info:30,spinner:46,gutter:16
```

- `border:16` and `input-border:16` make the two border lines invisible (black on black). Only their labels show.
- `hl:-1:underline`: a search match keeps the colour of its column and is underlined.
- `bg+:21` with `--highlight-line`: the cursor row is a full-width blue bar. Row colours stay as they are.
- Row text, band, notices, labels and footer carry their own ANSI codes (see Components).

Measured contrast (WCAG) of every text/background pair that occurs:

| Pair | Ratio |
|---|---|
| text on ground | 21.0 |
| value on ground | 19.6 |
| info on ground | 16.8 |
| on-tv on ground | 15.3 |
| dev on ground · ground on dev | 6.7 |
| error on ground · ground on error | 5.25 |
| quiet on ground | 4.8 |
| text on band | 8.6 |
| value on band | 8.0 |
| info on band | 6.9 |
| on-tv on band | 6.3 |
| quiet on band (leader dots on the cursor row only) | 2.0, decorative |

Never put yellow or white on the red or magenta band (they reach only 2.9 to 4.0 there): those two bands take
black text.

`NO_COLOR` set: tv.zsh omits `--color` for the row renderers and passes `--color=bw` to fzf. Every state stays
readable through its glyph or word.

## Typography

The font is the user's terminal font. There are two weights and no other attributes.

- **Regular** for everything.
- **Bold** for: `SofaStream` in the page row, the band title, the channel that goes to the TV (stream row and
  its list row), the cursor row (`fg+:bold`), the PIN digits.
- **Underline** only for search matches. No italics, no dim attribute (quiet text has its own colour), no blink
  attribute (the alternating glyph is drawn by the status poll).

Case: band titles and the state words in the stream row are upper case (`LIVE NU`, `NAAR TV`). Column heads are
upper case. Everything else is sentence case.

Glyph set. None is a wide character (East Asian Width N or A), like the glyphs the menu already draws
(`▶ ★ ● ○ ▸ ■ ≡ ✓ ↓`). New compared with today: `▷ ◉ ↻ ◆ ✕ →`; check those once in Terminal.app with Menlo.
No emoji anywhere; `❌` in existing messages becomes `✕` (see Notice).

| Glyph | Code point | Meaning | Where |
|---|---|---|---|
| `▶` `▷` | U+25B6, U+25B7 | goes to the TV now (alternates, see Motion) | stream row; `▶` in the list row and in success notices |
| `■` | U+25A0 | no stream | stream row |
| `?` | U+003F | unknown | stream row, nav row, summary |
| `★` | U+2605 | favourite | list rows, summary, notices |
| `●` | U+25CF | live / on | summary; settings rows that are on or paired |
| `○` | U+25CB | offline / off / not chosen | summary, nav row, settings rows |
| `◉` | U+25C9 | the chosen Apple TV | settings |
| `↻` | U+21BB | scan | settings |
| `◆` | U+25C6 | development-only row | settings in `tv-dev` |
| `▸` | U+25B8 | cursor (fzf pointer) | list |
| `‹` | U+2039 | back | `Terug naar live` row |
| `≡` | U+2261 | manage | nav row |
| `+` `↓` | U+002B, U+2193 | add, import | the two first-run rows |
| `→` | U+2192 | "this becomes" | input check line |
| `✕` | U+2715 | error | notices, input check line |
| `✓` | U+2713 | done | existing notices (`✓ beta verwijderd.`) |
| `.` | U+002E | leader | between a label and its number |
| `…` | U+2026 | cut text | every truncation, and fzf `--ellipsis` |
| `·` `—` | U+00B7, U+2014 | separator, no value | labels, empty cells |

## Layout

### Regions

`W` is the width fzf reports (`$FZF_COLUMNS`). There are no side borders and no margin, so `W` is the terminal
width. `T = W − 2` is the text width: fzf keeps two columns on the left for the pointer and the
gutter, and indents header and footer by the same two columns. Every row tv.zsh, tui.py and settings.py
compose is `T` columns or shorter.

| Row | Region | Source | Updates |
|---|---|---|---|
| 1 | page row: page number, name, `DEV`, date, clock | fzf `--border=top` label | every second |
| 2 | stream row: what the Mac sends to the TV | fzf `--input-border=top` label | every 2 s |
| 3 | search row: prompt, query, info on the right | fzf prompt + `--info-command` | on input |
| 4 | title band: page title, summary | header line 1 | on reload |
| 5–6 | notice: result of the last action, or a hint (up to 4 rows for a long message) | header lines 2–3 | on reload |
| 7 | column heads | last header line | on reload |
| 8 … last−1 | list | items | on reload |
| last | button row | fzf `--footer` | per view |

Eight rows of chrome, ten while a long message is shown. The band is always on row 4, also on the screens
tv.zsh draws itself, so it does not jump.

Left edges: the pointer is in column 1; all text starts in column 3 (prompt strings start with two spaces).

### Width

| Terminal columns | Behaviour |
|---|---|
| < 50 | not designed for; fzf cuts rows with `…` |
| 50–59 | button row without key hints; channel column at most 14 |
| 60–71 | base layout; channel column at most 18 |
| 72–99 | channel column up to 22; the game column takes the rest |
| 100–119 | adds `TITEL` (stream title); game column fixed at 24 |
| 120–149 | adds `DUUR` (time live); game column fixed at 28 |
| ≥ 150 | game column 44; the title column takes everything that is left |

The breakpoints are on `T`: `T ≥ 98` adds the title, `T ≥ 118` adds the duration, `T ≥ 148` widens the game.

There is no maximum width and no side margin. fzf paints only its own window: cells in an fzf margin keep the
terminal's colour on some rows, so a centred page would get uneven edges.

Rows are rendered for the width fzf reports, not for a width remembered from the start: every reload command
passes `--columns "$FZF_COLUMNS"`, and `resize` triggers a cached reload.

### Height

No special cases. fzf scrolls the list. With `--cycle`, Up from the first row lands on the last row
(`Beheer & Apple TV`), so the three overview rows are one key away even when the list is long.

### Channel row

```
▶ ★  ohnepixel           Counter-Strike 2 ............  47.188
│ │  │                   │                              │
│ │  │                   │                              └ viewers, right-aligned in vw
│ │  │                   └ game, then a leader, gw wide
│ │  └ channel, cw wide, then two spaces
│ └ star column, then two spaces
└ on-tv column, then one space
```

- Prefix: on-tv (1) + space (1) + star (1) + two spaces = 5 columns. The same 5 columns hold the glyph of a nav
  row (`  ○  Offline …`), so `○  Offline`, `?  Status onbekend` and `≡  Beheer & Apple TV` keep their two spaces.
- `cw = clamp(longest visible login, 12, cap)`, `cap` = 14 (`T < 58`), 18 (`T < 70`), else 22.
- `vw = max(7, longest formatted viewer count)`.
- Base (`T < 98`): `gw = T − 5 − cw − 2 − 1 − vw`.
- With title (`98 ≤ T < 118`): `gw = 24`, two spaces, `tw = T − 5 − cw − 2 − 24 − 2 − 1 − vw`.
- With duration (`T ≥ 118`): `gw = 28` (44 from `T ≥ 148`), `tw = T − 5 − cw − 2 − gw − 2 − 1 − 8 − vw`; the
  duration is right-aligned in 6 columns and followed by two spaces.
- One space separates the last text column from the numbers.

Leader: the text is cut to its column with `…` if needed. If at least 4 columns remain, write one space and
then dots to the end of the column; otherwise pad with spaces. The leader belongs to the last text column
before the numbers: the game in the base layout, the title in the wide layouts.

Formats:

- Viewers: Dutch thousands separator, `47.188`; unknown `—`.
- Duration: under an hour `47m`, otherwise `2u14`.
- Game missing: `—`. Title missing or empty after cleaning: `—`.
- Title: `clean()` as today, then drop emoji and pictographs (Unicode categories So, Sk, Cs, Co, Cn, Mn, Me and
  everything from U+1F000 up) and collapse spaces. Titles are the only remote text that often carries emoji;
  removing them keeps the columns straight.
- Login longer than `cw`: cut with `…` (as today).

Nav row: prefix as above with the glyph in the star column, then the label with a leader, one space, and the
page number in 3 columns at the right edge: label width `T − 5 − 1 − 3`.

### Data the wide layout needs

`TITEL` and `DUUR` come from two extra fields in the existing Twitch query (checked against the live endpoint
on 2026-11-19): `stream { type viewersCount title createdAt game { name } }`. Store them in the cache as `title`
(string) and `started` (epoch seconds). Add a field to the status dict only when Twitch sent it, so a reply
without them yields the same dict as today. Duration = now − `started`, computed at render time.

## Shapes

- **No box.** `--border=top` and `--input-border=top` exist only to carry the two label rows; their lines are
  drawn black on black. `--footer-border=none`, no list border, no separator, no scrollbar, no gutter glyph.
- **One band per page.** A full-`T` bar on row 4. It is the only filled shape besides the cursor row.
- **The cursor row** is a full-width blue bar with the yellow `▸` in column 1.
- **Leaders** are the only texture. They sit between a label and its number and nowhere else.
- **Buttons** are words in square brackets, each in its own colour, in the bottom row. Brackets mean "you can
  click this"; nothing else on a page uses brackets.

## Components

### Page row (row 1)

```
P101  SofaStream                           do 19 nov  21:04:33
```

- Width `T`, placed with `--border-label-pos=3`.
- `P` + page number in text colour; two spaces; `SofaStream` bold; in the dev build one space and the chip
  ` DEV ` (bold black on magenta); padding; date in info colour; two spaces; clock in value colour.
- Date: Dutch, lower case, `do 19 nov` (day names `zo ma di wo do vr za`, months `jan feb mrt apr mei jun jul aug
  sep okt nov dec`, day of month without leading zero). Do not rely on the locale.
- If the date does not fit (`T − used < date + 12`), show the clock only.

Page numbers:

| Page | View | Band title |
|---|---|---|
| 101 | live | `LIVE NU` |
| 102 | offline | `OFFLINE` |
| 103 | status unknown | `STATUS ONBEKEND` |
| 200 | manage | `BEHEER & APPLE TV` |
| 201 | open another streamer | `ANDERE STREAMER OPENEN` |
| 202 | add favourite | `FAVORIET TOEVOEGEN` |
| 203 | remove channel | `KANAAL VERWIJDEREN` |
| 220 | pair | `APPLE TV KOPPELEN` |
| 300 | settings | `INSTELLINGEN` |
| rolling | wait screen | `EVEN GEDULD` |

204, 210, 211 and 212 are the numbers of the action rows on page 200; they have no page of their own.

Reference implementation (POSIX sh, tested with fzf 0.74.4; `date` format works with BSD and GNU date). Ship it
as `app/tui-clock.sh`:

```sh
#!/bin/sh
# Page row: page number, name, date and running clock.  usage: tui-clock.sh PAGE [dev]
# Reads FZF_COLUMNS (set by fzf) and TV_TUI_MOTION.
set -- "$1" "$2" $(date '+%w %e %m %H:%M:%S')
page=$1 dev=$2 wd=$3 day=$4 mon=$5 clock=$6
[ "$TV_TUI_MOTION" = 0 ] && clock='        '   # no running clock: eight spaces keep the date in place
set -- zo ma di wo do vr za; shift "$wd"; wd=$1
set -- jan feb mrt apr mei jun jul aug sep okt nov dec; shift $(( ${mon#0} - 1 )); mon=$1
date="$wd $day $mon"
width=$(( ${FZF_COLUMNS:-80} - 2 ))
used=$(( ${#page} + 3 + 10 ))
left=$(printf '\033[38;5;231mP%s  \033[1mSofaStream\033[0m' "$page")
if [ -n "$dev" ]; then left="$left $(printf '\033[1;38;5;16;48;5;201m DEV \033[0m')"; used=$(( used + 6 )); fi
if [ $(( width - used )) -ge $(( ${#date} + 12 )) ]; then
  pad=$(( width - used - ${#date} - 10 ))
  printf '%s%*s\033[38;5;51m%s  \033[38;5;226m%s\033[0m' "$left" "$pad" '' "$date" "$clock"
else
  pad=$(( width - used - 8 )); [ "$pad" -lt 1 ] && pad=1
  printf '%s%*s\033[38;5;226m%s\033[0m' "$left" "$pad" '' "$clock"
fi
```

### Stream row (row 2)

The live state of the Mac stream, as today (launchd job plus the last `Bron:` line of the relay log; the TV is
never contacted). New wording, because `ACTIEF` did not say what was active:

| State | Text | Colours |
|---|---|---|
| running | `▶ NAAR TV  ohnepixel · 1440p60 · 2K` | glyph and `NAAR TV` on-tv; channel bold text; ` · quality` info |
| running, channel unknown | `▶ NAAR TV  stream` | same |
| stopped | `■ GEEN STREAM` | quiet |
| unknown | `? STREAMSTATUS ONBEKEND` | value |

- Two spaces after `NAAR TV`. One trailing space after the label.
- If the label is wider than `T`: drop ` · 2K`/` · 4K`, then the quality. Never cut the channel name.
- "Naar tv" is what the Mac knows: it is sending this to the TV. It does not claim the TV shows a picture.
  README and PRODUCT.md quote the old `ACTIEF · kanaal · …` form and need the new one.

`stream-status.mjs` gets a mode `--tui` that prints fzf actions instead of a bare label:

```
change-input-label(<label>)
change-input-label(<label>)+reload(<$TV_TUI_RELOAD>)
```

The second form is printed when `TV_TUI_RELOAD` is set and the channel in the new label differs from the
channel in the previous label, which fzf hands to the command as `$FZF_INPUT_LABEL` (strip the ANSI codes,
match `NAAR TV\s+([a-z0-9_]{1,25})`). Channel and quality are already limited to `[a-z0-9_]` and `[\w.+-]`, so
the label cannot contain a `)`.

The `▶` in the list is derived from the same label: tui.py reads `$FZF_INPUT_LABEL` with the same pattern when
it renders rows. The first render has no label and no marker; the first poll (at `start`) sets the label, sees
a change and reloads. The list marker can therefore never disagree with the stream row.

The initial `--input-label` is a single space. tv.zsh may instead reuse the last label if the poll wrote it less
than 5 s ago, to avoid an empty row for a moment after every action.

### Search row (row 3)

```
  Zoek › kanaal, game of paginanummer               stand 21:04
  Zoek › cou                                           3 van 14
  Zoek › doesnotexist                Geen resultaten · Esc wist
```

- Prompt `  Zoek › ` (info colour). Ghost text `kanaal, game of paginanummer` (quiet) while the query is empty.
- Info, right-aligned, quiet, from `--info-command`:
  - query empty, channel views: `stand HH:MM`, the time of the Twitch snapshot. tui.py writes `HH:MM` to
    `$TV_CACHE_DIR/tui-stand` whenever it writes the status cache; the info command reads it with `read`.
    No file: print nothing.
  - query empty, other views: nothing.
  - query with matches: `3 van 14`.
  - query without matches: `Geen resultaten · Esc wist`. This replaces the header line that used to appear and
    push the list down.
- During Ctrl-R the prompt reads `  Ververst… › ` and fzf shows its spinner in the info position; the `load`
  event puts `  Zoek › ` back.

Info command (sh):

```sh
if [ -n "$FZF_QUERY" ]; then
  if [ "$FZF_MATCH_COUNT" = 0 ]; then printf 'Geen resultaten · Esc wist'
  else printf '%s van %s' "$FZF_MATCH_COUNT" "$FZF_TOTAL_COUNT"; fi
elif [ -n "$TV_TUI_STAND_FILE" ] && read -r stand < "$TV_TUI_STAND_FILE"; then printf 'stand %s' "$stand"; fi
```

Typing a page number that names a view (`101`, `102`, `103`, `200`, `300`) goes there at once, without Enter:
`change:transform` compares the whole query. Any other number is an ordinary search: on page 200, `211`
narrows the list to `Apple TV-stream stoppen … 211` and Enter runs it. Views open instantly because opening a
view is harmless; actions always need Enter.

### Title band (row 4)

```
 LIVE NU           ● 11 live  ○ 31 offline  ★ 3  ? 2 onbekend
```

`T` columns of band background. Left: one space, the title (bold, value colour), one space. Right: the summary
in text colour, one trailing space. The summary takes the first form that fits (`left + summary + 2 ≤ T`):

1. `● 11 live  ○ 31 offline  ★ 3 favorieten  ? 2 onbekend` (`★ 1 favoriet` for one)
2. `● 11 live  ○ 31 offline  ★ 3  ? 2 onbekend`
3. `● 11  ○ 31  ★ 3  ? 2`

The `?` part is omitted when nothing is unknown. Two spaces between parts.

Right side per page: 101–103 the summary; 200 `44 kanalen in tv  ★ 3 favorieten` (short form
`44 kanalen  ★ 3`); 203 `44 kanalen in tv`; 300 `Apple TV: Woonkamer` (short form the name only,
`Apple TV: nog niet gekozen` when none); 201, 202, 220: nothing; wait screen: elapsed seconds, `4 s`.

Variants:

| Variant | Background | Title and right side |
|---|---|---|
| default | band (21) | title value (226) bold; right side text (231) |
| danger, page 203 | error (196) | black (16), title bold |
| dev build, every page except 203 | dev (201) | black (16), title bold |

### Notice (rows 5–6)

Two rows. The second is empty when not needed, which leaves a blank line above the column heads. A message
that needs more room gets three or four rows, so an error is never cut before its advice.

- Every source line is wrapped at the last space before `T`. Short lines stay one row each, in order
  (unchanged; the status message has two).
- Rows = clamp(wrapped lines, 2, 4). If there are more than four, the fourth takes the rest and is cut with `…`.
- The number of rows is fixed for one fzf run, because `--header-lines` is. tv.zsh counts the rows that start
  with `header<TAB>` in the first render, passes that as `--header-lines`, and exports
  `TV_TUI_NOTICE_ROWS` (the count minus 2) so that every reload inside that run renders the same number.
  Without that variable tui.py sizes the area from the message.
- Kinds, set by the caller in `TV_TUI_NOTICE_KIND` (tv.zsh sets `error` when the command failed, `ok` when it
  succeeded, `info` for status text) or by tui.py itself for a star toggle (`ok`) and a refresh (`info`, or
  `error` when incomplete):

| Kind | Colour | Marker |
|---|---|---|
| hint (nothing happened yet) | quiet | none |
| ok | on-tv | the message's own `▶`, `★` or `✓` |
| info | text | none |
| error | error | `✕ ` is put in front of the first row unless the message already starts with `✕` |

- `❌` in a message is shown as `✕`. Change the source strings in tv.zsh as well (`❌ Wisselen mislukt.` →
  `✕ Wisselen mislukt.`); no test pins them.
- A message that starts with `▶`, `★` or `✓` is treated as `ok` when no kind is given.
- Without `--color` and without a kind, short lines are the message lines verbatim, as today.

Default hints (kind hint). Each fits 58 columns:

| View | Text |
|---|---|
| live | `Kies een kanaal om af te spelen op Apple TV.` |
| live, nobody live | `Er is nu niemand live. Ctrl-R ververst de Twitch-status.` |
| live, no channels at all | `Nog geen kanalen. Voeg er een toe of importeer je follows.` |
| offline | `Nu offline. Ctrl-F zet een ster aan of uit.` |
| status unknown | `Geen actuele Twitch-status. Ctrl-R probeert het opnieuw.` |
| manage | `Beheer je kanalen, de tv-stream en de instellingen.` |
| settings | `Een keuze geldt vanaf je volgende kanaalkeuze.` |

All existing result messages keep their wording. Two small changes:

- The status notice drops ` · PID 1234` in the menu (`tv status` on the command line keeps it), so that
  `Op 21:04:31 · Streamlink: actief · ohnepixel · 1440p60 · 2K.` fits 62 columns.
- The failed-refresh message becomes one line (a space where the line break was), so that it wraps cleanly.

Kinds of the messages tv.zsh writes itself:

| Message | Kind |
|---|---|
| `Invoer geannuleerd.` · `Instellingen gesloten. Je selectie geldt bij de volgende kanaalkeuze.` | info |
| `Geen kanaal geselecteerd. Kies een overzicht of Beheer & Apple TV.` · `Nog geen Streamlink-log.` | info |
| `Er zijn geen kanalen om te verwijderen.` | info |
| `sleeper is offline. Kies een live kanaal.` · `Koppelen niet afgerond. Je kunt dit later opnieuw kiezen.` | error |
| `Apple TV gekoppeld voor automatisch wakker maken en VLC openen.` | ok |
| `Op 21:04:31 · …` (status) | info |
| output of a command (`_tv_start`, `tv stop`, `tv fav import`, `tui.py --add/--remove`) | ok when it exits 0, else error |

Success, one row each (on-tv colour, the message brings its own glyph):

```
  ▶ Gewisseld naar ohnepixel op de tv.
  ★ kaicenat: favoriet aan.
  ✓ beta verwijderd.
```

An error of two rows, and the longest one the app has, four rows:

```
  ✕ eslcs start niet; het vorige kanaal blijft spelen. Bekijk
  Beheer → Streamlog.
```

```
  ✕ VLC is nog niet klaar. Staat de profielkeuze in beeld? Zet
  op Apple TV onder Instellingen → Profielen en accounts 'Kies
  profiel bij uitschakelen sluimerstand' uit. Controleer ook
  Afspelen op afstand in VLC.
```

A status snapshot (kind info, two source lines):

```
  Op 21:04:31 · Streamlink: actief · ohnepixel · 1440p60 · 2K.
  Apple TV: speelt ohnepixel in VLC.
```

### Column heads (row 7, after the notice)

Quiet colour, upper case, aligned with the columns below: `KANAAL`, `GAME`, `TITEL`, `DUUR` (right-aligned),
`KIJKERS` (right-aligned). Offline: `KANAAL`. Status unknown: `KANAAL`, `STATUS`. Manage: `ACTIE` and, at the
right edge, `PAGINA`. Settings: `INSTELLING`. Remove: `KANAAL`, `STATUS`.

### Live (101)

Order as today: stars first, then by viewers. Colours: `▶` on-tv; `★` value; channel text (bold when it goes
to the TV); game info; title text; leader quiet; duration info; viewers value. After the channels come the
overview rows: glyph quiet, label text, leader quiet, page number value.

64 columns:

```
  P101  SofaStream                           do 19 nov  21:04:33
  ▶ NAAR TV  ohnepixel · 1440p60 · 2K
  Zoek › kanaal, game of paginanummer               stand 21:04
   LIVE NU           ● 11 live  ○ 31 offline  ★ 3  ? 2 onbekend
  ▶ Gewisseld naar ohnepixel op de tv.

       KANAAL              GAME                          KIJKERS
  ▶ ★  ohnepixel           Counter-Strike 2 ............  47.188
▸   ★  lirik               Just Chatting ...............  15.230
    ★  gamesdonequick      The Legend of Zelda: Tears o…   8.120
       kaicenat            Grand Theft Auto VI .........  39.069
       eslcs               Counter-Strike 2 ............  31.404
       shroud              VALORANT ....................  12.871
       cohhcarnage         Baldur's Gate 3 .............   9.540
       summit1g            DayZ ........................   7.302
       thisisaverylongch…  Software and Game Development   1.204
       northernlion        Balatro .....................     987
       smallstreamer_nl    — ...........................      87
    ○  Offline · 31 kanalen ................................ 102
  [Sluiten] Esc  [Verversen] ^R  [Favoriet] ^F  [Beheer] 200
```

120 columns:

```
  P101  SofaStream                                                                                   do 19 nov  21:04:33
  ▶ NAAR TV  ohnepixel · 1440p60 · 2K
  Zoek › kanaal, game of paginanummer                                                                       stand 21:04
   LIVE NU                                                        ● 11 live  ○ 31 offline  ★ 3 favorieten  ? 2 onbekend
  ▶ Gewisseld naar ohnepixel op de tv.

       KANAAL                  GAME                          TITEL                                         DUUR  KIJKERS
  ▶ ★  ohnepixel               Counter-Strike 2              Major playoffs terugkijken en skins beoord…   2u14   47.188
▸   ★  lirik                   Just Chatting                 Rustig beginnen, daarna nieuwe releases ...    47m   15.230
    ★  gamesdonequick          The Legend of Zelda: Tears …  Awesome Games Done Quick: Any% zonder glit…   6u28    8.120
       kaicenat                Grand Theft Auto VI           GTA 6 voor het eerst, volledige playthrough   3u32   39.069
       eslcs                   Counter-Strike 2              IEM Rio: Vitality tegen Spirit, halve fina…   1u35   31.404
       shroud                  VALORANT                      Ranked tot Radiant ........................   1u01   12.871
       cohhcarnage             Baldur's Gate 3               Honour mode, poging 4 .....................   5u01    9.540
       summit1g                DayZ                          Verse wipe op Namalsk .....................   2u53    7.302
       thisisaverylongchanne…  Software and Game Developme…  Een roguelike bouwen in Rust, dag 212 .....    25m    1.204
       northernlion            Balatro                       Dagelijkse run en chat-vragen .............   1u58      987
       smallstreamer_nl        —                             — .........................................     9m       87
    ○  Offline · 31 kanalen ........................................................................................ 102
    ?  Status onbekend · 2 kanalen ................................................................................. 103
    ≡  Beheer & Apple TV ........................................................................................... 200




  [Sluiten] Esc  [Verversen] ^R  [Favoriet] ^F  [Beheer] 200
```

88 columns (the game column takes the room; no title yet):

```
  P101  SofaStream                                                   do 19 nov  21:04:33
  ▶ NAAR TV  ohnepixel · 1440p60 · 2K
  Zoek › kanaal, game of paginanummer                                       stand 21:04
   LIVE NU                        ● 11 live  ○ 31 offline  ★ 3 favorieten  ? 2 onbekend
  Kies een kanaal om af te spelen op Apple TV.

       KANAAL                  GAME                                              KIJKERS
  ▶ ★  ohnepixel               Counter-Strike 2 ................................  47.188
▸   ★  lirik                   Just Chatting ...................................  15.230
    ★  gamesdonequick          The Legend of Zelda: Tears of the Kingdom .......   8.120
       kaicenat                Grand Theft Auto VI .............................  39.069
       eslcs                   Counter-Strike 2 ................................  31.404
       shroud                  VALORANT ........................................  12.871
       cohhcarnage             Baldur's Gate 3 .................................   9.540
       summit1g                DayZ ............................................   7.302
       thisisaverylongchanne…  Software and Game Development ...................   1.204
       northernlion            Balatro .........................................     987
       smallstreamer_nl        — ...............................................      87
    ○  Offline · 31 kanalen ........................................................ 102
  [Sluiten] Esc  [Verversen] ^R  [Favoriet] ^F  [Beheer] 200
```

60 columns:

```
  P101  SofaStream                       do 19 nov  21:04:33
  ▶ NAAR TV  ohnepixel · 1440p60 · 2K
  Zoek › kanaal, game of paginanummer           stand 21:04
   LIVE NU       ● 11 live  ○ 31 offline  ★ 3  ? 2 onbekend
  Kies een kanaal om af te spelen op Apple TV.

       KANAAL              GAME                      KIJKERS
  ▶ ★  ohnepixel           Counter-Strike 2 ........  47.188
▸   ★  lirik               Just Chatting ...........  15.230
    ★  gamesdonequick      The Legend of Zelda: Tea…   8.120
       kaicenat            Grand Theft Auto VI .....  39.069
       eslcs               Counter-Strike 2 ........  31.404
       shroud              VALORANT ................  12.871
       cohhcarnage         Baldur's Gate 3 .........   9.540
       summit1g            DayZ ....................   7.302
  [Sluiten] Esc  [Verversen] ^R  [Favoriet] ^F  [Beheer] 200
```

Overview rows, exact text (count and plural as today, `1 kanaal`, `2 kanalen`):

```
    ○  Offline · 31 kanalen ................................ 102
    ?  Status onbekend · 2 kanalen ......................... 103
    ≡  Beheer & Apple TV ................................... 200
```

The `?` row appears only when a channel is unknown.

### Offline (102) and status unknown (103)

```
  P102  SofaStream                           do 19 nov  21:04:33
  ▶ NAAR TV  ohnepixel · 1440p60 · 2K
  Zoek › kanaal, game of paginanummer               stand 21:04
   OFFLINE           ● 11 live  ○ 31 offline  ★ 3  ? 2 onbekend
  Nu offline. Ctrl-F zet een ster aan of uit.

       KANAAL
▸      a_seagull
       admiralbahroo
       asmongold
       bobross
       caseoh_
       criticalrole
  [Terug] Esc  [Verversen] ^R  [Favoriet] ^F  [Beheer] 200
```

Offline rows are star and name only; "Offline" on every row said nothing. Choosing a row gives the existing
notice `sleeper is offline. Kies een live kanaal.` as an error.

```
  P103  SofaStream                           do 19 nov  21:04:33
  ▶ NAAR TV  ohnepixel · 1440p60 · 2K
  Zoek › kanaal, game of paginanummer               stand 21:04
   STATUS ONBEKEND   ● 11 live  ○ 31 offline  ★ 3  ? 2 onbekend
  ✕ Verversen niet volledig gelukt: 2 kanalen zonder actuele
  status. Bekijk Status onbekend of probeer later opnieuw.
       KANAAL           STATUS
▸      oldaccount_gone  Kanaal niet gevonden
       laggy_status     Verouderde status
    ‹  Terug naar live ..................................... 101

  [Terug] Esc  [Verversen] ^R  [Favoriet] ^F  [Beheer] 200
```

Status texts as today: `Verouderde status`, `Kanaal niet gevonden`, `Niet beschikbaar`, in info colour.
Both views end with `‹  Terug naar live … 101` (`‹` in info colour).

### Search

```
  P101  SofaStream                           do 19 nov  21:04:33
  ▶ NAAR TV  ohnepixel · 1440p60 · 2K
  Zoek › cou                                           3 van 14
   LIVE NU           ● 11 live  ○ 31 offline  ★ 3  ? 2 onbekend
  Kies een kanaal om af te spelen op Apple TV.

       KANAAL              GAME                          KIJKERS
▸ ▶ ★  ohnepixel           Counter-Strike 2 ............  47.188
       eslcs               Counter-Strike 2 ............  31.404
       cohhcarnage         Baldur's Gate 3 .............   9.540

  [Sluiten] Esc  [Verversen] ^R  [Favoriet] ^F  [Beheer] 200
```

```
  P101  SofaStream                           do 19 nov  21:04:33
  ▶ NAAR TV  ohnepixel · 1440p60 · 2K
  Zoek › doesnotexist                Geen resultaten · Esc wist
   LIVE NU           ● 11 live  ○ 31 offline  ★ 3  ? 2 onbekend
  Kies een kanaal om af te spelen op Apple TV.

       KANAAL              GAME                          KIJKERS


  [Sluiten] Esc  [Verversen] ^R  [Favoriet] ^F  [Beheer] 200
```

### Empty lists

Nobody live:

```
  P101  SofaStream                           do 19 nov  21:04:33
  ■ GEEN STREAM
  Zoek › kanaal, game of paginanummer               stand 21:04
   LIVE NU            ● 0 live  ○ 31 offline  ★ 3  ? 2 onbekend
  Er is nu niemand live. Ctrl-R ververst de Twitch-status.

       KANAAL        GAME                                KIJKERS
▸      Er zijn nu geen live kanalen.
    ○  Offline · 31 kanalen ................................ 102
    ?  Status onbekend · 2 kanalen ......................... 103
  [Sluiten] Esc  [Verversen] ^R  [Favoriet] ^F  [Beheer] 200
```

No channels at all. The first row stays the `noop` row; the two rows after it are the real actions
`action:add` and `action:import`, so a new user can start from here:

```
  P101  SofaStream                           do 19 nov  21:04:33
  ■ GEEN STREAM
  Zoek › kanaal, game of paginanummer
   LIVE NU                ● 0 live  ○ 0 offline  ★ 0 favorieten
  Nog geen kanalen. Voeg er een toe of importeer je follows.

       KANAAL        GAME                                KIJKERS
▸      Er zijn nu geen live kanalen.
    +  Favoriet toevoegen .................................. 202
    ↓  GUI-follows importeren .............................. 204
  [Sluiten] Esc  [Verversen] ^R  [Favoriet] ^F  [Beheer] 200
```

Offline or unknown view without rows: `Geen kanalen in dit overzicht.` (text colour, indented 5), then the
back row.

### Manage (200)

```
  P200  SofaStream                           do 19 nov  21:04:33
  ▶ NAAR TV  ohnepixel · 1440p60 · 2K
  Zoek › kanaal, game of paginanummer
   BEHEER & APPLE TV           44 kanalen in tv  ★ 3 favorieten
  Beheer je kanalen, de tv-stream en de instellingen.

       ACTIE                                              PAGINA
▸      Andere streamer openen .............................. 201
       Favoriet toevoegen .................................. 202
       Kanaal uit tv verwijderen ........................... 203
       GUI-follows importeren .............................. 204
       Apple TV-stream: status ............................. 210
       Apple TV-stream stoppen ............................. 211
       Streamlog bekijken .................................. 212
       Koppelen voor automatisch starten (pincode op tv) ... 220
       Instellingen · Apple TV kiezen ...................... 300
    ‹  Terug naar live ..................................... 101


  [Terug] Esc  [Instellingen] 300
```

- No pictograms. Labels start in the channel column. Keys and order as today.
- Labels are unchanged except one: `Automatisch starten koppelen (pincode op tv)` becomes
  `Koppelen voor automatisch starten (pincode op tv)`.
- The number is what you type to find the row. The groups show in the numbers: 20x channels, 21x the TV stream,
  220 pairing, 300 settings.
- Results appear in the notice rows, e.g. after `210`:

```
  P200  SofaStream                           do 19 nov  21:04:33
  ▶ NAAR TV  ohnepixel · 1440p60 · 2K
  Zoek › kanaal, game of paginanummer
   BEHEER & APPLE TV           44 kanalen in tv  ★ 3 favorieten
  Op 21:04:31 · Streamlink: actief · ohnepixel · 1440p60 · 2K.
  Apple TV: speelt ohnepixel in VLC.
       ACTIE                                              PAGINA
▸      Apple TV-stream: status ............................. 210
       Apple TV-stream stoppen ............................. 211
  [Terug] Esc  [Instellingen] 300
```

### Settings (300)

```
  P300  SofaStream                           do 19 nov  21:04:33
  ▶ NAAR TV  ohnepixel · 1440p60 · 2K
  Kies › typ om te zoeken
   INSTELLINGEN                             Apple TV: Woonkamer
  Een keuze geldt vanaf je volgende kanaalkeuze.

       INSTELLING
    ◉  Woonkamer · 192.168.1.20
    ○  Slaapkamer · 192.168.1.31
    ↻  Zoek Apple TVs op het netwerk
    ●  Afstandsbediening: koppeling opgeslagen
▸   ●  Automatisch wakker maken en VLC openen: aan
    ○  2K (1440p, H.265; Apple TV 4K): uit · geen Twitch-login

  [Terug] Esc
```

- Row text stays in the sentence form the tests read (`label: state · detail`); the state is repeated as a glyph
  on the left so that on/off can be scanned down one column.
- Glyph: `◉` chosen Apple TV, `○` other Apple TV, `↻` scan, `●` on or paired, `○` off or not paired; on-tv
  colour for `◉` and `●`, quiet for `○`, info for `↻`.
- Pair row: `Afstandsbediening: eenmalig koppelen nodig · pincode op tv` or
  `Afstandsbediening: koppeling opgeslagen · opnieuw koppelen`. The part after ` · ` is dropped when the row
  would be wider than `T`.
- 2K row as today; `, max 1080p` only when `T ≥ 72`.
- Rows are plain (no leaders): the values are inside the sentence.
- Without `--color` settings.py prints the same text without ANSI codes.

No Apple TV chosen yet:

```
  P300  SofaStream                           do 19 nov  21:04:33
  ▶ NAAR TV  ohnepixel · 1440p60 · 2K
  Kies › typ om te zoeken
   INSTELLINGEN                      Apple TV: nog niet gekozen
  0 Apple TVs gevonden. Kies het gewenste apparaat.

       INSTELLING
▸   ↻  Zoek Apple TVs op het netwerk
    ○  Afstandsbediening: eenmalig koppelen nodig
    ●  Automatisch wakker maken en VLC openen: aan
    ○  2K (1440p, H.265; Apple TV 4K): uit · geen Twitch-login
  [Terug] Esc
```

The result of `DEV · Versie en gescheiden testomgeving bekijken` (four lines, kind info):

```
   INSTELLINGEN                             Apple TV: Woonkamer
  SofaStream 0.2.1-dev.2 · development
  Instellingen: /Users/tristan/.config/sofastream-dev
  Streamlink-poort: 8766
  Bijwerken: brew update && brew upgrade sofastream@dev
       INSTELLING
```

### Text input (201, 202)

A disabled fzf (no list) at full height, so the page does not shrink to a strip.

```
  P201  SofaStream                           do 19 nov  21:04:33
  ▶ NAAR TV  ohnepixel · 1440p60 · 2K
  Kanaal › https://twitch.tv/Shroud?ref=share
   ANDERE STREAMER OPENEN
  Typ een Twitch-kanaalnaam of plak een Twitch-link.
  → twitch.tv/shroud


  [Annuleren] Esc  [Openen] Enter
```

```
  P202  SofaStream                           do 19 nov  21:04:33
  ▶ NAAR TV  ohnepixel · 1440p60 · 2K
  Kanaal › invalid name
   FAVORIET TOEVOEGEN
  Typ een Twitch-kanaalnaam of plak een Twitch-link.
  ✕ Geen geldige kanaalnaam of Twitch-link.


  [Annuleren] Esc  [Toevoegen] Enter
```

- Prompt `  Kanaal › `, ghost `naam of twitch.tv/…`.
- `--header`, three lines: the band; `Typ een Twitch-kanaalnaam of plak een Twitch-link.` (text); a check line.
- Check line, recomputed on every change with the same `normalize_channel` the action uses: empty query →
  empty; valid → `→ twitch.tv/` (quiet) + login (on-tv, bold); invalid →
  `✕ Geen geldige kanaalnaam of Twitch-link.` (error). Use the synchronous `transform-header`; the background
  variant drops intermediate keystrokes and can show a stale answer.
- Buttons: `[Annuleren] Esc` (error colour) and `[Openen] Enter` or `[Toevoegen] Enter` (on-tv colour). Both are
  clickable. Enter with an empty or blank query cancels, as today (`Invoer geannuleerd.`).

### Remove channel (203)

```
  P203  SofaStream                           do 19 nov  21:04:33
  ▶ NAAR TV  ohnepixel · 1440p60 · 2K
  Verwijder › be                                       8 van 44
   KANAAL VERWIJDEREN                          44 kanalen in tv
  Enter of klik verwijdert het kanaal en zijn ster uit tv.
  Je Twitch-follows veranderen niet.
       KANAAL                  STATUS
▸      admiralbahroo           offline
       bobross                 offline
       hasanabi                offline
       kitboga                 offline
       laggy_status            onbekend
  [Terug] Esc
```

- The red band marks the one page where Enter removes something.
- Rows: star, name, and the cached state (`live` in info colour, `offline`, `onbekend` in quiet). The first
  field is the bare login, as today.
- Prompt `  Verwijder › `, ghost `typ om te zoeken`. Button `[Terug] Esc`.
- The result is the existing `✓ beta verwijderd.` notice on page 200.

### Button row (last row)

One row. Each button is followed by its key in quiet colour. Two spaces between groups.

| View | Row |
|---|---|
| live | `[Sluiten] Esc  [Verversen] ^R  [Favoriet] ^F  [Beheer] 200` |
| offline, status unknown | `[Terug] Esc  [Verversen] ^R  [Favoriet] ^F  [Beheer] 200` |
| manage | `[Terug] Esc  [Instellingen] 300` |
| settings, remove | `[Terug] Esc` |
| text input | `[Annuleren] Esc  [Openen] Enter` / `[Annuleren] Esc  [Toevoegen] Enter` |

Colours in fixed Teletekst order: red `[Sluiten]`/`[Terug]`/`[Annuleren]`, green `[Verversen]`/confirm,
yellow `[Favoriet]`, cyan `[Beheer]`/`[Instellingen]`. Below 60 columns the key hints are left out.

Keys and mouse (unchanged unless marked new):

| Input | Action |
|---|---|
| Enter, Ctrl-J, click on a row | open the channel, overview or action |
| Ctrl-F, right-click on a row, `[Favoriet]` | toggle the star |
| Ctrl-R, `[Verversen]` | refresh the Twitch status |
| typing | search |
| Esc | clear the query; with an empty query go back or close |
| `[Sluiten]`, `[Terug]` | close or go back |
| `[Beheer]`, `[Instellingen]` | new: open page 200 or 300 |
| `101` `102` `103` `200` `300` typed as the whole query | new: open that page |
| Up on the first row | new (`--cycle`): jump to the last row |

### Wait screen

Drawn by tv.zsh between two fzf runs (the action runs in zsh, as today). Same page: rows 1, 2 and 4 are where
they are in the menu.

```
  P347  SofaStream                           do 19 nov  21:04:33
  ▷ BEZIG  shroud

   EVEN GEDULD                                              4 s
  Kanaal controleren en openen op Apple TV…

  Ctrl-C breekt af.
```

- Row 1: the page row, with the page number replaced by a counter in on-tv colour that rolls through the page
  numbers while you wait, like a Teletekst decoder searching for a page.
- Row 2: `▷ BEZIG` in value colour, then two spaces and the channel in bold when a channel is being started.
  The live stream state is not shown here because nothing polls it during a wait.
- Row 4: band `EVEN GEDULD`; on the right the elapsed whole seconds, `4 s`.
- Row 5: the message in text colour. Messages as today: `Kanaal controleren en openen op Apple TV…`,
  `GUI-follows importeren…`, `Stream- en tv-status ophalen…`, `Tv-stream stoppen…`,
  `Apple TVs zoeken op het lokale netwerk…`.
- Row 7: `Ctrl-C breekt af.` in quiet colour. Ctrl-C keeps its meaning.
- Paint the screen black first (`\e[48;5;16m\e[2J\e[H`) and reset attributes (`\e[0m`) when leaving. Do the
  same in `_tv_clear`, so the moment between two fzf runs is black and not the terminal's own colour.

### Pairing (220)

```
  P220  SofaStream                           do 19 nov  21:04:33
  ▷ BEZIG

   APPLE TV KOPPELEN
  Apple TV koppelen: er verschijnt zo een pincode op de tv.
  Ctrl-C annuleert.

  Pincode op de Apple TV (leeg = annuleren): 481▏
```

tv.zsh draws rows 1–4 and leaves the cursor on row 5; `tv pair` prints its two existing lines and reads the
PIN. remote.py indents those lines by two spaces when `TV_FULLSCREEN` is set, so they start in column 3.

### Stream log

Unchanged: `less -X` on the same screen with the prompt `q: terug  •  F: live volgen  •  :n: volgend log`.
It uses the terminal's own colours.

### Development build

```
  P101  SofaStream  DEV                      do 19 nov  21:04:33
  ▶ NAAR TV  ohnepixel · 1440p60 · 2K
  Zoek › kanaal, game of paginanummer               stand 21:04
   LIVE NU           ● 11 live  ○ 31 offline  ★ 3  ? 2 onbekend
  Kies een kanaal om af te spelen op Apple TV.

       KANAAL              GAME                          KIJKERS
  ▶ ★  ohnepixel           Counter-Strike 2 ............  47.188
▸   ★  lirik               Just Chatting ...............  15.230
    ★  gamesdonequick      The Legend of Zelda: Tears o…   8.120
  [Sluiten] Esc  [Verversen] ^R  [Favoriet] ^F  [Beheer] 200
```

```
  P300  SofaStream  DEV                      do 19 nov  21:04:33
  ▶ NAAR TV  ohnepixel · 1440p60 · 2K
  Kies › typ om te zoeken
   INSTELLINGEN                             Apple TV: Woonkamer
  Een keuze geldt vanaf je volgende kanaalkeuze.

       INSTELLING
    ◉  Woonkamer · 192.168.1.20
    ○  Slaapkamer · 192.168.1.31
    ↻  Zoek Apple TVs op het netwerk
    ●  Afstandsbediening: koppeling opgeslagen
▸   ●  Automatisch wakker maken en VLC openen: aan
    ○  2K (1440p, H.265; Apple TV 4K): uit · geen Twitch-login
    ◆  DEV · Versie en gescheiden testomgeving bekijken
    ◆  DEV · Ontbrekende voorkeuren uit stabiel overnemen

  [Terug] Esc
```

- The `DEV` chip after the name in the page row, on every screen including the wait screen.
- Every band is magenta with black text (the remove page stays red).
- `◆` in magenta before the two `DEV · …` settings rows.
- Magenta appears nowhere in the stable build. Both builds can drive the same TV, so the difference has to be
  visible at a glance; the word `DEV` carries it without colour.
- This replaces the two spellings in use today (`· DEV` and `@DEV`).

### Other stream states

```
  P101  SofaStream                           do 19 nov  21:04:33
  ■ GEEN STREAM
  Zoek › kanaal, game of paginanummer               stand 21:04
   LIVE NU           ● 11 live  ○ 31 offline  ★ 3  ? 2 onbekend
  Streamlink: gestopt.
  VLC: tv-stream gestopt.
```

```
  P101  SofaStream                           do 19 nov  21:04:33
  ? STREAMSTATUS ONBEKEND
  Zoek › kanaal, game of paginanummer               stand 21:04
   LIVE NU           ● 11 live  ○ 31 offline  ★ 3  ? 2 onbekend
```

## Do's and Don'ts

Do:

- Compose every row for `T` columns and let nothing wrap.
- Keep one meaning per colour and one glyph per state.
- Put results in the notice rows and state in the stream row. A notice is an event, the stream row is a fact.
- Date every snapshot.
- Keep labels that tests click or read exactly as they are (see Tests).

Don't:

- No border box, rounded corners, margin, padding, gutter glyph or scrollbar.
- No colour outside the nine, no 24-bit sequences, no gradients, no dim or italic.
- No emoji and no pictogram per menu row.
- No yellow or white text on the red or magenta band.
- No second band, no coloured background other than the band and the cursor row.
- Do not start, stop or change playback from a page number or a button that is not on the page: typed numbers
  open views; actions need Enter.
- Do not show a live-looking stream row on a screen that does not poll (the wait and pairing screens say
  `▷ BEZIG`).

## Motion

| What | How | How often | Purpose |
|---|---|---|---|
| Clock | `start,every(1):bg-transform-border-label` runs `tui-clock.sh` | 1 s | the page is alive; time while watching |
| Stream glyph | the poll draws `▶` when `floor(now / 2 s)` is even, `▷` when odd | every 2 s poll | the row is live; it freezes if the poll does |
| Stream row and list marker | `start,every(2):bg-transform` runs `stream-status.mjs --tui` | 2 s | truth about the TV stream |
| Refresh | prompt `  Ververst… › ` plus fzf's spinner; restored on `load` | while Ctrl-R runs | feedback without moving the layout |
| Wait screen | page counter +1 every 0.1 s from 100 to 899 and round; seconds; clock | while an action runs | shows that something is happening and for how long |

Nothing else moves. No entrance animation, no auto-refresh of the Twitch list: a list that reorders by itself
moves the row under the mouse, and with `--track` a reload blocks typing until it finishes. The dated
`stand HH:MM` tells how old the list is; Ctrl-R is one key.

`TV_TUI_MOTION=0` turns the motion off: the page row is drawn once (bind it to `start` only) and shows the date
without a clock, the stream glyph stays `▶`, the wait screen shows the page number of the view and no counters.
Use it in the PTY tests to keep screens stable.

The glyph alternates 0.25 times per second, far below any flashing threshold.

The wait animation is a zsh loop in the background that writes only to fixed cells (row 1 columns 3–6, the last
cells of rows 1 and 4). It must be stopped and reaped before the screen is cleared for the next fzf run and in
the INT/TERM/HUP trap. If that cannot be made safe next to the existing cancellation logic, ship the wait
screen without the loop.

## Engine

**fzf stays.** A custom TUI was weighed and rejected.

- Everything in this design runs in fzf 0.74.4. Each mechanism was tried against the real binary: labels on
  invisible borders, a ticking label, a background poll that changes a label and reloads the list when the
  channel changes, `$FZF_INPUT_LABEL` in reload commands, `--info-command`, `become` from a typed page number
  and from a footer click, a synchronous `transform-header` in the input dialog, reload on `resize`. The full
  invocation below was run end to end against stub commands.
- What a custom TUI would add: more than one list on a screen, per-cell animation, action screens that keep the
  list visible. None of these is needed here.
- What it would cost: mouse decoding (fzf 0.74.4 is pinned precisely because older versions misread mouse
  input), fuzzy search, resize, alternate-screen and cancellation handling, and a rewrite of the PTY test.
  "Keep previously working controls, import safeguards and cancellation behavior" is a rule of this repo.
- Limits accepted with fzf: actions still run between two fzf runs, so the list is replaced by the wait screen
  while a channel starts; the list is one column; a reload with `--track` blocks input until it finishes.

### fzf options

Run fzf with `SHELL=/bin/sh` in its environment so that binds and the info command run in POSIX sh, quickly and
the same everywhere. Shared by every call (`finder_style`):

```
--ansi --height=100% --layout=reverse
--border=top --border-label=' ' --border-label-pos=3
--input-border=top --input-label=' ' --input-label-pos=3
--no-separator --no-scrollbar --info=inline-right
--pointer='▸' --gutter=' ' --highlight-line --cycle --ellipsis='…'
--footer-border=none
--color='…'                               # the string under Colors
--bind='start,every(1):bg-transform-border-label:sh "$TV_APP_DIR/tui-clock.sh" '"$page${TV_DEV_MODE:+ dev}"
--bind='start,every(2):bg-transform:node "$TV_APP_DIR/stream-status.mjs" --tui'
```

Main menu (pages 101, 102, 103, 200), in addition:

```
--prompt='  Zoek › ' --ghost='kanaal, game of paginanummer'
--info-command="$info"                    # under Search row
--header-lines="$header_rows" --footer="$buttons"      # 4, or up to 6 with a long message
--no-sort --track --id-nth=1 --delimiter=$'\t' --with-nth=2.. --accept-nth=1
--bind='enter:wait+accept-non-empty,ctrl-j:wait+accept-non-empty,left-click:accept-non-empty,right-click:trigger(ctrl-f),esc:cancel'
--bind='click-footer:transform:case "$FZF_CLICK_FOOTER_WORD" in "[Favoriet]") echo "trigger(ctrl-f)";; "[Verversen]") echo "trigger(ctrl-r)";; "[Terug]"|"[Sluiten]") echo abort;; "[Beheer]") echo "become(echo view:manage)";; "[Instellingen]") echo "become(echo action:settings)";; esac'
--bind='change:transform:case "$FZF_QUERY" in 101) echo "become(echo view:live)";; 102) echo "become(echo view:offline)";; 103) echo "become(echo view:unknown)";; 200) echo "become(echo view:manage)";; 300) echo "become(echo action:settings)";; esac'
--bind='ctrl-r:change-prompt(  Ververst… › )+reload(python3 "$TV_APP_DIR/tui.py" --view "$TV_TUI_VIEW" --color --force --columns "$FZF_COLUMNS")'
--bind='ctrl-f:reload(python3 "$TV_APP_DIR/tui.py" --toggle-key {1} --render-after-action --view "$TV_TUI_VIEW" --color --columns "$FZF_COLUMNS")'
--bind='resize:reload(python3 "$TV_APP_DIR/tui.py" --render-after-action --view "$TV_TUI_VIEW" --color --columns "$FZF_COLUMNS")'
--bind='load:change-prompt(  Zoek › )'
```

- `TV_TUI_RELOAD` is exported with the `resize` command so the poll can reload the list. Leave it empty on
  pages without channel rows (200, 201, 202, 203, 300).
- `become(echo view:manage)` ends fzf with exit status 0 and that one line as output, so the existing `case`
  in the menu loop handles it. Leave out the entry for the page that is already open.
- The old binds `zero:change-header(…)`, `change:change-header()` and `load:change-header()` go away.
- `--columns` now means the width fzf reports; rows are `--columns − 2` wide. `TV_TUI_COLUMNS` is only the
  value for the first render (`${COLUMNS:-100}`).

Text input: `finder_style` plus `--disabled --no-info --prompt='  Kanaal › ' --ghost='naam of twitch.tv/…'`,
`--header` with the three lines, `--footer`,
`--bind='change:transform-header(python3 "$TV_APP_DIR/tui.py" --dialog other --columns "$FZF_COLUMNS" {q})'`,
`--bind='enter:accept-or-print-query,ctrl-j:accept-or-print-query,esc:abort'` and a `click-footer` bind that
maps `[Annuleren]` to `abort` and `[Openen]`/`[Toevoegen]` to `accept-or-print-query`. Input stays `</dev/null`.

Remove: main-menu options without `--track --id-nth`, the page-number bind and the Ctrl-R/Ctrl-F binds; rows
from `tui.py --view remove --color --columns …` (cache only, no network).

Settings: `finder_style` plus `--prompt='  Kies › ' --ghost='typ om te zoeken'` and `--header-lines` counted
from the output, rows from `settings.py menu --color --columns …` with the notice in
`TV_TUI_NOTICE`/`TV_TUI_NOTICE_KIND` (it replaces `--header="$notice"` and the two header rows settings.py
prints today). The four lines of the `dev-info` result fit because the notice grows to four rows. Add `--ansi`,
which this call lacks today.

### Where things change

| File | Change |
|---|---|
| `app/tv.zsh` | `finder_style`, binds, footer per view, `SHELL=/bin/sh`, notice kind and rows, `_tv_progress` as a page, pairing page, black `_tv_clear`, `\e[0m` on leave |
| `app/tui.py` | row layout, band, notice wrapping and kinds, hints, `▶` from `$FZF_INPUT_LABEL`, `title`/`started`, `tui-stand`, `--view remove`, `--dialog` |
| `app/settings.py` | `menu --color --columns`: band, notice, column head, glyph column, shorter pair row |
| `app/stream-status.mjs` | `--tui`: coloured label, alternating glyph, reload on channel change |
| `app/tui-clock.sh` | new |
| `app/remote.py` | two spaces of indent for the pairing lines when `TV_FULLSCREEN` is set |
| `README.md`, `PRODUCT.md` | the stream row wording, the new keys |

The band, notice and leader helpers are needed by both tui.py and settings.py; put them in one small module.

Environment variables between tv.zsh, fzf's child commands and the renderers:

| Variable | Set by | Read by | Meaning |
|---|---|---|---|
| `TV_TUI_VIEW` | tv.zsh (exists) | tui.py | `live`, `offline`, `unknown`, `manage` |
| `TV_TUI_NOTICE` | tv.zsh (exists) | tui.py, settings.py | message of the last action |
| `TV_TUI_NOTICE_KIND` | tv.zsh | tui.py, settings.py | `ok`, `error`, `info`, or empty for a hint |
| `TV_TUI_NOTICE_ROWS` | tv.zsh, after the first render | tui.py | notice rows for this fzf run (2–4) |
| `TV_TUI_RELOAD` | tv.zsh, channel views only | stream-status.mjs | cached-render command for a reload |
| `TV_TUI_STAND_FILE` | tv.zsh, channel views only | info command | path of `tui-stand` |
| `TV_TUI_MOTION` | the user or a test | tv.zsh, tui-clock.sh, stream-status.mjs | `0` turns motion off |
| `FZF_COLUMNS`, `FZF_INPUT_LABEL`, `FZF_QUERY`, `FZF_MATCH_COUNT`, `FZF_TOTAL_COUNT`, `FZF_CLICK_FOOTER_WORD` | fzf | the commands above | see the fzf manual |

## Tests

Behaviour the tests pin and this design keeps: every label the interaction test clicks or reads (`Andere
streamer openen`, `Favoriet toevoegen`, `Kanaal uit tv verwijderen`, `GUI-follows importeren`, `Apple TV-stream:
status`, `Apple TV-stream stoppen`, `Streamlog bekijken`, `Terug naar live`, `Offline`, `?  Status onbekend`,
`Beheer & Apple TV`, `[Favoriet]`, `[Verversen]`, `[Terug]`, `[Sluiten]`, `Kanaal ›`, `KANAAL VERWIJDEREN`,
`BEHEER & APPLE TV`, `Geen resultaten`, `Verouderde status`, `Er zijn nu geen live kanalen.`), all result
messages, four header rows for a short message with its two lines verbatim in rows 2 and 3, one tab per row, the
row keys, the order of channels, and the plain settings strings (`nog niet gekozen`, `eenmalig koppelen nodig`,
`koppeling opgeslagen`, `2K (1440p, H.265; Apple TV 4K): uit · geen Twitch-login`, `: aan · Twitch-login
gevonden`, `: uit · login uit je Streamlink-config`).

Tests that have to change:

1. `app/test_interaction.py`, `Screen.locate`: it only accepts lines that start with `│` and prefers lines with
   `▸` or `▌`. There is no side border and no gutter glyph any more. Search the screen from the bottom row up
   and take the first line that contains the text; that finds the button row and list rows before a notice
   that repeats a name.
2. `app/test_interaction.py`: the replacement of `node "$TV_APP_DIR/stream-status.mjs" --label` must follow the
   new command (`--tui`) and print an action, e.g. `printf "change-input-label(Test: lokale streamstatus)"`.
   Set `TV_TUI_MOTION=0` in the test environment.
3. `app/test_tui.py`, `test_alignment_and_remote_text_are_safe`: the bound `display_width(...) <= 68` encoded the
   12 columns the old frame took at `columns=80`. Rows are now `columns − 2` wide: the bound becomes 78.

Worth adding: a row is never wider than `columns − 2` at 60, 64, 100 and 120 columns; a title with emoji and a
tab yields one row without them; a status reply without `title` gives the same dict as before; the marker
appears only for the channel named in `FZF_INPUT_LABEL`; typing `102` opens the offline page; `[Beheer]` opens
page 200.

Not tested here: `tui-clock.sh` and the binds ran under dash and GNU date on Linux. The `date` format used is
the same for BSD date, but run it once on macOS.
