#!/usr/bin/env python3
"""Build a queryable year index for Jiangshan Atlas snapshot files.

The upstream atlas stores each snapshot's covered years only inside the
human-readable ``snapshot.caption`` string (e.g. ``"220 — 237 · 三国鼎立初局"``).
There is no machine-readable start/end field, so nothing upstream can sort,
query or gap-check the timeline.  This tool extracts the range, builds a
year -> snapshot index, and reports timeline defects.

Exit codes: 0 clean, 1 findings, 2 usage/input error.
"""
import argparse
import json
import os
import re
import sys

TOOL = "jiangshan-atlas-year-index"
VERSION = "1.1.0"

UL = "\u2014"  # em dash
SEP = "[%s\u2013\\-~至到]" % UL
BCE = r"(?:公元前|前|BC\s*|BCE\s*)"
CE = r"(?:公元|AD\s*|CE\s*)"
NUM = r"(\d{1,4})"
POINT_RE = re.compile(r"^\s*(?P<b>%s|%s)?\s*(?P<n>\d{1,4})\s*(?:年)?\s*(?:·|$)" % (BCE, CE))
# Single years are frequently written after a label ("明 · 1407 年"), so the
# anchored form above misses them.  The loose form requires an explicit 年 and
# a 3-4 digit year, which keeps reign-year counts (2 digits) and section
# numbers out of the result.
POINT_ANY_RE = re.compile(
    r"(?P<b>%(bce)s|%(ce)s)?\s*(?P<n>\d{3,4})\s*年" % {"bce": BCE, "ce": CE}
)
RANGE_RE = re.compile(
    r"(?P<b1>%(bce)s|%(ce)s)?\s*(?P<n1>%(num)s)\s*(?:年)?\s*%(sep)s\s*(?:年)?\s*"
    r"(?P<b2>%(bce)s|%(ce)s)?\s*(?P<n2>%(num)s)\s*(?:年)?"
    % {"bce": BCE, "ce": CE, "num": NUM, "sep": SEP}
)


def _clean(text):
    out = []
    for ch in text:
        o = ord(ch)
        if 0xFF10 <= o <= 0xFF19:  # full-width digits
            out.append(chr(o - 0xFF10 + ord("0")))
        elif ch in "\u3000\u00a0":
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def parse_year_range(caption):
    """Return (start, end) with BCE as negative years, or None.

    Caption-only data forces a convention: an unmarked second year inherits
    BCE from a BCE first year (``前221 — 207``).  Crossing into CE must be
    written explicitly as ``公元8`` / ``AD 8``.
    """
    if not isinstance(caption, str):
        return None
    text = _clean(caption)
    m = RANGE_RE.search(text)
    if not m:
        p = POINT_RE.match(text) or POINT_ANY_RE.search(text)
        if not p or int(p.group("n")) == 0:
            return None
        y = int(p.group("n"))
        neg = bool(p.group("b") and re.match(BCE, p.group("b")))
        if not neg:
            # "公元前" may sit before the label that precedes the year.
            head = text[: p.start("n")]
            neg = bool(re.search(BCE, head[-8:]))
        return (-y, -y) if neg else (y, y)
    a, b = int(m.group("n1")), int(m.group("n2"))
    a_bce = bool(m.group("b1") and re.match(BCE, m.group("b1")))
    b_raw = m.group("b2") or ""
    b_bce = bool(re.match(BCE, b_raw)) if b_raw else a_bce
    a = -a if a_bce else a
    b = -b if b_bce else b
    if a == 0 or b == 0:  # there is no year 0
        return None
    return (a, b)


def _span(a, b):
    return b - a + 1


