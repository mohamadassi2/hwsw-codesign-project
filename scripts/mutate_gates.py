#!/usr/bin/env python3
"""Mutation-test the two number checkers, the way tb/mutate.sh tests the testbench.

`check_report_numbers.py` and `check_deck_numbers.py` print a count of passing
gates, and that count is easy to misread: it says how many assertions ran, not
how many of the numbers in the documents are actually held to anything. A gate
that compares a constant to a constant passes forever, and a gate that asks
"does this number appear somewhere in the deck" does not notice when one of
three copies drifts.

So do to the checkers what hw/tb/mutate.sh does to the testbench: change one
number a document states, and see whether the checker fails. A number no
checker notices is ungated, and the count was flattering us by one.

Nothing is written to the working tree - the repository is copied to a
temporary directory and mutated there.

    python3 scripts/mutate_gates.py            # both documents, summary + misses
    python3 scripts/mutate_gates.py --quiet    # just the summary and the exit code

Exit status is non-zero if an ungated number is not in ALLOWED below.
"""
import os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# How many figures in each document a checker currently holds. This is a
# ratchet, not a target: the script fails if a number drops, so a gate cannot be
# weakened or a new unchecked figure added without someone noticing. Raise a
# floor when you raise the coverage.
#
# What is still ungated, and why, as of the last time these were raised:
#   docs/presentation.html   10 of 84. All of them are either a constant of the
#       bzip2 format (a selector every 50 symbols, codes up to 15 bits, 258
#       table entries, a 400 KB block), a constant of the proposed design (20
#       bits, 14 bits per bank), the 7% the assignment asks for, or an
#       assumption the slide labels as one (200 MHz, 0.6 ms of DMA). None is a
#       measurement, so there is nothing under results/ to recompute them from.
#   report_pyflate.txt  59 of 299, report_mdp.txt  34 of 135. The reports are
#       checked with `"1.141" in report`, which one copy of a repeated figure
#       satisfies for all of them - the same flaw the deck had until want()
#       started counting. Fixing it means teaching those 87 checks to count too.
FLOORS = {
    "docs/presentation.html": 74,
    "report_pyflate.txt": 59,
    "report_mdp.txt": 34,
}


def text_spans(src):
    """Character ranges of docs/presentation.html that are prose a slide states:
    outside every tag, and outside <style>, <script> and the inline drawings."""
    out, i, n, start = [], 0, len(src), 0
    closers = {"style": "</style>", "script": "</script>", "svg": "</svg>"}
    while i < n:
        if src[i] != "<":
            i += 1
            continue
        if start < i:
            out.append((start, i))
        m = re.match(r"</?([a-zA-Z][\w-]*)", src[i:i + 20])
        name = m.group(1).lower() if m else ""
        close = src.find(">", i)
        if close < 0:
            break
        if name in closers and src[i + 1] != "/":
            end = src.lower().find(closers[name], close)
            i = n if end < 0 else end + len(closers[name])
        else:
            i = close + 1
        start = i
    if start < n:
        out.append((start, n))
    return out


# What counts as a figure. README says "every figure the reports quote
# recomputes from results/", and a figure is a quantity with a unit: 487 ms,
# 2.34x, 51.0%, 148,271 symbols. A section number, a line-number citation, an
# RFC, a CPython version and a lecture number are none of those, and no gate
# should be expected to recompute them from a measurement.
UNIT = (r"(?:&nbsp;|\s)*(?:ms|msec|s\b|%|x\b|&times;|\u00d7|MHz|GHz|KB|MB|kbit|kb\b"
        r"|bytes?\b|B\b|cycles?\b|bits?\b|ns\b|runs?\b|entries\b|symbols?\b"
        r"|cells?\b|flip-flops?\b|gates?\b|levels?\b|samples?\b|ulp\b)")
NOT_A_FIGURE = re.compile(r"(?:section|lines?|RFC|lecture|figure|table|CPython|Python|Icarus"
                          r"|yosys|Yosys|version|mutation|slide)\s*$", re.I)


