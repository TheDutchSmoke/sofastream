---
version: 1
slug: "app-tv-zsh"
primary_target: "app/tv.zsh"
related_targets: ["app/tui.py","app/settings.py"]
---

# Surface brief: the `tv` menu (app/tv.zsh, app/tui.py, app/settings.py)

Scope: the full-screen terminal menu and the screens it opens. Mode: Operate.

Audience and job: the owner, on the couch with a laptop in a small window or at a desk in a large one. Open,
see who is live, pick, close. Always know what the Mac is sending to the TV.

Constraints: fzf 0.74.4+ stays the engine; Dutch copy; 60 columns to very wide; 256 colours; state never on
colour alone; controls, cancellation and the labels the PTY test reads stay as they are.

Chosen direction: Teletekst (recommended by the designer and chosen by the owner on 2026-11-19).
Alternatives shown: "Op zender" (assigned by the roll) and "Bank". See docs/design/directions.html.
Memorable moment: the page row with its running clock, and typing 102 to be on the offline page.

Resolved 2026-11-19: the owner chose Teletekst ("not the prettiest, but the most readable"). The wait-screen
animation ships: it stops before every redraw and in the exit trap, and ends itself when the menu shell is gone
(checked in a PTY, including Ctrl-C).

## Direction contract

THESIS: The menu is page 101 of your own TV. It refuses the framed, rounded, dark-with-one-accent fzf picker.

OWN-WORLD: Black page. White names, cyan information, yellow numbers and stars, green for "goes to the TV",
red for errors and the way out, one blue band per page, teal dotted leaders. No box. Buttons are bracketed
words in red, green, yellow, cyan order in the last row.

STORY: The user sees what goes to the TV (row 2), who is live (list, stars first), and when that list was
taken (`stand 21:04`). They press Enter on a row. Other pages are a number away.

FIRST VIEWPORT: Row 1 page number, SofaStream, date, running clock. Row 2 stream state. Row 3 search. Row 4
blue band `LIVE NU` with the counts. Rows 5–6 notice. Row 7 column heads. Then channels: marker, star, name,
game with a leader, viewers right-aligned; the three overview rows with page numbers. Last row: the four
buttons. Primary action: Enter or click on a channel row.

FORM: own grounded candidate 1 of 7 (Teletekst), chosen by the designer over the rolled assignment
(candidate 4, studio tally); seed:7ffcaa27d7cf691e.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict,
DESIGN.md, and every shipping raster carrying its provenance
