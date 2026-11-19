"""A small local dashboard: http://127.0.0.1:8765

It lists what you can enter today, opens the entry page in a new tab and gives
you copy buttons for your details. You submit every entry yourself.
"""

from __future__ import annotations

import html
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import db
from .extract import analyse_url

e = html.escape

CSS = """
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6b6b66;--card:#fff;--line:#e3e3de;
--ok:#1f7a4d;--warn:#a86400;--bad:#b3261e;--accent:#2f5bd3}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ececea;--muted:#9a9a94;
--card:#1f1f1e;--line:#33332f;--ok:#4cc38a;--warn:#e0a33a;--bad:#f2766b;--accent:#7da0ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 10px}
.muted{color:var(--muted)}.row{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:8px 0}
.title{font-weight:600}.title a{color:inherit}.meta{font-size:13px;color:var(--muted)}
.badge{font-size:12px;padding:2px 8px;border-radius:99px;border:1px solid currentColor}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
button,.btn{font:inherit;font-size:13px;padding:6px 12px;border-radius:7px;border:1px solid var(--line);
background:var(--card);color:var(--fg);cursor:pointer;text-decoration:none;display:inline-block}
.primary{background:var(--accent);border-color:var(--accent);color:#fff}
input{font:inherit;padding:7px 10px;border-radius:7px;border:1px solid var(--line);background:var(--card);color:var(--fg)}
form{display:inline}ul.flags{margin:6px 0 0;padding-left:18px;font-size:13px}
.profile{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:8px}
.value{font-variant-numeric:tabular-nums;font-weight:600}
"""

JS = """
document.querySelectorAll('[data-copy]').forEach(b=>b.addEventListener('click',()=>{
 navigator.clipboard.writeText(b.dataset.copy).then(()=>{const t=b.textContent;b.textContent='Copied';
 setTimeout(()=>b.textContent=t,900)})}));
"""


def _verdict_class(v: str) -> str:
    return {"looks legit": "ok", "check the T&Cs": "warn"}.get(v, "bad")


def _comp_card(c: dict) -> str:
    value = f"£{c['value_gbp']:,.0f}" if c["value_gbp"] else "value unknown"
    bits = [c["frequency"], c["entry_method"]]
    if c["closes_on"]:
        bits.append(f"closes {c['closes_on']}")
    if c["winners"]:
        bits.append(f"{c['winners']} winners")
    bits.append(f"entered {c['entries']}×")
    if c["hidden_because"]:
        bits.append("hidden: " + ", ".join(c["hidden_because"]))
    flags = "".join(f"<li class=bad>{e(f)}</li>" for f in c["red_flags"])
    terms = f' · <a href="{e(c["terms_url"])}" target=_blank rel=noopener>T&amp;Cs</a>' if c["terms_url"] else ""
    actions = ""
    if c["due"] and not c["hidden_because"]:
        actions += (f'<a class="btn primary" href="{e(c["url"])}" target=_blank rel=noopener>Open entry page</a> '
                    f'<form method=post action=/entered><input type=hidden name=id value={c["id"]}>'
                    f'<button>I entered</button></form> ')
    else:
        actions += f'<a class=btn href="{e(c["url"])}" target=_blank rel=noopener>Open</a> '
    actions += (f'<form method=post action=/status><input type=hidden name=id value={c["id"]}>'
                f'<input type=hidden name=status value=won><button>I won!</button></form> '
                f'<form method=post action=/status><input type=hidden name=id value={c["id"]}>'
                f'<input type=hidden name=status value=hidden><button>Hide</button></form>')
    return f"""<div class=card>
<div class=row><span class=value>{value}</span>
<span class=title><a href="{e(c['url'])}" target=_blank rel=noopener>{e(c['title'])}</a></span>
<span class="badge {_verdict_class(c['verdict'])}">{e(c['verdict'])} · {c['legit']}</span>
<span class=meta>priority {c['priority']}</span></div>
<div class=meta>{e(' · '.join(bits))}{terms}</div>
{f'<ul class=flags>{flags}</ul>' if flags else ''}
<div class=row style="margin-top:10px">{actions}</div></div>"""


