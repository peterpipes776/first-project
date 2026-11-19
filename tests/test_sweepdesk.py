import unittest
from datetime import date, datetime

from sweepdesk import db
from sweepdesk.extract import analyse, feed_links
from sweepdesk.scoring import legitimacy, verdict

GOOD = """<html><head><title>Win a Rolex Submariner | Acme Watches</title></head><body>
<h1>Win a Rolex Submariner worth £9,500</h1>
<p>Enter once per day. The competition closes at midnight on 31st December 2026.</p>
<p>No purchase necessary. Open to UK residents aged 18 or over.</p>
<p>One winner will be drawn at random. Promoter: Acme Watches Ltd, 1 High Street, Leeds LS1 4AB.</p>
<a href="/terms">Terms &amp; Conditions</a> <a href="/privacy">Privacy policy</a>
<p>Our newsletter costs £0. Shipping from £4.99 on orders.</p>
</body></html>"""

SCAM = """<html><head><title>Congratulations!</title></head><body>
<h1>You've been selected to win a MacBook Pro worth £2,499!</h1>
<p>Only 3 left! Just pay a small shipping fee of £1.95 to claim your prize.</p>
<p>Enter your card number and CVV below.</p></body></html>"""

US_ONLY = """<html><body><p>Win a £1,000 gift card! Open to legal residents of the 50 United States only.
Ends 01/02/2027.</p></body></html>"""

SKILL = """<html><body><p>Win a gaming PC worth £2k. Complete the tiebreaker in 25 words.
Closing date: 15 Jan 2027. UK residents only.</p></body></html>"""


class ExtractTests(unittest.TestCase):
    def test_genuine_page(self):
        info = analyse("https://acme.example/win", GOOD)
        self.assertEqual(info.title, "Win a Rolex Submariner | Acme Watches")
        self.assertEqual(info.value_gbp, 9500)
        self.assertEqual(info.closes_on, date(2026, 12, 31))
        self.assertEqual(info.frequency, "daily")
        self.assertEqual(info.terms_url, "https://acme.example/terms")
        self.assertTrue(info.uk_eligible)
        self.assertEqual(info.red_flags, [])
        self.assertEqual(verdict(legitimacy(info)), "looks legit")

    def test_scam_page(self):
        info = analyse("https://x.example", SCAM)
        self.assertGreaterEqual(len(info.red_flags), 3)
        self.assertEqual(verdict(legitimacy(info)), "avoid")

    def test_us_only_and_numeric_date(self):
        info = analyse("https://y.example", US_ONLY)
        self.assertIs(info.uk_eligible, False)
        self.assertEqual(info.closes_on, date(2027, 2, 1))  # UK day/month order

    def test_skill_and_k_suffix(self):
        info = analyse("https://z.example", SKILL)
        self.assertEqual(info.value_gbp, 2000)
        self.assertEqual(info.entry_method, "skill")
        self.assertEqual(info.closes_on, date(2027, 1, 15))

    def test_feed_links(self):
        rss = "<rss><channel><item><title>A</title><link>https://a.example/1</link></item>" \
              "<item><link><![CDATA[https://a.example/2]]></link></item></channel></rss>"
        self.assertEqual(feed_links(rss), ["https://a.example/1", "https://a.example/2"])


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_due_rules(self):
        now = datetime(2026, 11, 19, 10, 0)
        self.assertTrue(db.is_due("once", None, now))
        self.assertFalse(db.is_due("once", datetime(2026, 1, 1), now))
        self.assertFalse(db.is_due("daily", datetime(2026, 11, 19, 8, 0), now))
        self.assertTrue(db.is_due("daily", datetime(2026, 11, 18, 23, 0), now))
        self.assertFalse(db.is_due("weekly", datetime(2026, 11, 14), now))
        self.assertTrue(db.is_due("weekly", datetime(2026, 11, 12), now))

    def test_filters(self):
        good = analyse("https://acme.example/win", GOOD)
        cheap = analyse("https://c.example", "<p>Win a mug worth £15. UK residents. No purchase necessary.</p>")
        db.save_comp(self.conn, good)
        db.save_comp(self.conn, cheap)
        db.save_comp(self.conn, analyse("https://x.example", SCAM))
        db.save_comp(self.conn, analyse("https://y.example", US_ONLY))
        now = datetime(2026, 11, 19)
        shown = [c["url"] for c in db.listing(self.conn, now=now)]
        self.assertEqual(shown, ["https://acme.example/win"])
        self.assertEqual(len(db.listing(self.conn, include_all=True, now=now)), 4)

    def test_entry_makes_it_not_due(self):
        cid = db.save_comp(self.conn, analyse("https://acme.example/win", GOOD))
        db.record_entry(self.conn, cid, datetime(2026, 11, 19, 9))
        c = db.listing(self.conn, now=datetime(2026, 11, 19, 12))[0]
        self.assertFalse(c["due"])
        c = db.listing(self.conn, now=datetime(2026, 11, 20, 9))[0]
        self.assertTrue(c["due"])


if __name__ == "__main__":
    unittest.main()
