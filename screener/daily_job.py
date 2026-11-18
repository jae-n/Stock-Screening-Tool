"""DailyJob singleton: discover -> refresh data -> screen -> send ONE morning message."""

import traceback
from datetime import date, datetime, timezone

import requests

from screener.config import Config
from screener.daily_report import DailyReport
from screener.database import Database
from screener.discovery import Discovery
from screener.loader import FundamentalsLoader
from screener.market_loader import MarketDataLoader
from screener.market_overview import MarketOverview
from screener.notifier import Notifier
from screener.singleton import SingletonMeta
from screener.stock_screener import StockScreener


class DailyJob(metaclass=SingletonMeta):
    def __init__(self):
        self._config = Config()
        self._db = Database()
        self._screener = StockScreener()
        self._report = DailyReport()
        self._notifier = Notifier()

    def _refresh_market(self, watchlist, today, discover):
        """Yahoo side: find candidates and snapshot the broad market. Never raises."""
        warnings = []
        if discover and self._config.discovery_enabled:
            warnings += Discovery().refresh(today)
        warnings += MarketOverview().refresh(today)
        return warnings

    def _refresh_data(self, universe, prices):
        """Download filings and prices for everything we will screen. A failure must not stop
        the message: the job carries on with what is stored and says so in the message."""
        warnings = []
        try:
            FundamentalsLoader().load(universe, max_age_days=self._config.fundamentals_max_age_days)
        except RuntimeError as exc:
            warnings.append(f"filings refresh failed ({exc}); using stored data")
        if prices:
            try:
                MarketDataLoader().load(universe)
            except RuntimeError as exc:
                warnings.append(f"price refresh failed ({exc}); using stored prices")
        return warnings

    def _stale_price_warning(self, tickers):
        limit = self._config.stale_price_days
        stale = sum(1 for t in tickers
                    if (self._db.market_age_days(t) is None or self._db.market_age_days(t) > limit))
        if stale and stale / len(tickers) > 0.2:
            return f"prices are stale (older than {limit} days) for {stale} of {len(tickers)} tickers"
        return None

    def run(self, watchlist, *, refresh=True, prices=True, discover=True, send=True,
            dry_run=False, force=False, today=None):
        """Returns a process exit code: 0 = done (or already sent today), 1 = failed.

        Safety net: if anything unexpected goes wrong, you get a short FAILED notification instead
        of silence (a missing morning message is the worst way to find out). Nothing is recorded
        as sent, so a later run the same day can still deliver the real message."""
        try:
            return self._run(watchlist, refresh=refresh, prices=prices, discover=discover,
                             send=send, dry_run=dry_run, force=force, today=today)
        except Exception as exc:
            traceback.print_exc()
            if send and not dry_run:
                try:
                    self._notifier.send(
                        "Stock screen FAILED",
                        f"The morning job crashed: {type(exc).__name__}: {exc}\n\nSee data/daily.log.",
                        priority=4, tags="warning")
                except Exception:
                    pass
            return 1

    def _run(self, watchlist, *, refresh, prices, discover, send, dry_run, force, today):
        today = today or date.today()
        run_date = today.isoformat()

        if send and not dry_run and not force:
            existing = self._db.get_run(run_date)
            if existing and existing["sent_at"]:
                print(f"Already sent today's message ({existing['sent_at']}). Use --force to resend.")
                return 0

        warnings = self._refresh_market(watchlist, today, discover) if refresh else []
        universe, sources = Discovery().universe(watchlist, today)
        if not universe:
            print("Nothing to screen: tickers.txt is empty and Yahoo discovery found nothing.")
            return 1
        if refresh:
            warnings += self._refresh_data(universe, prices)
        if not send:
            return 0

        passers, near, no_data = self._screener.screen(universe)
        errors = self._screener.last_errors
        if errors:
            print("Could not evaluate:\n  " + "\n  ".join(errors))
            warnings.append(f"{len(errors)} tickers could not be evaluated (see log)")
        if len(no_data) / len(universe) > 0.25:
            warnings.append(f"{len(no_data)} of {len(universe)} tickers had no usable filings data "
                            "(ADRs and banks are normal; many more than that suggests a data problem)")
        stale = self._stale_price_warning(universe)
        if stale:
            warnings.append(stale)

        report = self._report.build(
            passers, near, total=len(universe),
            previous=self._db.latest_run_before(run_date), today=today, warnings=warnings,
            overview_lines=MarketOverview().lines(MarketOverview().latest(), today),
            sources=sources)

        if dry_run:
            print(f"--- DRY RUN (nothing sent) ---\nTitle: {report.title}\n"
                  f"Priority: {report.priority}\n\n{report.body}")
            return 0

        try:
            self._notifier.send(report.title, report.body, priority=report.priority)
        except (requests.RequestException, RuntimeError) as exc:
            print(f"Could not send message: {exc}")     # nothing saved, so a rerun can retry
            return 1

        self._db.save_run(run_date, report.passers,
                          datetime.now(timezone.utc).isoformat(timespec="seconds"))
        Discovery().complete_batch()
        print(f"Sent: {report.title}")
        return 0
