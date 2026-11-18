"""EdgarClient singleton: the only code that talks to the SEC."""

import json
import time

import requests

from screener.config import Config
from screener.singleton import SingletonMeta

TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


class EdgarClient(metaclass=SingletonMeta):
    def __init__(self):
        self._config = Config()
        self._session = None
        self._last_call = 0.0
        self._ticker_map = None

    @property
    def session(self):
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": self._config.require_user_agent(),
                "Accept-Encoding": "gzip, deflate",
            })
        return self._session

    def _get_json(self, url, cache_name):
        cache_dir = self._config.cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / cache_name

        if not self._config.refresh and path.exists():
            age_hours = (time.time() - path.stat().st_mtime) / 3600
            if age_hours < self._config.cache_hours:
                return json.loads(path.read_text())

        wait = self._config.min_interval - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        resp = self.session.get(url, timeout=30)
        self._last_call = time.time()

        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        path.write_text(json.dumps(data))
        return data

    def lookup(self, ticker):
        """Return (cik, company_name) or None if the ticker isn't in the SEC list."""
        if self._ticker_map is None:
            raw = self._get_json(TICKER_URL, "company_tickers.json")
            self._ticker_map = {
                row["ticker"].upper(): (int(row["cik_str"]), row["title"])
                for row in raw.values()
            }
        return self._ticker_map.get(ticker.upper())

    def company_facts(self, cik):
        return self._get_json(FACTS_URL.format(cik=cik), f"facts_{cik:010d}.json")

    def discard_facts(self, cik):
        """Delete the raw JSON for one company (the parsed data is already in the database)."""
        if not self._config.keep_raw_cache:
            (self._config.cache_dir / f"facts_{cik:010d}.json").unlink(missing_ok=True)

    def close(self):
        if self._session is not None:
            self._session.close()
            self._session = None
