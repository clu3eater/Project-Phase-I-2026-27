"""Automatable parts of the PRD Part 4 §15 verification checklist.

The HMI standard is a compliance document: a rule marked [SHALL] is not a style
preference. But a compliance document nobody can run is a document that drifts,
and this one did -- a first pass found **78 violations of §5.1** (minimum text
size) spread across every file in the console, including the design token
`--size-label: 13px`, whose comment reasoned that labels were exempt when §5.1
names "Labels / units ... 16 px [SHALL]" explicitly.

§15 marks several checks "automated". These are those:

  TYPE TEST             s5.1  no text below 16 px; alert legends >= 21 px;
                              primary numeric readouts >= 30 px.
  RESERVED-COLOUR TEST  s3.3a red and amber are reserved for WARNING and
                              CAUTION. They may not be used for a focus ring,
                              a link, or a primary button.
  ANTI-PATTERN TEST     s14   the explicitly forbidden list -- gradients,
                              glassmorphism, emoji status, auto-dismissing
                              toasts, count-up animation, shimmer loaders.

The checks that need a running console and a human eye -- MONOCHROME, FLASH,
MASTER RESET, 3-SECOND, STALE, INVALID, OVERFLOW, ROLE -- are listed at the end
as a reminder rather than silently omitted, because a checklist that quietly
drops its hard half reads as a pass it has not earned.

    python scripts/hmi_check.py

Exits non-zero on any [SHALL] violation.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONSOLE = REPO / "layer5_viz" / "gcs_console" / "src"

MIN_TEXT_PX = 16      # §5.1 [SHALL]
MIN_ALERT_PX = 21     # §5.1 alert legends [SHALL]
MIN_READOUT_PX = 30   # §5.1 primary numeric readouts [SHALL]

# §3.3a: reserved for WARNING and CAUTION only.
RESERVED_COLOURS = {
    "--alert-warn": "red (WARNING)",
    "--alert-caut": "amber (CAUTION)",
    "--alert-caut-hi": "amber escalated (CAUTION)",
}

# Properties that must never carry a reserved alert colour (s3.3a).
RESERVED_MISUSE = re.compile(
    r"(outline|outlineColor|borderColor\s*:\s*[^,;]*focus|textDecoration)"
    r"[^;\n]*var\(--alert-(warn|caut)",
    re.IGNORECASE,
)

ANTI_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("gradient header/hero", re.compile(r"linear-gradient|radial-gradient"),
     "s14: no gradient headers or hero panels"),
    ("glassmorphism / blur", re.compile(r"backdrop-?[Ff]ilter|blur\("),
     "s14: no glassmorphism or blur backdrops"),
    ("drop shadow depth theatre", re.compile(r"boxShadow|box-shadow"),
     "s14: no drop shadows used for depth"),
    ("emoji", re.compile(
        "[\U0001F300-\U0001FAFF☀-➿️]"),
     "s14: no emoji as status icons"),
    ("auto-dismiss toast", re.compile(r"setTimeout[^;]*(dismiss|toast|hide)",
                                      re.IGNORECASE),
     "s14 / 411F 5.2.5.5: alerts must not self-clear"),
    ("count-up animation", re.compile(r"requestAnimationFrame[^;]*(count|odom)",
                                      re.IGNORECASE),
     "s14 / P2: no odometer animation on values"),
    ("shimmer loader", re.compile(r"shimmer|skeleton", re.IGNORECASE),
     "s14 / s8.1b: use a static ACQUIRING state"),
]


def _sources() -> list[Path]:
    return sorted(
        p for p in CONSOLE.rglob("*")
        if p.suffix in {".tsx", ".ts", ".css"} and p.is_file()
    )


def check_type() -> list[str]:
    """s5.1 -- no text below 16 px anywhere."""
    bad: list[str] = []
    px = re.compile(r"fontSize:\s*(\d+)")
    css_px = re.compile(r"font-size:\s*(\d+)px")
    tok = re.compile(r"(--size-[a-z]+):\s*(\d+)px")

    for f in _sources():
        text = f.read_text(encoding="utf-8", errors="ignore")
        rel = f.relative_to(REPO).as_posix()
        for line_no, line in enumerate(text.splitlines(), 1):
            for m in list(px.finditer(line)) + list(css_px.finditer(line)):
                size = int(m.group(1))
                if size < MIN_TEXT_PX:
                    bad.append(f"{rel}:{line_no}  {size}px  (s5.1 requires >= "
                               f"{MIN_TEXT_PX}px) - {line.strip()[:64]}")
            for m in tok.finditer(line):
                if int(m.group(2)) < MIN_TEXT_PX:
                    bad.append(f"{rel}:{line_no}  token {m.group(1)} = "
                               f"{m.group(2)}px (s5.1 requires >= "
                               f"{MIN_TEXT_PX}px)")
    return bad


def check_alert_and_readout_sizes() -> list[str]:
    """s5.1 -- alert legends >= 21 px, primary numeric readouts >= 30 px.

    Both minimums were declared at the top of this file and never checked, so
    the script could report COMPLIANT over a 16 px alert legend and a 27 px
    readout (HMI-05). A static check has to infer the role from the code: a
    font size within six lines above a rendered alert legend belongs to the
    legend, and a numeric-font size of 24 px or more is a primary readout
    (smaller numeric text is a label or a clock, governed by s5.1's 16 px).
    """
    bad: list[str] = []
    px = re.compile(r"fontSize:\s*(\d+)")
    for f in _sources():
        if f.suffix != ".tsx":
            continue
        lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        rel = f.relative_to(REPO).as_posix()
        for i, line in enumerate(lines):
            if "{a.legend}" in line or "{alert.legend}" in line:
                for j in range(max(0, i - 6), i + 1):
                    for m in px.finditer(lines[j]):
                        if int(m.group(1)) < MIN_ALERT_PX:
                            bad.append(f"{rel}:{j + 1}  alert legend {m.group(1)}px "
                                       f"(s5.1 requires >= {MIN_ALERT_PX}px)")
            if "var(--font-num)" in line:
                for m in px.finditer(line):
                    size = int(m.group(1))
                    if 24 <= size < MIN_READOUT_PX:
                        bad.append(f"{rel}:{i + 1}  primary readout {size}px "
                                   f"(s5.1 requires >= {MIN_READOUT_PX}px)")
    return sorted(set(bad))


def check_reserved_colours() -> list[str]:
    """s3.3a -- red and amber mean WARNING and CAUTION, nothing else."""
    bad: list[str] = []
    for f in _sources():
        if f.name == "tokens.css":
            continue  # where the colours are legitimately defined
        text = f.read_text(encoding="utf-8", errors="ignore")
        rel = f.relative_to(REPO).as_posix()
        for line_no, line in enumerate(text.splitlines(), 1):
            if RESERVED_MISUSE.search(line):
                bad.append(f"{rel}:{line_no}  reserved alert colour on a "
                           f"focus ring, link or decoration (s3.3a) - "
                           f"{line.strip()[:64]}")
    return bad


def _strip_comments(text: str) -> str:
    """Blank out comments, KEEPING the line count so numbers stay honest.

    THE TRAP THIS CLOSES, WHICH HAS NOW CAUGHT FOUR CHECKS IN THIS FILE.
    Every rule here is explained in a comment beside the code that obeys it,
    and an explanation necessarily NAMES the thing it is about. So the prose
    "drawn as an SVG pattern rather than a repeating-linear-gradient" trips a
    scan for `repeating-linear-gradient`, the fix for `outline: none` quotes
    `outline: none`, and the comment above a `:focus-visible` rule satisfies a
    search for `:focus-visible` after the rule itself has been deleted.

    A per-line heuristic is not enough: it caught lines starting with `*`, `//`
    or `/*`, and missed the CONTINUATION lines of a JSX `{/* ... */}` block,
    which start with whatever word the sentence reached.

    Line numbering is preserved by replacing each comment with the same number
    of newlines, so a finding still points at the right line.
    """
    NEWLINE = chr(10)
    out: list[str] = []
    i, n = 0, len(text)
    in_block = in_line = False
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_block:
            if c == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            out.append(NEWLINE if c == NEWLINE else " ")
        elif in_line:
            if c == NEWLINE:
                in_line = False
                out.append(NEWLINE)
            else:
                out.append(" ")
        elif c == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        elif c == "/" and nxt == "/":
            in_line = True
            i += 2
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def check_anti_patterns() -> list[str]:
    bad: list[str] = []
    for f in _sources():
        text = _strip_comments(f.read_text(encoding="utf-8", errors="ignore"))
        rel = f.relative_to(REPO).as_posix()
        for line_no, line in enumerate(text.splitlines(), 1):
            for name, pat, why in ANTI_PATTERNS:
                if pat.search(line):
                    bad.append(f"{rel}:{line_no}  {name} - {why}")
    return bad


MANUAL = [
    "MONOCHROME  s3   with alert tokens greyed, every alert still identifiable",
    "FLASH       s8.2 exactly one flashing class, 3 Hz, stops on acknowledge",
    "MASTER RESET s4.2 reset clears the master, keeps the alert, re-arms",
    "3-SECOND    s4.3d a 200 ms transient caution stays visible >= 3 s",
    "STALE       s7   stop the feed; values render STALE with an age",
    "INVALID     s7.2 an out-of-range input renders as dashes, not a number",
    "OVERFLOW    s4.3c more alerts than fit -> '+N MORE', recallable",
    "ROLE        s10  unauthorised controls absent AND the API refuses them",
]


def _luminance(hex6: str) -> float:
    r, g, b = (int(hex6[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def check_contrast() -> list[str]:
    """s3.4a, which s15 lists as AUTOMATED and which nothing was running.

    MIL-STD-1472H 5.17.25.16.1 wants coloured symbols to differ from their
    background by at least 100 deltaE (CIE L*u*v*); s3.4a adopts the practical
    WCAG proxy of 4.5:1 for body text and 7:1 for numeric readouts and alert
    legends, "and verify it in CI".

    It had never been verified, and the palette had drifted accordingly: 28
    failing pairs across the two ambient palettes when this check was first
    run, including the WARNING red at 4.93:1 on a night panel and 5.19:1 on a
    day one -- the single most important colour on the console, failing the
    threshold its own standard sets for it, in both palettes.

    Both palettes are checked, because MIL-STD-411F 5.2.3 requires legibility
    "in illumination up to 10,000 fc" and the day palette is how that is met;
    a console that is only compliant at night is compliant for half a sortie.
    """
    css = CONSOLE / "theme" / "tokens.css"
    if not css.is_file():
        return [f"{css}: the token file is missing"]
    text = css.read_text(encoding="utf-8", errors="replace")

    def palette(block: str) -> dict[str, str]:
        return dict(re.findall(r"(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", block))

    parts = text.split(':root[data-ambient="day"]')
    night = palette(parts[0])
    day = {**night, **(palette(parts[1].split("}")[0]) if len(parts) > 1 else {})}

    surfaces = ("--bg-void", "--bg-panel", "--bg-raised")
    # 4.5:1 -- body text, labels, units, hints.
    body = ("--ink-dim", "--ink-mute", "--phys")
    # 7:1 -- s3.4a names "numeric readouts and alert legends". --ink is every
    # current value on the console; the rest are the legends.
    legend = ("--ink", "--state-normal", "--alert-advis", "--alert-caut",
              "--alert-caut-hi", "--alert-warn-ink", "--ref-selected-ink")

    bad: list[str] = []
    for label, pal in (("night", night), ("day", day)):
        for token, need in [(t, 4.5) for t in body] + [(t, 7.0) for t in legend]:
            if token not in pal:
                bad.append(f"tokens.css[{label}]: {token} is not defined")
                continue
            for surf in surfaces:
                if surf not in pal:
                    continue
                got = _contrast(pal[token], pal[surf])
                if got + 1e-9 < need:
                    bad.append(
                        f"tokens.css[{label}]: {token} on {surf} is "
                        f"{got:.2f}:1, below the {need}:1 s3.4a requires")

    # LEGENDS ON A COLOURED FILL. A lit toggle is text on a coding colour,
    # not on a surface, and nothing measured it: the RADAR and flight-
    # condition toggles carried a fixed dark legend that read 8:1 on the night
    # cyan and 1.5:1 on the day teal. The legend is a button label, so 4.5:1.
    fills = (("--on-advis", "--alert-advis"),     # RADAR, condition toggles
             ("--bg-void", "--alert-advis"),      # login button
             ("--bg-void", "--ref-selected"))     # scenario and rig buttons
    for label, pal in (("night", night), ("day", day)):
        for text_tok, fill_tok in fills:
            if text_tok not in pal or fill_tok not in pal:
                bad.append(f"tokens.css[{label}]: {text_tok} or {fill_tok} "
                           f"is not defined")
                continue
            got = _contrast(pal[text_tok], pal[fill_tok])
            if got + 1e-9 < 4.5:
                bad.append(f"tokens.css[{label}]: {text_tok} on {fill_tok} is "
                           f"{got:.2f}:1, below the 4.5:1 s3.4a requires")

    # A NAME THAT IS NOT DEFINED IS NOT A COLOUR. var(--bg) was used for three
    # button legends and never defined, so the browser fell back to the body
    # ink: pale on magenta at night, black on dark magenta by day.
    defined: set[str] = set()
    used: dict[str, str] = {}
    for f in _sources():
        src = f.read_text(encoding="utf-8", errors="ignore")
        defined |= set(re.findall(r"(--[a-zA-Z0-9-]+)\s*:", src))
        defined |= set(re.findall(r"[\"'](--[a-zA-Z0-9-]+)[\"']\s*[,:\]]", src))
        for m in re.finditer(r"var\((--[a-zA-Z0-9-]+)", src):
            used.setdefault(m.group(1), f"{f.relative_to(REPO).as_posix()}:"
                            f"{src.count(chr(10), 0, m.start()) + 1}")
    for name, where in sorted(used.items()):
        if name not in defined:
            bad.append(f"{where}  var({name}) is used but never defined")
    return bad


def check_zone_layout() -> list[str]:
    """s6.1/s6.2: the five zones, and what Zone B is REQUIRED to contain.

    THE VIOLATION THIS EXISTS TO CATCH, WHICH NOTHING CHECKED FOR MONTHS.
    s6.1 names Zone B the PRIMARY ENGINE STRIP and lists its contents: "The
    four highest-criticality parameters, always visible on every page: RPM,
    CHT (max of 4), EGT (max of 4), OIL PRESS." The console shipped a CONTEXT
    strip there instead -- engine id, aircraft id, flight time, altitude,
    airspeed, OAT, throttle, phase -- so on the MISSION page, where an operator
    commits an aircraft to a sortie, not one of the four appeared anywhere on
    the screen.

    s6.1 also requires "Zone D -- ALERT STACK (right rail, fixed)". There was
    no rail: `AlertStack` existed in the component library and was mounted on
    one page inside the content grid, so the alert surface moved between pages
    and vanished on most of them, against s6.2(a) -- "A parameter SHALL occupy
    the same screen position on every page and in every state."

    Both are structural and neither is visible in a diff of any single page,
    which is exactly why they need a check rather than a reviewer.
    """
    bad: list[str] = []
    shell = CONSOLE / "App.tsx"
    if not shell.is_file():
        return [f"{shell}: the application shell is missing entirely"]
    src = shell.read_text(encoding="utf-8", errors="replace")

    # Zone B: the four criticality parameters, mounted in the fixed shell
    # rather than on a page. Matched on the Readout labels, because that is
    # the s12 component that carries a value's STATE (s7.1) -- a plain <span>
    # of the same number would not annunciate a stale reading.
    for label in ('label="RPM"', 'label="CHT MAX"',
                  'label="EGT MAX"', 'label="OIL PRESS"'):
        if label not in src:
            bad.append(
                f"App.tsx: Zone B is missing a Readout with {label} - s6.1 "
                f"requires RPM, CHT max, EGT max and OIL PRESS on EVERY page")

    # Zone D: a fixed rail, marked so this check does not have to guess.
    if 'data-zone="D"' not in src:
        bad.append(
            'App.tsx: no element marked data-zone="D" - s6.1 requires a fixed '
            "right-rail ALERT STACK present on every page")
    elif "AlertStack" not in src:
        bad.append(
            "App.tsx: Zone D exists but does not mount AlertStack - s4.3 "
            "ordering is the component's job, not the rail's")

    # s6.3: the rail must COLLAPSE on a narrow panel, never shrink its text.
    css = (CONSOLE / "theme" / "tokens.css")
    if css.is_file():
        t = css.read_text(encoding="utf-8", errors="replace")
        if "--alert-rail-display" not in t or "@media" not in t:
            bad.append(
                "tokens.css: no media query collapsing Zone D - s6.3 requires "
                "the console to stay usable at 1366x768 by collapsing the "
                "rail, never by shrinking text below the s5.1 minima")
    return bad


def check_flash_is_applied() -> list[str]:
    """s8.2: the flash must be APPLIED, not merely defined.

    THE DEFECT THIS CATCHES. tokens.css carried a `.flash` class, a 3 Hz
    `annunciate` keyframe and a reduced-motion fallback for it, and Core.tsx
    carried a comment saying "flashing belongs to a new unacknowledged warning
    ROW". Nothing anywhere applied it: grepping the whole console for `flash`
    returned three hits and all three were comments. The entire s8.2 flash
    requirement -- MIL-STD-1472H 5.17.27 and 411F 4.1.3.5 -- was specified,
    styled, documented and dead.

    The server had been sending `acknowledged` on every alert row from the
    start, and the console's AlertRow interface did not declare the field, so
    there was nothing to drive a flash from even if something had tried.

    s8.2d also requires simultaneous flashers to be synchronised "from a single
    shared clock, not per-component timers" -- which a CSS animation cannot do,
    because two rows appearing a quarter-second apart each start their own from
    zero and end up in antiphase.
    """
    core = CONSOLE / "components" / "Core.tsx"
    if not core.is_file():
        return [f"{core}: the component library is missing"]
    src = core.read_text(encoding="utf-8", errors="replace")
    body = re.sub(r"/\*.*?\*/", "", src, flags=re.S)

    bad: list[str] = []
    if "acknowledged" not in body:
        bad.append("Core.tsx: AlertRow does not carry `acknowledged` - s8.2(a) "
                   "flashes a NEW, UNACKNOWLEDGED warning and cannot tell")
    if "useFlashPhase" not in body:
        bad.append("Core.tsx: no shared flash clock - s8.2(d) requires "
                   "simultaneous flashers synchronised from one clock")
    elif "setInterval" not in body:
        bad.append("Core.tsx: useFlashPhase does not drive a timer")
    # A CALL SITE, not the declaration. `"useFlashPhase()" in body` also
    # matches `export function useFlashPhase()`, so the first version of this
    # check passed with the flash disconnected -- the very state s8.2 was in
    # before it was implemented. Third time a check here was satisfied by the
    # wrong occurrence of its own search term; negative-test everything.
    if not re.search(r"=\s*useFlashPhase\(\)", body):
        bad.append("Core.tsx: the flash clock is defined but never called - "
                   "s8.2 was dead code once already")
    # s8.2(a): a WARNING only. Level 5 is WARNING in lib/api.ts levelName.
    if "level >= 5" not in body:
        bad.append("Core.tsx: nothing gates the flash on WARNING level - "
                   "s8.2(a) permits it for mission-critical events only")

    # s13(a) lists what an alert is coded by, and it is FIVE things: "hue +
    # glyph + legend + position + (for warnings) flash". The rows had hue,
    # legend and position; there was no glyph and the category word was never
    # rendered, so greying the alert tokens -- the s15 MONOCHROME condition --
    # left a WARNING and a CAUTION identical. That is P4, s13(a) on colour
    # vision, and s13(b) on laser eyewear inducing selective colour blindness.
    if not re.search(r"<AlertGlyph\s", body):
        bad.append("Core.tsx: alert rows carry no glyph - s13(a) codes an "
                   "alert by hue AND glyph AND legend AND position")
    if "categoryTag" not in body:
        bad.append("Core.tsx: the alert category is never rendered as a word - "
                   "s13(c) requires it so cyan advisories cannot be read as "
                   "green normal states")
    # s14 forbids emoji as status icons, so the glyph must be geometry.
    glyph = body.split("function AlertGlyph", 1)
    if len(glyph) > 1 and "<svg" not in glyph[1][:1200]:
        bad.append("Core.tsx: AlertGlyph is not drawn as SVG - s14 forbids "
                   "emoji status icons and a font glyph can go missing")
    return bad


def check_motion_and_focus() -> list[str]:
    """s8.1 motion budget, s8.1d reduced motion, s9.4 visible focus.

    Three of the s15 checklist items, none of which had an implementation.

    MOTION. s8.1c(ii) permits a bar moving to a new value with "<=150 ms
    linear easing" and s8.1b forbids decorative animation outright. The bar in
    Core.tsx was running 220 ms, over the budget by half.

    REDUCED MOTION. s8.1d: "prefers-reduced-motion SHALL disable (ii) and (iii)
    entirely." The media query disabled only the flash, so a bar kept animating
    for an operator who had asked the system to stop moving.

    FOCUS. s9.4 requires "full keyboard operability, visible focus ring (2 px,
    --ink, never red/amber per s3.3a)". There was no focus style anywhere, and
    the login fields set `outline: none` -- removing the only cue a keyboard
    operator has, on the one screen where they are certainly typing.
    """
    bad: list[str] = []
    css_path = CONSOLE / "theme" / "tokens.css"
    raw = css_path.read_text(encoding="utf-8", errors="replace") if css_path.is_file() else ""
    # COMMENTS ARE STRIPPED BEFORE ANYTHING IS LOOKED FOR.
    # The first version searched the raw file, and the prose explaining each of
    # these rules necessarily QUOTES the selector or the property it is about
    # -- so deleting the actual `:focus-visible` rule left the comment behind
    # and the check went on passing. A check that a comment can satisfy is not
    # a check.
    css = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)

    if ":focus-visible" not in css:
        bad.append("tokens.css: no :focus-visible rule - s9.4 requires a "
                   "visible 2 px focus ring for keyboard operation")
    else:
        ring = css.split(":focus-visible", 1)[1].split("}", 1)[0]
        if "--alert" in ring or "--ref-selected" in ring:
            bad.append("tokens.css: the focus ring uses an alerting colour - "
                       "s3.3a reserves red and amber for alerting")

    if "prefers-reduced-motion" not in css:
        bad.append("tokens.css: no prefers-reduced-motion block - s8.1d")
    else:
        block = css.split("prefers-reduced-motion", 1)[1]
        end = block.find(chr(10) + "}")
        block = block[:end] if end != -1 else block
        for cls in (".flash", ".bar-fill"):
            if cls not in block:
                bad.append(f"tokens.css: prefers-reduced-motion does not "
                           f"disable {cls} - s8.1d requires (ii) and (iii) off")

    # s8.1c(ii): no transition longer than 150 ms anywhere in the console.
    for path in _sources():
        for n, line in enumerate(_strip_comments(
                path.read_text(encoding="utf-8", errors="replace")).splitlines(), 1):
            for ms in re.findall(r"transition[^;\"]*?(\d+)\s*ms", line):
                if int(ms) > 150:
                    bad.append(f"{path.name}:{n}  {ms} ms transition - "
                               f"s8.1c(ii) caps a value change at 150 ms")
            if "outline: \"none\"" in line or "outline: none" in line:
                bad.append(f"{path.name}:{n}  outline removed - s9.4 requires "
                           f"focus to stay visible")
    return bad


def check_authenticated_fetch() -> list[str]:
    """Every API call from the console must carry the bearer token.

    The browser attaches no Authorization header on its own, so a bare
    ``fetch("/api/...")`` reaches the server ANONYMOUS and comes back
    "authentication required". To an operator that reads as a broken page, not
    as a missing token -- and it looks identical on a page they genuinely lack
    the scope for, which is the confusion PRD Part 4 s10a exists to prevent.

    Measured: the FLEET and REPLAY pages both did this, so two of twelve screens
    were unreachable for every role including the commander.

    Login, password change, refresh and demo-account discovery can run before
    an access token exists. The demo endpoint supplies the login screen.
    """
    out: list[str] = []
    # A fetch whose URL literal starts /api/, in any of the three
    # quote styles TSX uses. A leading dot is excluded so a method
    # call on some other object is not mistaken for the global.
    pat = re.compile(r"""(?<!\.)fetch\(\s*['"`]/api/([^'"`]*)""")
    for f in sorted(CONSOLE.rglob("*.tsx")) + sorted(CONSOLE.rglob("*.ts")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            m = pat.search(line)
            # Match exact public routes: a prefix exemption could hide a
            # protected route such as /api/demo/reset from this check.
            if m and m.group(1) not in {
                    "auth/login", "auth/change_password", "auth/refresh", "demo"}:
                out.append(
                    f"{f.relative_to(REPO)}:{i}  bare fetch to /api/{m.group(1)} "
                    f"- use api() so the bearer token is attached"
                )
    return out


def main() -> int:
    groups = [
        ("TYPE TEST (s5.1)", check_type()),
        ("ALERT / READOUT SIZE TEST (s5.1)", check_alert_and_readout_sizes()),
        ("RESERVED-COLOUR TEST (s3.3a)", check_reserved_colours()),
        ("CONTRAST TEST (s3.4a)", check_contrast()),
        ("ANTI-PATTERN TEST (s14)", check_anti_patterns()),
        ("ZONE LAYOUT TEST (s6.1/s6.2/s6.3)", check_zone_layout()),
        ("MOTION / FOCUS TEST (s8.1/s9.4)", check_motion_and_focus()),
        ("FLASH-APPLIED TEST (s8.2)", check_flash_is_applied()),
        ("AUTHENTICATED-FETCH TEST (s10c)", check_authenticated_fetch()),
    ]

    print("=" * 78)
    print("  PRD PART 4 s15 - AUTOMATED VERIFICATION")
    print("=" * 78)

    total = 0
    for name, findings in groups:
        status = "PASS" if not findings else f"FAIL ({len(findings)})"
        print(f"\n  [{status}] {name}")
        for f in findings[:25]:
            print(f"      {f}")
        if len(findings) > 25:
            print(f"      ... and {len(findings) - 25} more")
        total += len(findings)

    print("\n" + "-" * 78)
    print("  REQUIRES A RUNNING CONSOLE AND A HUMAN - not checked here:")
    for m in MANUAL:
        print(f"      [ ] {m}")

    print("\n" + "=" * 78)
    print(f"  {total} [SHALL] violation(s)" if total else "  COMPLIANT")
    print("=" * 78)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
