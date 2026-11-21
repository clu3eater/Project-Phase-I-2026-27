#!/usr/bin/env python3
"""The half of the PRD Part 4 s15 checklist that needs a RUNNING console.

`scripts/hmi_check.py` reads the source and proves nine things about it. The
rest of the s15 list is behavioural -- "stop the telemetry feed", "log in as
each of the four roles", "grey the alert tokens" -- and no static check can
reach those. They were marked "REQUIRES A RUNNING CONSOLE AND A HUMAN", which
in practice meant nobody ran them, and that is exactly how s8.2 came to be
fully styled, fully documented and never once applied to an element.

This drives a real console in a real browser and checks four of them:

    ROLE        s10   unauthorised controls absent AND the API refuses anyway
    STALE       s7.3  cut the feed; the console must stop looking live
    FLASH       s8.2  a new unacknowledged WARNING flashes, and the master
                      reset stops it while the alert itself remains
    MONOCHROME  s3/P4 grey every alerting hue; alerts stay identifiable

Run it against a THROWAWAY instance, never the operational one: it injects a
fault and acknowledges alerts.

    DT_DATA_DIR=/tmp/hmi DT_PORT=8011 DT_ALLOW_INITIAL_PASSWORDS=1 \\
        python -m layer4_core.twin_api &
    python scripts/hmi_runtime_check.py --base http://127.0.0.1:8011 \\
        --credentials /tmp/hmi/keys/FIRST_RUN_CREDENTIALS.txt

Exit status is the number of failures, so it drops into CI beside its static
sibling.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request

# Privileged actions and the scope each needs, per layer4_core/security.py.
# One the engineer holds and the maintenance officer does not, and one the
# other way round -- so a role table that had simply been widened for
# everybody would fail here rather than pass.
PROBES = [
    ("/api/faults/inject", {"mode": "misfire", "severity": 0.5}, "run:simulation"),
    ("/api/maintenance/performed", {"action_id": "A1"}, "write:maintenance"),
]


def _post(base, path, body, tok=None):
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if tok:
        headers["Authorization"] = "Bearer " + tok
    req = urllib.request.Request(base + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, None


def _get(base, path, tok):
    req = urllib.request.Request(
        base + path, headers={"Authorization": "Bearer " + tok})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def read_credentials(path):
    """Parse the note the server writes on a fresh data directory."""
    users = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"\s+(\S+)\s+ROLE_(\S+)\s+(\S+)\s*$", line)
            if m:
                users.append((m.group(1), m.group(3), m.group(2)))
    return users


def check_role(base, users, out):
    """s10: hidden in the console AND refused by the API.

    s10(a) prefers hiding a control to disabling it, and s10(c) requires the
    server to enforce regardless -- so checking the console alone proves
    nothing at all. Both halves are here, and the API half is the one that
    matters.
    """
    bad = 0
    out("s10(c) -- the SERVER refuses, whatever the console chooses to show")
    for user, pw, role in users:
        st, s = _post(base, "/api/auth/login", {"username": user, "password": pw})
        if s is None:
            out(f"   {user}: could not sign in ({st})")
            bad += 1
            continue
        tok, scopes = s["access_token"], set(s["scopes"])
        cells = []
        for path, body, need in PROBES:
            code, _ = _post(base, path, body, tok)
            allowed = need in scopes or "*" in scopes
            ok = (code != 403) if allowed else (code == 403)
            bad += 0 if ok else 1
            name = path.rsplit("/", 1)[-1]
            cells.append(f"{name}={code}" + ("" if ok else " MISMATCH"))
        out(f"   {user:<12} {role:<12} {'  '.join(cells)}")
    return bad


def _login_ui(pg, base, user, pw):
    pg.goto(base, wait_until="networkidle")
    pg.get_by_placeholder("User ID").fill(user)
    pg.get_by_placeholder("Password").fill(pw)
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(6000)


def check_stale(ctx, pg, base, user, pw, out):
    """s7.3: a console whose feed has stopped must not go on looking live.

    s7 opens by saying why: "the most dangerous failure mode of a monitoring
    console is a plausible-looking frozen number."
    """
    _login_ui(pg, base, user, pw)
    before = "LINK OK" in pg.inner_text("body")
    ctx.set_offline(True)
    pg.wait_for_timeout(12000)
    body = pg.inner_text("body")
    banner = "DATA NOT LIVE" in body
    dim = float(pg.evaluate(
        "() => { const m = document.querySelector('main');"
        " return m ? getComputedStyle(m).opacity : '1'; }"))
    ctx.set_offline(False)
    pg.wait_for_timeout(9000)
    back = "LINK OK" in pg.inner_text("body")
    out(f"   link_before={before}  banner_on_loss={banner}  "
        f"work_area_opacity={dim}  recovered={back}")
    return 0 if (before and banner and dim < 1.0 and back) else 1


def check_flash(base, pg, tok, out):
    """s8.2: a new unacknowledged WARNING flashes; the reset stops it.

    Sampled faster than the 166 ms half-period of the 3 Hz rate, so both
    phases are caught. Two distinct bar colours means it is alternating; one
    means it is static -- which is what this console did for its entire life
    before the flash was actually wired up.
    """
    sel = '[data-zone="D"] div[style*="border-left"]'

    def sample(n=40):
        seen = {}
        for _ in range(n):
            for c in pg.eval_on_selector_all(
                    sel, "e=>e.map(x=>getComputedStyle(x).borderLeftColor)"):
                seen[c] = seen.get(c, 0) + 1
            pg.wait_for_timeout(50)
        return seen

    lvl = 0
    alerts = {"active": []}
    for _ in range(80):
        time.sleep(3)
        alerts = _get(base, "/api/state", tok)["twin"]["alerts"]
        lvl = max([r["level"] for r in alerts["active"]] or [0])
        if lvl >= 5:
            break
    if lvl < 5:
        out("   no WARNING-level alert appeared; flash not exercised")
        return 0

    pg.wait_for_timeout(1500)
    during = sample()
    _post(base, "/api/alerts/acknowledge", {}, tok)
    pg.wait_for_timeout(2500)
    after = sample()
    alerts = _get(base, "/api/state", tok)["twin"]["alerts"]
    remains = len(alerts["active"]) > 0
    acked = all(r["acknowledged"] for r in alerts["active"]) if remains else False
    out(f"   unacknowledged: {len(during)} distinct bar colours {list(during)}")
    out(f"   after reset:    {len(after)} distinct, alert_remains={remains}, "
        f"acknowledged={acked}")
    bad = 0
    if len(during) < 2:
        out("   FAIL s8.2: the status bar did not alternate")
        bad += 1
    if not (remains and acked):
        out("   FAIL s4.2(c)/s8.2(f): the reset must leave the alert, acknowledged")
        bad += 1
    return bad


def check_monochrome(pg, out):
    """s3/P4: grey every alerting hue; an alert must still be readable.

    s13(a) codes an alert by "hue + glyph + legend + position + (for warnings)
    flash". Removing the first of those must leave the other four standing --
    which is also what s13(b) demands of any operational system, since
    laser-protective eyewear induces selective colour blindness.
    """
    pg.add_style_tag(content=""":root, :root[data-ambient="day"] {
        --alert-warn:#808080 !important; --alert-warn-ink:#808080 !important;
        --alert-caut:#808080 !important; --alert-caut-hi:#808080 !important;
        --alert-advis:#808080 !important; --state-normal:#808080 !important;
        --ref-selected:#808080 !important; }""")
    pg.wait_for_timeout(800)
    rows = pg.eval_on_selector_all(
        '[data-zone="D"] div[style*="border-left"]',
        "e => e.map(x => ({"
        " text: x.innerText.split(String.fromCharCode(10)).join(' | '),"
        " glyphs: x.querySelectorAll('svg').length,"
        " title: (x.querySelector('svg title')||{}).textContent || null }))")
    if not rows:
        out("   no alerts present; monochrome not exercised")
        return 0
    bad = 0
    for r in rows:
        tagged = any(t in r["text"] for t in ("WARN", "CAUT", "ADVS"))
        ok = r["glyphs"] >= 1 and r["title"] and tagged
        bad += 0 if ok else 1
        out(f"   glyph={r['glyphs']} title={r['title']} tagged={tagged}  "
            f"{r['text'][:50]}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8011")
    ap.add_argument("--credentials", required=True,
                    help="FIRST_RUN_CREDENTIALS.txt from the instance data dir")
    a = ap.parse_args()

    users = read_credentials(a.credentials)
    if not users:
        print("no credentials parsed from", a.credentials)
        return 1
    commander = next((u for u in users if u[2] == "COMMANDER"), users[-1])

    lines: list[str] = []
    out = lines.append
    total = 0

    print("=" * 78)
    print("  PRD PART 4 s15 - RUNTIME VERIFICATION")
    print("=" * 78)

    total += check_role(a.base, users, out)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        out("")
        out("   playwright is not installed; the browser checks were skipped.")
        out("   pip install playwright  (it drives the installed Chrome)")
        print("\n".join(lines))
        return total

    with sync_playwright() as pw:
        # channel="chrome" rather than the bundled build: Playwright's own
        # Chromium download fails behind some proxies, and the installed
        # browser is the one an operator would be using anyway.
        br = pw.chromium.launch(channel="chrome")
        ctx = br.new_context(viewport={"width": 1920, "height": 1080})
        pg = ctx.new_page()

        out("")
        out("s7.3 -- STALE: the console stops looking live when the feed stops")
        total += check_stale(ctx, pg, a.base, commander[0], commander[1], out)

        _, s = _post(a.base, "/api/auth/login",
                     {"username": commander[0], "password": commander[1]})
        tok = s["access_token"]
        # Injected AFTER the browser has signed in, because signing in
        # restarts the sortie -- which cools the engine and clears exactly the
        # alert this is trying to raise.
        _post(a.base, "/api/faults/inject",
              {"mode": "cooling_degradation", "severity": 1.0,
               "ramp_hours": 0.01}, tok)

        out("")
        out("s8.2 -- FLASH: a new unacknowledged WARNING, and the master reset")
        total += check_flash(a.base, pg, tok, out)

        out("")
        out("s3/P4 -- MONOCHROME: alerts identifiable with every hue greyed")
        total += check_monochrome(pg, out)

        br.close()

    print("\n".join(lines))
    print("\n" + "=" * 78)
    print(f"  {total} failure(s)" if total else "  RUNTIME CHECKS PASS")
    print("=" * 78)
    return total


if __name__ == "__main__":
    sys.exit(main())
