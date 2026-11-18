"""Config singleton: one place for every setting."""

import os
from pathlib import Path

from screener.singleton import SingletonMeta


class Config(metaclass=SingletonMeta):
    """Holds runtime settings. Call configure() once at startup, before other
    singletons are first used (they read these values lazily)."""

    def __init__(self):
        self.db_path = os.environ.get("DB_PATH", "data/stocks.db")
        self.cache_dir = Path(os.environ.get("CACHE_DIR", "data/edgar_cache"))
        self.cache_hours = 20
        self.min_interval = 0.2          # seconds between SEC requests (limit is ~10/sec)
        self.user_agent = os.environ.get("SEC_USER_AGENT", "").strip()
        self.refresh = False             # True = ignore the on-disk JSON cache
        self.keep_raw_cache = False      # False = delete each company's raw SEC JSON once parsed (saves ~1 GB)
        self.sec_max_failures = 5        # consecutive SEC failures before giving up for this run
        self.yahoo_max_failures = 10     # same for Yahoo (it rate-limits aggressively)

        # Market data / valuation
        self.use_ttm = True              # trailing-12-month flows + latest quarter balance sheet
        self.price_history_years = 11    # monthly closes to download
        self.hist_compare_years = 5      # fiscal years used for "vs own history"
        self.min_hist_points = 3         # need at least this many past years to compare
        self.min_sector_peers = 3        # need at least this many peers for "vs sector"
        self.market_pause = 1.0          # seconds between Yahoo requests (be gentle)

        # ---- Screen: "undervalued + durable advantage + little debt" ----
        # Debt (latest fiscal year)
        self.max_net_debt_to_ebitda = 2.0    # net cash always passes
        self.max_debt_to_equity = 0.5
        self.min_interest_coverage = 8.0     # operating income / interest expense
        # Advantage ("moat" proxy): persistently high returns on capital
        self.moat_years = 5                  # fiscal years examined
        self.tax_rate = 0.21                 # used to estimate after-tax operating profit
        self.min_avg_roic = 0.15
        self.roic_floor = 0.10               # a year "counts" if ROIC is at least this
        self.min_roic_consistency = 0.80     # share of years that must meet roic_floor
        self.min_rev_cagr = 0.0              # value-trap guard: revenue must not be shrinking
        # Undervaluation (median of P/E, P/FCF, EV/EBITDA relative to benchmark)
        self.max_rel_history = 0.90          # at least 10% cheaper than its own history
        self.max_rel_sector = 1.00           # no pricier than sector peers
        self.require_sector = False          # True = fail when too few sector peers
        self.min_fcf_yield = 0.04
        # Ranking weights among stocks that pass every gate
        self.weight_value = 0.40
        self.weight_moat = 0.35
        self.weight_debt = 0.25

        # ---- Daily morning alert (ntfy push notification) ----
        self.ntfy_server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").strip().rstrip("/")
        self.ntfy_topic = os.environ.get("NTFY_TOPIC", "").strip()
        self.ntfy_token = os.environ.get("NTFY_TOKEN", "").strip()    # only if your server needs auth
        self.alert_top_n = 5                  # picks shown in the message
        self.alert_near_misses = 3            # close misses shown in the message
        self.fundamentals_max_age_days = 3    # filings change quarterly, so don't refetch daily
        self.stale_price_days = 2             # warn in the message if prices are older than this

        # ---- Discovery: broad stock discovery ----
        self.discovery_enabled = True
        self.discovery_screens = ["undervalued_large_caps", "undervalued_growth_stocks"]
        self.discovery_predefined_size = 50
        self.discovery_sweep = True
        self.discovery_per_sector = 30
        self.discovery_max = 1000
        self.discovery_keep_days = 30
        self.discovery_min_cap = 3e8
        self.discovery_max_pe = 50
        self.discovery_min_roe = 5
        self.discovery_max_de_pct = 200

        # ---- Backtest ----
        self.store_pit = False                # keep every filed version of every number (needed for backtests)
        self.backtest_start = "2019-12"       # first rebalance month (needs ~5 earlier fiscal years of filings)
        self.backtest_step_months = 3         # re-run the screen every N months
        self.backtest_horizons = (12, 24, 36) # months each pick is held
        self.backtest_benchmark = "SPY"       # S&P 500 fund; its adjusted price includes dividends
        self.backtest_min_picks = 1           # ignore dates where fewer stocks than this pass
        self.backtest_price_years = 20        # monthly price history to download

    def configure(self, **overrides):
        """Apply overrides; None values are ignored so argparse defaults are safe to pass."""
        for key, value in overrides.items():
            if not hasattr(self, key):
                raise AttributeError(f"Unknown config option: {key}")
            if value is not None:
                setattr(self, key, Path(value) if key == "cache_dir" else value)
        return self

    def require_user_agent(self):
        if "@" not in self.user_agent:
            raise RuntimeError(
                'Set SEC_USER_AGENT, e.g. export SEC_USER_AGENT="Your Name you@example.com"'
            )
        return self.user_agent

    def require_ntfy(self):
        if not self.ntfy_topic:
            raise RuntimeError("Set NTFY_TOPIC, e.g. export NTFY_TOPIC=some-long-random-string")
