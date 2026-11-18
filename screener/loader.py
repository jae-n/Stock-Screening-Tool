"""FundamentalsLoader singleton: orchestrates client -> parser -> database."""

import requests

from screener.config import Config
from screener.database import Database
from screener.edgar_client import EdgarClient
from screener.facts_parser import FactsParser
from screener.singleton import SingletonMeta


class FundamentalsLoader(metaclass=SingletonMeta):
    def __init__(self):
        self._config = Config()
        self._client = EdgarClient()
        self._parser = FactsParser()
        self._db = Database()

    def load(self, tickers, max_age_days=None):
        """Fetch and store each ticker. If max_age_days is set, tickers fetched more recently
        than that are skipped (filings only change quarterly). Returns tickers stored.

        Raises RuntimeError if the SEC can't be reached, so callers stop early instead of
        waiting out a timeout for every remaining ticker."""
        stored = skipped = failures = 0
        total = len(tickers)
        for i, ticker in enumerate(tickers, 1):
            if max_age_days is not None:
                age = self._db.company_age_days(ticker)
                if (age is not None and age < max_age_days
                        and (not self._config.store_pit or self._db.has_pit(ticker))):
                    skipped += 1
                    continue
            tag = f"[{i}/{total}] {ticker}"
            try:
                found = self._client.lookup(ticker)
            except requests.RequestException as exc:
                raise RuntimeError(f"could not reach the SEC ({exc})") from exc
            if found is None:
                print(f"{tag}: not found in SEC ticker list, skipping")
                continue
            cik, name = found
            try:
                facts = self._client.company_facts(cik)
            except requests.RequestException as exc:
                failures += 1
                print(f"{tag}: network error: {exc}")
                if failures >= self._config.sec_max_failures:
                    raise RuntimeError(f"the SEC is unreachable ({failures} failures in a row)") from exc
                continue
            failures = 0
            if facts is None:
                print(f"{tag}: no XBRL data, skipping")
                continue
            pit = self._parser.to_pit_rows(ticker, facts) if self._config.store_pit else None
            count = self._db.store_company(ticker, cik, name, self._parser.to_rows(ticker, facts), pit)
            self._client.discard_facts(cik)
            print(f"{tag} ({name}): stored {count} data points")
            stored += 1
        if skipped:
            print(f"{skipped} tickers already fresh (< {max_age_days} days old), skipped")
        return stored
