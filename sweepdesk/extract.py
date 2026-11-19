"""Fetch a competition page and pull out the facts that matter.

Everything here is heuristic: it reads the page text and the links on it.
It never fills in or submits a form.
"""

from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser

USER_AGENT = "Mozilla/5.0 (compatible; sweepdesk/0.1; personal competition tracker)"
FETCH_DELAY_SECONDS = 2.0
_last_fetch = 0.0


# --------------------------------------------------------------------------- HTML


class _PageParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.links: list[tuple[str, str]] = []
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "a":
            self._href = dict(attrs).get("href")
            self._link_text = []
        elif tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "section"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._link_text).strip()))
            self._href = None

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
            return
        self._chunks.append(data)
        if self._href is not None:
            self._link_text.append(data.strip())

    @property
    def text(self) -> str:
        text = " ".join(self._chunks)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        return re.sub(r"\s*\n\s*", "\n", text).strip()


def _robots_allows(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(f"{parts.scheme}://{parts.netloc}/robots.txt")
    try:
        rp.read()
    except Exception:
        return True  # no readable robots.txt: allowed
    return rp.can_fetch(USER_AGENT, url)


def fetch(url: str, timeout: float = 20.0) -> str:
    """Politely GET a page: honours robots.txt and spaces requests out."""
    global _last_fetch
    if not _robots_allows(url):
        raise PermissionError(f"robots.txt asks automated readers not to fetch {url}")
    wait = FETCH_DELAY_SECONDS - (time.monotonic() - _last_fetch)
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        _last_fetch = time.monotonic()
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read(3_000_000).decode(charset, errors="replace")


# ----------------------------------------------------------------------- analysis


@dataclass
class PageInfo:
    url: str
    title: str = ""
    value_gbp: float | None = None
    closes_on: date | None = None
    frequency: str = "once"  # once | daily | weekly
    winners: int | None = None
    terms_url: str | None = None
    entry_method: str = "form"  # form | social | skill | email | post
    uk_eligible: bool | None = None  # None = not stated
    paid_entry: bool = False
    red_flags: list[str] = field(default_factory=list)
    good_signs: list[str] = field(default_factory=list)


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

_MONEY = re.compile(r"£\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?\s?(k|m|million|thousand)?\b", re.I)
_DATE_WORDS = re.compile(
    r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+(\d{4})", re.I)
_DATE_NUM = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})\b")
_CLOSE_WORDS = re.compile(r"\b(clos(?:es|ing|ed)?|ends?|ending|deadline|until|before|by)\b", re.I)
_UK_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")

# (pattern, message) — any match is a reason to be careful.
RED_FLAGS = [
    (r"\b(card number|cvv|cvc|sort code|bank details|account number|credit card details)\b",
     "Asks for card or bank details: genuine free draws never need these"),
    (r"\b(pay|cover|small)\b.{0,25}\b(fee|postage|shipping|delivery|handling)\b.{0,40}\b(claim|prize|receive)",
     "Wants a fee to claim or post the prize"),
    (r"\b(claim|release)\b.{0,30}\b(fee|charge|tax)\b",
     "Mentions a fee to claim the prize"),
    (r"\b09\d{2}\s?\d{3}\s?\d{4}\b|premium[- ]rate",
     "Uses a premium-rate phone number"),
    (r"\byou(?:'ve| have)? (?:been (?:selected|chosen)|(?:already )?won)\b",
     "Says you've already won: real winners are drawn, not told on a landing page"),
    (r"\b(only \d+ (?:left|remaining)|expires? in \d+ (?:minutes|seconds)|act now|hurry)\b",
     "Pressure tactics (countdowns, 'only N left')"),
    (r"\b(free trial|subscription|subscribe to win|recurring payment)\b",
     "Ties entry to a trial or subscription"),
    (r"\b(gift ?card|crypto|bitcoin|wire transfer|western union)\b.{0,30}\b(pay|send|fee)\b",
     "Asks you to pay by gift card, crypto or wire"),
    (r"\b(complete|take)\b.{0,15}\b(\d+ )?(offers|deals|surveys)\b.{0,20}\b(to (?:claim|win|qualify))",
     "Makes you complete offers or surveys to qualify"),
]

GOOD_SIGNS = [
    (r"\bno purchase (?:is )?necessary\b", "Says no purchase necessary"),
    (r"\bpromoter\b", "Names a promoter (required by the UK CAP Code)"),
    (r"\bwinners? (?:will be|is|are) (?:selected|drawn|chosen|picked|notified)\b",
     "Explains how winners are picked"),
    (r"\b(18|eighteen)\b.{0,20}\b(or over|and over|\+|years)", "States an age requirement"),
    (r"\bdata protection|privacy (?:policy|notice)\b", "Has a privacy notice"),
]

