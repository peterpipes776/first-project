"""Command line: `python -m sweepdesk --help`."""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date

from . import db
from .extract import PageInfo, analyse_url, feed_links, fetch


def _print_comp(c: dict) -> None:
    value = f"£{c['value_gbp']:,.0f}" if c["value_gbp"] else "£?"
    due = "DUE " if c["due"] else "    "
    print(f"{due}[{c['id']:>3}] {value:>9}  {c['verdict']:<15} p={c['priority']:<5} "
          f"{c['frequency']:<6} {c['closes_on'] or '':<10}  {c['title'][:60]}")
    for f in c["red_flags"]:
        print(f"              ! {f}")
    if c["hidden_because"]:
        print(f"              hidden: {', '.join(c['hidden_because'])}")


def _add(conn, url: str, args=None) -> int:
    try:
        info = analyse_url(url)
    except Exception as exc:
        if args and (args.value or args.title):
            info = PageInfo(url=url)  # keep it with what the user told us
            print(f"  couldn't read page ({exc}); saving with the details you gave")
        else:
            raise
    if args:
        info.value_gbp = args.value or info.value_gbp
        info.title = args.title or info.title
        info.frequency = args.freq or info.frequency
        if args.closes:
            info.closes_on = date.fromisoformat(args.closes)
    comp_id = db.save_comp(conn, info)
    c = next(c for c in db.listing(conn, include_all=True) if c["id"] == comp_id)
    _print_comp(c)
    return comp_id


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sweepdesk", description="Track free UK prize draws worth entering.")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="check a competition page and add it")
    a.add_argument("url")
    a.add_argument("--value", type=float, help="prize value in £, if the page doesn't say")
    a.add_argument("--title")
    a.add_argument("--freq", choices=["once", "daily", "weekly"])
    a.add_argument("--closes", help="closing date, YYYY-MM-DD")

    i = sub.add_parser("import", help="add every URL from a CSV with a 'url' column")
    i.add_argument("csv_file")

    f = sub.add_parser("feed", help="manage RSS/Atom feeds of competition listings")
    f.add_argument("action", choices=["add", "remove", "list"])
    f.add_argument("url", nargs="?")

    sub.add_parser("refresh", help="read every feed and add new competitions")
    sub.add_parser("due", help="what you can enter right now")
    ls = sub.add_parser("list", help="everything being tracked")
    ls.add_argument("--all", action="store_true", help="include filtered-out ones")

    for name, hlp in [("entered", "record that you entered"), ("won", "mark as won"),
                      ("hide", "stop showing it")]:
        s = sub.add_parser(name, help=hlp)
        s.add_argument("id", type=int)

    ed = sub.add_parser("edit", help="correct details the page reader got wrong")
    ed.add_argument("id", type=int)
    ed.add_argument("--value", type=float)
    ed.add_argument("--title")
    ed.add_argument("--freq", choices=["once", "daily", "weekly"])
    ed.add_argument("--closes", help="YYYY-MM-DD")
    ed.add_argument("--winners", type=int)
    ed.add_argument("--uk", choices=["yes", "no"])
    ed.add_argument("--notes")

    pr = sub.add_parser("profile", help="your details, shown with copy buttons")
    pr.add_argument("action", choices=["set", "show"])
    pr.add_argument("key", nargs="?", choices=db.PROFILE_FIELDS)
    pr.add_argument("value", nargs="?")

    cf = sub.add_parser("min-value", help="show or set the minimum prize value in £")
    cf.add_argument("amount", nargs="?", type=float)

    sv = sub.add_parser("serve", help="open the dashboard")
    sv.add_argument("--port", type=int, default=8765)

    args = p.parse_args(argv)
    conn = db.connect()

    if args.cmd == "add":
        _add(conn, args.url, args)
    elif args.cmd == "import":
        with open(args.csv_file, newline="") as fh:
            for row in csv.DictReader(fh):
                url = (row.get("url") or "").strip()
                if url and not db.known_url(conn, url):
                    try:
                        _add(conn, url)
                    except Exception as exc:
                        print(f"  skipped {url}: {exc}", file=sys.stderr)
    elif args.cmd == "feed":
        if args.action == "list":
            print("\n".join(db.feeds(conn)) or "No feeds yet.")
        elif not args.url:
            p.error("feed add/remove needs a URL")
        elif args.action == "add":
            db.add_feed(conn, args.url)
        else:
            db.remove_feed(conn, args.url)
    elif args.cmd == "refresh":
        for feed in db.feeds(conn):
            print(f"Reading {feed}")
            try:
                links = feed_links(fetch(feed))
            except Exception as exc:
                print(f"  failed: {exc}", file=sys.stderr)
                continue
            for url in links:
                if not db.known_url(conn, url):
                    try:
                        _add(conn, url)
                    except Exception as exc:
                        print(f"  skipped {url}: {exc}", file=sys.stderr)
    elif args.cmd == "due":
        due = [c for c in db.listing(conn) if c["due"]]
        for c in due:
            _print_comp(c)
        print(f"{len(due)} due." if due else "Nothing due right now.")
    elif args.cmd == "list":
        for c in db.listing(conn, include_all=args.all):
            _print_comp(c)
    elif args.cmd == "entered":
        db.record_entry(conn, args.id)
    elif args.cmd == "won":
        db.update_comp(conn, args.id, status="won")
        print("Congratulations! Reply to the promoter before their deadline.")
    elif args.cmd == "hide":
        db.update_comp(conn, args.id, status="hidden")
    elif args.cmd == "edit":
        fields = {k: v for k, v in dict(
            value_gbp=args.value, title=args.title, frequency=args.freq, closes_on=args.closes,
            winners=args.winners, notes=args.notes,
            uk_eligible=None if args.uk is None else int(args.uk == "yes")).items() if v is not None}
        if args.closes:
            date.fromisoformat(args.closes)
        db.update_comp(conn, args.id, **fields)
    elif args.cmd == "profile":
        if args.action == "show":
            for k, v in db.get_profile(conn).items():
                print(f"{k:<14} {v}")
        elif not (args.key and args.value):
            p.error("profile set needs a field and a value")
        else:
            db.set_profile(conn, args.key, args.value)
    elif args.cmd == "min-value":
        if args.amount is not None:
            db.set_setting(conn, "min_value", str(args.amount))
        print(f"Minimum prize value: £{db.min_value(conn):,.0f}")
    elif args.cmd == "serve":
        from .web import serve
        serve(args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