def scan(atlas_dir):
    """Read every *.geojson under atlas_dir. Returns (entries, findings)."""
    entries, findings = [], []
    if not os.path.isdir(atlas_dir):
        raise ValueError("atlas directory not found: %s" % atlas_dir)
    for root, dirs, files in os.walk(atlas_dir):
        dirs.sort()
        for name in sorted(files):
            if not name.endswith(".geojson"):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, atlas_dir)
            group = os.path.basename(os.path.dirname(path))
            key = name[: -len(".geojson")]
            try:
                with open(path, encoding="utf-8") as fh:
                    doc = json.load(fh)
            except (OSError, ValueError) as exc:
                findings.append(
                    {"code": "invalid-json", "severity": "error", "file": rel,
                     "detail": str(exc)[:200]}
                )
                continue
            if not isinstance(doc, dict):
                findings.append(
                    {"code": "invalid-json", "severity": "error", "file": rel,
                     "detail": "top level is not an object"}
                )
                continue
            snap = doc.get("snapshot")
            caption = snap.get("caption") if isinstance(snap, dict) else None
            rng = parse_year_range(caption)
            entry = {"key": key, "group": group, "file": rel,
                     "caption": caption, "start": None, "end": None}
            if rng is None:
                entry["reason"] = "no caption" if not caption else "no parseable range"
                findings.append(
                    {"code": "year-unparsed", "severity": "error", "file": rel,
                     "detail": entry["reason"] + ": " + repr(caption)[:120]}
                )
                entries.append(entry)
                continue
            entry["start"], entry["end"] = rng
            entries.append(entry)
            if rng[0] > rng[1]:
                findings.append(
                    {"code": "year-reversed", "severity": "error", "file": rel,
                     "detail": "range %d..%d starts after it ends" % rng}
                )
    order = []
    idx_path = os.path.join(atlas_dir, "index.json")
    if os.path.isfile(idx_path):
        try:
            with open(idx_path, encoding="utf-8") as fh:
                idx = json.load(fh)
            if isinstance(idx.get("order"), list):
                order = [k for k in idx["order"] if isinstance(k, str)]
        except (OSError, ValueError):
            pass
    rank = {k: i for i, k in enumerate(order)}
    for e in entries:
        e["order"] = rank.get(e["key"], len(order) + 1)
    # duplicate keys across groups
    by_key = {}
    for e in entries:
        by_key.setdefault(e["key"], []).append(e["file"])
    for key, paths in sorted(by_key.items()):
        if len(paths) > 1:
            findings.append({"code": "duplicate-key", "severity": "error",
                             "file": paths[0],
                             "detail": "key %s also in %s" % (key, ", ".join(paths[1:]))})
    return entries, findings


def group_findings(entries):
    """Ordering, overlap and gap checks inside each group (dynasty folder)."""
    findings = []
    groups = {}
    for e in entries:
        if e["start"] is None or e["start"] > e["end"]:
            continue  # reversed ranges are already reported by scan()
        groups.setdefault(e["group"], []).append(e)
    timeline = {}
    for group, items in sorted(groups.items()):
        items.sort(key=lambda e: (e["order"], e["key"]))
        covered = set()
        for i, e in enumerate(items):
            covered.update(range(e["start"], e["end"] + 1))
            if i:
                prev = items[i - 1]
                if e["start"] < prev["start"]:
                    findings.append(
                        {"code": "group-nonmonotonic", "severity": "warning",
                         "file": e["file"],
                         "detail": "%s starts %d, after %s starts %d"
                                   % (e["key"], e["start"], prev["key"], prev["start"])}
                    )
                if e["start"] <= prev["end"] and e["start"] >= prev["start"]:
                    findings.append(
                        {"code": "group-overlap", "severity": "warning",
                         "file": e["file"],
                         "detail": "%s [%d..%d] overlaps %s [%d..%d]"
                                   % (e["key"], e["start"], e["end"], prev["key"],
                                      prev["start"], prev["end"])}
                    )
                gap = e["start"] - prev["end"] - 1
                if gap > 0:
                    findings.append(
                        {"code": "group-gap", "severity": "warning",
                         "file": e["file"],
                         "detail": "%d uncovered year(s) between %s (ends %d) and %s (starts %d)"
                                   % (gap, prev["key"], prev["end"], e["key"], e["start"])}
                    )
        lo = min(e["start"] for e in items)
        hi = max(e["end"] for e in items)
        covered_in_span = sum(1 for y in range(lo, hi + 1) if y in covered)
        timeline[group] = {
            "snapshots": len(items),
            "span": [lo, hi],
            "span_years": hi - lo + 1,
            "covered_years": covered_in_span,
            "uncovered_years": hi - lo + 1 - covered_in_span,
        }
    return findings, timeline