_PAID = re.compile(r"\b(entry fee|per ticket|buy (?:more )?tickets|tickets? from £|£\d+(?:\.\d\d)? (?:per|an?) entry)\b", re.I)
_UK_YES = re.compile(r"\b(uk|united kingdom|gb|great britain|england|scotland|wales|northern ireland)\b(?: and [a-z ]{2,30})? residents\b|\bopen to (?:all )?(?:uk|united kingdom)\b|\bresidents of the (?:uk|united kingdom)\b", re.I)
_NON_UK = r"(?:us|u\.s\.|united states|usa|50 united states|canada|canadian|australia|australian|new zealand)"
_UK_NO = re.compile(
    rf"\b{_NON_UK}\b[^.\n]{{0,30}}\bresidents?\b"
    rf"|\bresidents? of (?:the )?(?:\d+ )?{_NON_UK}\b"
    r"|\b(?:republic of )?ireland only\b", re.I)
_WINNERS = re.compile(r"\b(\d{1,4}|one|two|three|four|five|ten|twenty|fifty|hundred)\s+(?:lucky\s+)?winners\b", re.I)
_WORD_NUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10,
              "twenty": 20, "fifty": 50, "hundred": 100}


def _money_values(text: str) -> list[float]:
    vals = []
    for m in _MONEY.finditer(text):
        n = float(m.group(1).replace(",", ""))
        mult = (m.group(2) or "").lower()
        if mult in ("k", "thousand"):
            n *= 1_000
        elif mult in ("m", "million"):
            n *= 1_000_000
        if 0 < n <= 5_000_000:
            vals.append(n)
    return vals


def _parse_date(s: str) -> date | None:
    m = _DATE_WORDS.search(s)
    if m:
        try:
            return date(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
        except ValueError:
            pass
    m = _DATE_NUM.search(s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        try:
            return date(y, mo, d)  # UK order: day/month/year
        except ValueError:
            pass
    return None


def _closing_date(text: str) -> date | None:
    for m in _CLOSE_WORDS.finditer(text):
        found = _parse_date(text[m.end(): m.end() + 80])
        if found:
            return found
    return None


def _frequency(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(enter|entry|once)\b[^.\n]{0,25}\b(daily|every day|per day|each day|a day)\b|\bdaily (?:entry|entries|draw)\b", t):
        return "daily"
    if re.search(r"\b(enter|entry|once)\b[^.\n]{0,25}\b(weekly|every week|per week|each week|a week)\b|\bweekly (?:entry|entries|draw)\b", t):
        return "weekly"
    return "once"


def _entry_method(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(tiebreaker|tie-breaker|caption|in (?:\d+|twenty|fifty) words|write a|tell us why|best answer|judged)\b", t):
        return "skill"
    if re.search(r"\b(like|follow|share|retweet|repost|tag a friend|comment below)\b[^.\n]{0,40}\b(to (?:enter|win)|instagram|facebook|tiktok|x\b|twitter)", t):
        return "social"
    if re.search(r"\bby post\b|\bsend (?:a )?postcard\b|\bpostal entr", t):
        return "post"
    if re.search(r"\bemail (?:us|your answer|your entry)\b", t):
        return "email"
    return "form"


def analyse(url: str, html: str) -> PageInfo:
    p = _PageParser()
    p.feed(html)
    text = p.text
    info = PageInfo(url=url, title=re.sub(r"\s+", " ", p.title).strip()[:200])

    values = _money_values(text)
    prize_ctx = [v for m in re.finditer(r"\b(worth|value[d]?|rrp|prize of|win (?:a|an|one of)?)\b[^.\n]{0,60}", text, re.I)
                 for v in _money_values(m.group(0))]
    info.value_gbp = max(prize_ctx or values) if (prize_ctx or values) else None

    info.closes_on = _closing_date(text)
    info.frequency = _frequency(text)
    info.entry_method = _entry_method(text)

    w = _WINNERS.search(text)
    if w:
        g = w.group(1).lower()
        info.winners = int(g) if g.isdigit() else _WORD_NUMS.get(g)

    for href, label in p.links:
        if re.search(r"terms|t ?& ?c|t&amp;c|rules|conditions", f"{href} {label}", re.I):
            info.terms_url = urllib.parse.urljoin(url, href)
            break

    if _UK_NO.search(text) and not _UK_YES.search(text):
        info.uk_eligible = False
    elif _UK_YES.search(text):
        info.uk_eligible = True

    if _PAID.search(text) and not re.search(r"free (?:entry )?route|free postal entry|enter for free", text, re.I):
        info.paid_entry = True

    for pattern, msg in RED_FLAGS:
        if re.search(pattern, text, re.I):
            info.red_flags.append(msg)
    for pattern, msg in GOOD_SIGNS:
        if re.search(pattern, text, re.I):
            info.good_signs.append(msg)
    if _UK_POSTCODE.search(text):
        info.good_signs.append("Includes a UK postal address")
    if info.terms_url:
        info.good_signs.append("Links to terms and conditions")
    if info.closes_on:
        info.good_signs.append("States a closing date")
    return info


def analyse_url(url: str) -> PageInfo:
    return analyse(url, fetch(url))


def feed_links(xml: str) -> list[str]:
    """Item links from an RSS or Atom feed."""
    links = re.findall(r"<item\b.*?<link>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</link>", xml, re.S | re.I)
    links += re.findall(r"<entry\b.*?<link[^>]*href=\"([^\"]+)\"", xml, re.S | re.I)
    seen, out = set(), []
    for link in links:
        link = link.strip()
        if link and link not in seen:
            seen.add(link)
            out.append(link)
    return out
