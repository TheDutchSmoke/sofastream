"""Teletekst page parts shared by tui.py and settings.py (see DESIGN.md).

Every row is composed for a text width T = terminal columns - 2: fzf keeps two
columns for the pointer and indents header and footer by the same two.
"""

import unicodedata

# xterm-256 cube colours: the 256-colour code and the hex value are the same colour,
# so Terminal.app (no truecolor) shows exactly what Ghostty or iTerm2 show.
BLACK, WHITE, CYAN, YELLOW, GREEN, RED, BLUE, TEAL, MAGENTA = 16, 231, 51, 226, 46, 196, 21, 30, 201
RESET = "\033[0m"


def clean(value):
    """Keep remote text on one terminal row, with no control sequences."""
    text = "".join(c if not unicodedata.category(c).startswith("C") else " "
                   for c in str(value))
    return " ".join(text.split())


def clean_title(value):
    """Stream titles often carry emoji; drop pictographs so the columns stay straight."""
    text = "".join(" " if unicodedata.category(c) in ("So", "Cs", "Co", "Cn", "Mn", "Me")
                   or ord(c) >= 0x1F000 else c for c in clean(value))
    return " ".join(text.split())


def display_width(text):
    return sum(0 if unicodedata.combining(c) else
               2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def fit(text, width, right=False):
    width = max(0, width)
    text = clean(text)
    if display_width(text) > width:
        clipped = ""
        for char in text:
            if display_width(clipped + char) > width - 1:
                break
            clipped += char
        text = clipped + "…" if width else ""
    padding = " " * max(0, width - display_width(text))
    return padding + text if right else text + padding


def sgr(fg=None, bg=None, bold=False):
    codes = (["1"] if bold else []) + ([f"38;5;{fg}"] if fg is not None else []) \
        + ([f"48;5;{bg}"] if bg is not None else [])
    return f"\033[{';'.join(codes)}m"


def paint(text, fg, color=True, bold=False, bg=None):
    return f"{sgr(fg, bg, bold)}{text}{RESET}" if color and text else text


def number(value):
    return f"{value:,}".replace(",", ".") if type(value) is int and value >= 0 else "—"


def uptime(minutes):
    if type(minutes) is not int or minutes < 0:
        return "—"
    return f"{minutes}m" if minutes < 60 else f"{minutes // 60}u{minutes % 60:02d}"


def plural(count):
    return "kanaal" if count == 1 else "kanalen"


def leaders(text, width, fg, color=True):
    """Text, then a dotted leader to the end of its column (a Teletekst index)."""
    text = fit(text, width).rstrip()
    rest = width - display_width(text)
    if rest >= 4:
        return paint(text, fg, color) + " " + paint("." * (rest - 1), TEAL, color)
    return paint(text, fg, color) + " " * rest


def nav_row(glyph, label, page, width, color=True, glyph_fg=TEAL):
    """'  ○  Offline · 3 kanalen ......... 102': glyph in the star column, page at the right edge."""
    return ("  " + paint(glyph, glyph_fg, color) + "  " + leaders(label, width - 9, WHITE, color)
            + " " + paint(fit(str(page), 3, right=True), YELLOW, color))


def band(title, right, width, color=True, danger=False, dev=False):
    """The full-width title band. `right` is a list of candidates, longest first."""
    candidates = [right] if isinstance(right, str) else list(right)
    left = f" {title} "
    right_text = next((c for c in candidates if c and display_width(left) + display_width(c) + 2 <= width), "")
    gap = max(0, width - display_width(left) - display_width(right_text) - (1 if right_text else 0))
    if not color:
        return (left + " " * gap + right_text).rstrip()
    background = RED if danger else MAGENTA if dev else BLUE
    title_fg = BLACK if danger or dev else YELLOW
    right_fg = BLACK if danger or dev else WHITE
    return (sgr(title_fg, background, True) + left + RESET + sgr(right_fg, background)
            + " " * gap + right_text + (" " if right_text else "") + RESET)


def wrap(line, width):
    """Word-wrap one line at the last space before `width` display columns."""
    rows, current = [], ""
    for word in line.split(" "):
        candidate = f"{current} {word}" if current else word
        if display_width(candidate) <= width or not current:
            current = candidate
        else:
            rows.append(current)
            current = word
    rows.append(current)
    return rows


OK_GLYPHS = ("▶", "★", "✓")


def notice_rows(notice, kind, width, color=True, count=None, hint=False):
    """Two to four rows for the result of the last action (DESIGN.md, Notice).

    kind: 'ok', 'error', 'info' or None. `hint` marks a default hint (quiet colour).
    `count` fixes the number of rows for one fzf run (--header-lines is fixed).
    """
    lines = [line.replace("❌", "✕").strip() for line in notice.splitlines()] or [""]
    if kind is None and not hint:
        kind = "ok" if lines[0].startswith(OK_GLYPHS) else "info"
    if kind == "error" and lines[0] and not lines[0].startswith("✕"):
        lines[0] = "✕ " + lines[0]
    lines = [row for line in lines for row in wrap(line, width)]
    count = count or min(4, max(2, len(lines)))
    if len(lines) > count:
        lines = lines[:count - 1] + [" ".join(lines[count - 1:])]
    lines = (lines + [""] * count)[:count]
    fg = TEAL if hint else {"ok": GREEN, "error": RED}.get(kind, WHITE)
    # An empty header line would collapse in fzf and shift the list; keep one space.
    return [paint(fit(line, width).rstrip(), fg, color) or " " for line in lines]


def column_head(text, color=True):
    return paint(text.rstrip(), TEAL, color)