def render(conn, message: str = "", show_all: bool = False) -> str:
    comps = db.listing(conn, include_all=show_all)
    due = [c for c in comps if c["due"]]
    later = [c for c in comps if not c["due"]]
    won = [c for c in db.listing(conn, include_all=True) if c["status"] == "won"]
    profile = db.get_profile(conn)
    prof_html = "".join(
        f'<div class=card><div class=meta>{e(k.replace("_", " "))}</div>'
        f'<div class=row><span>{e(profile[k])}</span>'
        f'<button data-copy="{e(profile[k])}">Copy</button></div></div>'
        for k in db.PROFILE_FIELDS if profile.get(k))
    if not prof_html:
        prof_html = '<p class=muted>Add your details with <code>sweepdesk profile set email you@example.com</code>.</p>'
    toggle = '<a href="/">Hide filtered</a>' if show_all else '<a href="/?all=1">Show filtered-out</a>'
    msg = f'<div class=card>{e(message)}</div>' if message else ""
    return f"""<!doctype html><html lang=en><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Sweepdesk</title>
<style>{CSS}</style><main>
<h1>Sweepdesk</h1>
<div class=muted>Free UK prize draws worth £{db.min_value(conn):,.0f}+ · you submit every entry yourself · {toggle}</div>
{msg}
<h2>Add a competition</h2>
<form method=post action=/add class=row><input name=url type=url required placeholder="https://… competition page" style="flex:1;min-width:260px">
<button class=primary>Check &amp; add</button></form>
<h2>Due now ({len(due)})</h2>{''.join(map(_comp_card, due)) or '<p class=muted>Nothing due. Nice.</p>'}
<h2>Already entered / waiting ({len(later)})</h2>{''.join(map(_comp_card, later)) or '<p class=muted>None.</p>'}
<h2>Wins ({len(won)})</h2>{''.join(map(_comp_card, won)) or '<p class=muted>Not yet. Check your inbox and spam folder for winner emails: most have a reply deadline.</p>'}
<h2>Your details</h2><div class=profile>{prof_html}</div>
</main><script>{JS}</script></html>"""


class Handler(BaseHTTPRequestHandler):
    db_file = None

    def _send(self, body: str, status: int = 200):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, msg: str = ""):
        self.send_response(303)
        self.send_header("Location", "/" + (f"?msg={urllib.parse.quote(msg)}" if msg else ""))
        self.end_headers()

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        if urllib.parse.urlsplit(self.path).path != "/":
            return self._send("Not found", 404)
        with db.connect(self.db_file) as conn:
            self._send(render(conn, q.get("msg", [""])[0], bool(q.get("all"))))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(length).decode()).items()}
        path = urllib.parse.urlsplit(self.path).path
        with db.connect(self.db_file) as conn:
            if path == "/add":
                url = form.get("url", "").strip()
                if not url.startswith(("http://", "https://")):
                    return self._redirect("That doesn't look like a web address.")
                try:
                    info = analyse_url(url)
                except Exception as exc:  # network, robots.txt, bad page
                    return self._redirect(f"Couldn't read that page: {exc}")
                db.save_comp(conn, info)
                return self._redirect(f"Added: {info.title or url}")
            comp_id = int(form.get("id", 0))
            if path == "/entered":
                db.record_entry(conn, comp_id)
                return self._redirect("Entry recorded.")
            if path == "/status" and form.get("status") in {"won", "hidden", "active"}:
                db.update_comp(conn, comp_id, status=form["status"])
                return self._redirect("Congratulations!" if form["status"] == "won" else "Updated.")
        self._send("Bad request", 400)

    def log_message(self, *args):
        pass


def serve(port: int = 8765, db_file=None) -> None:
    Handler.db_file = db_file
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Sweepdesk running at http://127.0.0.1:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
