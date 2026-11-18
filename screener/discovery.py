"""Stock discovery: official US listings plus Yahoo candidate screens."""

from datetime import timedelta

from screener.config import Config
from screener.database import Database
from screener.market_client import MarketDataClient
from screener.singleton import SingletonMeta

SECTORS = (
    "Technology", "Healthcare", "Financial Services",
    "Consumer Cyclical", "Consumer Defensive", "Energy",
    "Industrials", "Basic Materials", "Utilities",
    "Real Estate", "Communication Services",
)

BATCH_SIZE = 250


class Discovery(metaclass=SingletonMeta):
    def __init__(self):
        self._config = Config()
        self._db = Database()
        self._client = MarketDataClient()
        self._pending_position = None

    def refresh(self, today):
        """Refresh official listings and Yahoo discovery candidates."""
        cfg = self._config
        cutoff = (today - timedelta(days=cfg.discovery_keep_days)).isoformat()

        # Preserve sources already recorded during the retention period.
        existing = dict(self._db.universe_since(cutoff))
        found = {}

        def record(symbol, source):
            symbol = str(symbol).strip().upper()
            if not symbol:
                return
            labels = set(existing.get(symbol, "").split(","))
            labels.discard("")
            labels.update(found.get(symbol, set()))
            labels.add(source)
            found[symbol] = labels

        warnings = []
        official_symbols = None

        # Official Nasdaq, NYSE and S&P 500 listings.
        try:
            official = self._client.listed_symbols()
            official_symbols = set(official)
            for symbol in official:
                record(symbol, "official listings")
            print(f"Official listings added: {len(official)}")
        except Exception as exc:
            warnings.append(f"Official stock listings failed: {exc}")

        # Yahoo discovery screens.
        jobs = [
            (name, lambda n=name: self._client.predefined(
                n, cfg.discovery_predefined_size
            ))
            for name in cfg.discovery_screens
        ]

        if cfg.discovery_sweep:
            jobs += [
                (f"sweep:{sector}", lambda s=sector: self._client.sweep(
                    s, cfg.discovery_per_sector
                ))
                for sector in SECTORS
            ]

        attempted = failed = 0

        for label, job in jobs:
            attempted += 1
            try:
                for symbol in job():
                    record(symbol, label)
            except Exception as exc:
                failed += 1
                print(f"Discovery warning ({label}): {exc}")

        if attempted and failed == attempted:
            warnings.append("Yahoo discovery failed; using official and stored listings")
        elif failed:
            warnings.append(
                f"{failed} of {attempted} Yahoo screens failed"
            )

        # Save each ticker once with all its known sources.
        for symbol, labels in found.items():
            self._db.upsert_universe(
                symbol, ",".join(sorted(labels)), today.isoformat()
            )

        if official_symbols is not None:
            removed = self._db.reconcile_official_listings(official_symbols)
            print(f"Obsolete official listings removed: {removed}")

        print(f"Discovery database updated: {len(found)} symbols")
        return warnings

    def complete_batch(self):
        """Save batch progress after the daily job succeeds."""
        if self._pending_position is not None:
            self._db.set_discovery_position(self._pending_position)
            self._pending_position = None

    def universe(self, watchlist, today):
        """Return the next batch of stocks and their discovery sources."""
        sources = {t: "watchlist" for t in watchlist}

        if self._config.discovery_enabled:
            cutoff = (
                today - timedelta(days=self._config.discovery_keep_days)
            ).isoformat()

            for ticker, found_by in self._db.universe_since(cutoff):
                sources.setdefault(ticker, found_by)

        tickers = list(sources)

        if not tickers:
            return [], {}

        # Rotate through the full universe, processing only one batch.
        position = self._db.get_discovery_position() % len(tickers)
        count = min(BATCH_SIZE, len(tickers))

        batch = [
            tickers[(position + i) % len(tickers)]
            for i in range(count)
        ]

        next_position = (position + count) % len(tickers)
        self._pending_position = next_position

        batch_sources = {ticker: sources[ticker] for ticker in batch}

        print(
            f"Screening batch: {count} stocks out of {len(tickers)} "
            f"total; next position: {next_position}"
        )

        return batch, batch_sources