def contested_years(entries):
    """Years rendered by more than one dynasty group (legitimate, but worth counting)."""
    years = {}
    for e in entries:
        if e["start"] is None or e["start"] > e["end"]:
            continue
        for y in range(e["start"], e["end"] + 1):
            years.setdefault(y, set()).add(e["group"])
    return sum(1 for g in years.values() if len(g) > 1)


def build(atlas_dir):
    entries, findings = scan(atlas_dir)
    more, timeline = group_findings(entries)
    findings.extend(more)
    findings.sort(key=lambda f: (f["file"], f["code"]))
    good = [e for e in entries if e["start"] is not None and e["start"] <= e["end"]]
    summary = {
        "snapshots": len(entries),
        "parsed": len(good),
        "unparsed": len(entries) - len(good),
        "groups": len(timeline),
        "findings": len(findings),
        "first_year": min((e["start"] for e in good), default=None),
        "last_year": max((e["end"] for e in good), default=None),
        "contested_years": contested_years(good),
    }
    return {
        "tool": TOOL,
        "version": VERSION,
        "atlas_dir": atlas_dir,
        "summary": summary,
        "groups": timeline,
        "snapshots": sorted(
            (e for e in entries if e["start"] is not None),
            key=lambda e: (e["start"], e["end"], e["group"], e["key"]),
        ),
        "findings": findings,
    }


def _label(y):
    return "%d BCE" % -y if y < 0 else "%d CE" % y


def render(report):
    lines = ["%s %s" % (report["tool"], report["version"]),
             "atlas: %s" % report["atlas_dir"]]
    s = report["summary"]
    lines.append("snapshots: %d parsed / %d total, groups: %d, findings: %d"
                 % (s["parsed"], s["snapshots"], s["groups"], s["findings"]))
    if s["first_year"] is not None:
        lines.append("timeline span: %s .. %s, contested years: %d"
                     % (_label(s["first_year"]), _label(s["last_year"]),
                        s["contested_years"]))
    for group, g in sorted(report["groups"].items()):
        lines.append("  %-8s %2d snapshots  %s..%s  uncovered %d/%d years"
                     % (group, g["snapshots"], _label(g["span"][0]),
                        _label(g["span"][1]), g["uncovered_years"], g["span_years"]))
    if report["findings"]:
        lines.append("findings:")
        for f in report["findings"]:
            lines.append("  [%s] %s: %s" % (f["severity"], f["code"], f["file"]))
            lines.append("      %s" % f["detail"])
    else:
        lines.append("no findings")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="atlas-year-index",
        description="Extract years from caption-only Jiangshan Atlas snapshots and audit the timeline.",
    )
    ap.add_argument("atlas_dir", help="path to a data/atlas directory of *.geojson snapshots")
    ap.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    ap.add_argument("--year", type=int, default=None,
                    help="only list snapshots covering this year (negative = BCE)")
    ap.add_argument("--quiet", action="store_true", help="print nothing; exit code only")
    args = ap.parse_args(argv)
    try:
        report = build(args.atlas_dir)
    except ValueError as exc:
        if not args.quiet:
            print("error: %s" % exc, file=sys.stderr)
        return 2
    if args.year is not None:
        y = args.year
        hits = [e for e in report["snapshots"] if e["start"] <= y <= e["end"]]
        if args.json:
            print(json.dumps({"tool": TOOL, "year": y, "count": len(hits),
                              "snapshots": hits}, ensure_ascii=False, indent=2))
        elif not args.quiet:
            print("%s: %d snapshot(s)" % (_label(y), len(hits)))
            for e in hits:
                print("  %-14s %s  %s" % (e["key"], e["group"], e["caption"]))
        return 0
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif not args.quiet:
        print(render(report))
    return 1 if report["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())