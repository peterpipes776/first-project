# Sweepdesk

Find, vet and keep track of **free UK prize draws worth £200 or more**, then enter
them yourself in a few seconds each.

Sweepdesk does the tedious parts: reading the page, judging whether it's genuine,
working out when you're next allowed to enter, and keeping your details one click
away. **It never submits an entry for you.** Nearly every UK promoter's terms void
entries made "by automated means", and bulk or duplicate entries get you
disqualified, sometimes after you've already won. Entering by hand, within the
rules, keeps your wins valid.

## What it does

- **Reads a competition page** and pulls out the prize value, closing date, entry
  frequency (once/daily/weekly), number of winners, entry method, T&Cs link and
  UK eligibility.
- **Scores legitimacy (0–100).** It rewards the basics the UK CAP Code expects from a
  promoter (a named promoter and address, closing date, how winners are picked, T&Cs)
  and penalises scam signs heavily: card or bank details, fees to claim, premium-rate
  numbers, "you've already won", countdown pressure, subscription traps.
- **Filters out** prizes under your minimum value, competitions not open to UK
  residents, paid entries and scam risks.
- **Ranks by priority**, a transparent heuristic rather than a probability. Bigger
  prizes, more winners, short closing windows and **skill or postal entries** (far
  fewer people bother) rank higher. Social "like & share" giveaways rank lower.
- **Tracks entries** so a daily draw shows up again tomorrow, a weekly one in 7 days,
  and a one-off never again.
- **Dashboard** with an "Open entry page" button, an "I entered" button and copy
  buttons for your name, email, address and so on.

## Setup

Requires Python 3.10+. No other dependencies.

```bash
pip install -e .          # or run everything as: python -m sweepdesk ...
sweepdesk min-value 200
sweepdesk profile set full_name "Your Name"
sweepdesk profile set email "comps@yourdomain.com"   # use a dedicated inbox
sweepdesk profile set postcode "AB1 2CD"
sweepdesk serve           # http://127.0.0.1:8765
```

Your data stays on your machine in `~/.sweepdesk/sweepdesk.db` (override with
`SWEEPDESK_DB`).

## Daily use

```bash
sweepdesk add https://brand.co.uk/win-a-laptop     # check & add one page
sweepdesk add URL --value 1200 --freq daily        # override what it read
sweepdesk import comps.csv                         # bulk add (CSV with a 'url' column)
sweepdesk feed add https://some-comp-site/feed/    # RSS/Atom feed of listings
sweepdesk refresh                                  # pull new items from feeds
sweepdesk due                                      # what you can enter now
sweepdesk entered 12                               # after you've entered #12
sweepdesk edit 12 --closes 2026-12-31 --value 950  # fix anything misread
sweepdesk won 12
```

Feed fetching is polite: it honours `robots.txt` and waits 2 seconds between
requests. Point it at the promoter's own page where you can. A listing site's page
often lacks the full T&Cs, so its legitimacy score will be lower.

## Tips that genuinely improve your odds

- **Favour skill, tiebreaker and postal entries.** Far fewer entrants.
- **Never miss a daily entry** on the high-value ones. That's what the "Due now" list is for.
- **Short closing windows and local competitions** draw fewer entrants.
- **Use a dedicated email address and check spam.** Winners usually have a deadline
  (often 7–28 days) to reply, or the prize is redrawn.
- **Never pay to claim.** A genuine UK prize draw is free to enter and free to claim.

## Tests

```bash
python -m unittest -v
```