def numbers(path, src):
    """Every figure the document quotes, as (start, end, text): a quantity that
    carries a unit, or a comma-grouped count like 148,271."""
    spans = text_spans(src) if path.endswith(".html") else [(0, len(src))]
    found = []
    for a, b in spans:
        for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", src[a:b]):
            s, e = a + m.start(), a + m.end()
            tok, before, after = m.group(0), src[max(0, s - 24):s], src[e:e + 12]
            if path.endswith(".html") and re.search(r"\d\d/23", src[s - 3:e + 3]):
                continue          # the deck's own page numbers are chrome
            if src[e:e + 1] == "-" or src[s - 1:s] == "-":
                continue          # a range: a line-number citation like 291-310
            if NOT_A_FIGURE.search(before):
                continue
            if "," not in tok and not re.match(UNIT, after):
                continue          # no unit and no thousands group: not a figure
            found.append((s, e, tok))
    return found


def bump(s):
    """The same number with its last digit changed - a wrong figure of the right shape."""
    for i in range(len(s) - 1, -1, -1):
        if s[i].isdigit():
            return s[:i] + str((int(s[i]) + 1) % 10) + s[i + 1:]
    return s


def context(src, s, e):
    window = re.sub(r"<[^>]+>", " ", src[max(0, s - 80):e + 45])
    return re.sub(r"\s+", " ", window).strip()


def sweep(work, doc, checker, quiet):
    """Mutate every number in `doc` and report the ones `checker` does not catch."""
    path = os.path.join(work, doc)
    src = open(path, encoding="utf-8").read()
    todo = numbers(doc, src)
    caught, missed = 0, []
    env = dict(os.environ, DEVELOPER_DIR="/Library/Developer/CommandLineTools")

    # The control, as hw/tb/mutate.sh runs one: a checker that fails on the
    # unmutated tree would "catch" every mutation and report perfect coverage.
    # Writing this script without it did exactly that, and scored 84 of 84.
    ctl = subprocess.run([sys.executable, os.path.join(work, "scripts", checker)],
                         capture_output=True, text=True, cwd=work, env=env)
    if ctl.returncode != 0:
        print("%-28s CONTROL FAILED - %s does not pass on the unmutated tree, so "
              "nothing below would mean anything" % (doc, checker))
        return False, 0, FLOORS.get(doc, 0)
    for s, e, old in todo:
        new = bump(old)
        if new == old:
            continue
        open(path, "w", encoding="utf-8").write(src[:s] + new + src[e:])
        r = subprocess.run([sys.executable, os.path.join(work, "scripts", checker)],
                           capture_output=True, text=True, cwd=work, env=env)
        if r.returncode == 0:
            missed.append((old, context(src, s, e)))
        else:
            caught += 1
    open(path, "w", encoding="utf-8").write(src)

    total = caught + len(missed)
    floor = FLOORS.get(doc, 0)
    print("%-28s %3d figures   %3d gated   %3d not%s"
          % (doc, total, caught, len(missed),
             "" if caught >= floor else "   BELOW ITS FLOOR OF %d" % floor))
    if missed and not quiet:
        for old, ctx in missed:
            print("      %-10s %s" % (old, ctx[:104]))
    return caught >= floor, caught, floor


def main():
    quiet = "--quiet" in sys.argv
    work = tempfile.mkdtemp(prefix="mutate_gates_")
    try:
        shutil.copytree(ROOT, os.path.join(work, "r"),
                        ignore=shutil.ignore_patterns(".git", "venv*", "__pycache__", "FlameGraph"))
        work = os.path.join(work, "r")
        rows = [(doc,) + sweep(work, doc, checker, quiet)
                for doc, checker in (("docs/presentation.html", "check_deck_numbers.py"),
                                     ("report_pyflate.txt", "check_report_numbers.py"),
                                     ("report_mdp.txt", "check_report_numbers.py"))]
        print()
        fell = [(d, got, floor) for d, ok, got, floor in rows if not ok]
        if fell:
            for d, got, floor in fell:
                print("%s: %d figures gated, down from %d" % (d, got, floor))
            print("coverage went backwards - a gate was weakened, or a figure was "
                  "added that nothing checks")
            return 1
        print("coverage held: %s" % ", ".join("%s %d" % (d.split("/")[-1], got)
                                              for d, _, got, _ in rows))
        return 0
    finally:
        shutil.rmtree(os.path.dirname(work), ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
