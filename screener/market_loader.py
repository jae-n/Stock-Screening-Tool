"""MarketDataLoader singleton: orchestrates market client -> database."""

import time

from screener.config import Config
from screener.database import Database
from screener.market_client import MarketDataClient
from screener.singleton import SingletonMeta


class MarketDataLoader(metaclass=SingletonMeta):
    def __init__(self):
        self._config = Config()
        self._client = MarketDataClient()
        self._db = Database()

    def _trip(self, failures):
        if failures >= self._config.yahoo_max_failures:
            raise RuntimeError(f"Yahoo is unreachable or rate-limiting ({failures} failures in a row)")

    def load(self, tickers):
        """Fetch price, sector, forward EPS, price history and splits for each ticker that has
        filings data (no point pricing a company we can't evaluate). Raises RuntimeError if Yahoo
        fails repeatedly, so callers stop hammering it."""
        stored = skipped = failures = 0
        total = len(tickers)
        for i, ticker in enumerate(tickers, 1):
            if not self._db.has_company(ticker):
                skipped += 1
                continue
            tag = f"[{i}/{total}] {ticker}"
            try:
                snapshot, closes, splits = self._client.fetch(ticker)
            except RuntimeError:
                raise                                   # e.g. yfinance missing: stop early
            except Exception as exc:                    # yfinance raises many error types
                failures += 1
                print(f"{tag}: market data error: {exc}")
                self._trip(failures)
                time.sleep(self._config.market_pause)
                continue
            if not snapshot.get("price"):
                failures += 1
                print(f"{tag}: no price returned, skipping")
                self._trip(failures)
                time.sleep(self._config.market_pause)
                continue
            failures = 0
            self._db.store_market(ticker, snapshot, closes, splits)
            print(f"{tag}: price {snapshot['price']:.2f}, sector {snapshot.get('sector')}, "
                  f"{len(closes)} months, {len(splits)} splits")
            stored += 1
            time.sleep(self._config.market_pause)
        if skipped:
            print(f"{skipped} tickers skipped (no filings data, e.g. foreign ADRs or preferreds)")
        return stored
