"""MarketOverview singleton: a broad sense of the market for the morning message.

Index levels and trend, volatility (VIX), the 10-year yield, and which sectors have been
strongest and weakest over the past month. Context only: nothing here changes what passes
the screen.
"""

import time
from datetime import timedelta

from screener.config import Config
from screener.database import Database
from screener.market_client import MarketDataClient
from screener.singleton import SingletonMeta

INDICES = (("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq"), ("^DJI", "Dow"), ("^RUT", "Russell 2000"))
VIX, TNX = "^VIX", "^TNX"
SECTOR_ETFS = {          # SPDR sector funds -> the sector names Yahoo's screens use
    "XLK": "Technology", "XLV": "Healthcare", "XLF": "Financial Services",
    "XLY": "Consumer Cyclical", "XLP": "Consumer Defensive", "XLE": "Energy",
    "XLI": "Industrials", "XLB": "Basic Materials", "XLU": "Utilities",
    "XLRE": "Real Estate", "XLC": "Communication Services",
}


def _pct(v):
    return "n/a" if v is None else f"{v * 100:+.1f}%"


class MarketOverview(metaclass=SingletonMeta):
    def __init__(self):
        self._config = Config()
        self._db = Database()
        self._client = MarketDataClient()

    @staticmethod
    def stats(closes):
        """Summary numbers from [(date, close)] oldest first, or None if too short."""
        if len(closes) < 2:
            return None
        dates, vals = [d for d, _ in closes], [c for _, c in closes]
        last, year = vals[-1], dates[-1][:4]
        base = next((v for d, v in reversed(closes) if d[:4] < year), vals[0])   # prior year's last close
        return {
            "as_of": dates[-1],
            "last": last,
            "day": last / vals[-2] - 1,
            "month": last / vals[-22] - 1 if len(vals) >= 22 else None,          # ~21 trading days
            "ytd": last / base - 1,
            "from_high": last / max(vals) - 1,
            "above_200d": last > sum(vals[-200:]) / 200 if len(vals) >= 200 else None,
        }

    def _fetch(self, symbol):
        try:
            return self.stats(self._client.closes(symbol, "1y"))
        except Exception:
            return None
        finally:
            time.sleep(self._config.market_pause)

    def refresh(self, today):
        """Download and store a fresh snapshot. Returns warnings; never raises."""
        indices = []
        for symbol, name in INDICES:
            s = self._fetch(symbol)
            if s:
                indices.append({"name": name, "symbol": symbol, **s})
        vix = self._fetch(VIX)
        tnx = self._fetch(TNX)
        sectors = []
        for etf, name in SECTOR_ETFS.items():
            s = self._fetch(etf)
            if s and s["month"] is not None:
                sectors.append({"name": name, "month": s["month"], "day": s["day"]})

        if not indices and not sectors and not vix:
            return ["market overview unavailable; message sent without it"]

        tnx_value = None
        if tnx:
            tnx_value = tnx["last"] / 10 if tnx["last"] > 20 else tnx["last"]   # older feeds quote yield x10
        payload = {
            "as_of": indices[0]["as_of"] if indices else today.isoformat(),
            "indices": indices,
            "vix": vix["last"] if vix else None,
            "tnx": tnx_value,
            "sectors": sectors,
        }
        self._db.save_overview(today.isoformat(), payload)
        missing = len(INDICES) - len(indices)
        return [f"{missing} market indices could not be fetched"] if missing else []

    def latest(self):
        return self._db.latest_overview()

    @staticmethod
    def _vix_label(vix):
        return "calm" if vix < 15 else "normal" if vix < 25 else "elevated" if vix < 35 else "high stress"

    def lines(self, payload, today=None):
        """Message lines for a stored snapshot (empty list if there is none)."""
        if not payload:
            return []
        out = ["MARKET"]
        for ix in payload["indices"]:
            high = ("at its high" if ix["from_high"] > -0.005
                    else f"{abs(ix['from_high']) * 100:.1f}% below high")
            trend = {True: ", above 200-day avg", False: ", below 200-day avg", None: ""}[ix["above_200d"]]
            out.append(f"{ix['name']} {ix['last']:,.0f}: {_pct(ix['day'])} day, "
                       f"{_pct(ix['month'])} month, {high}{trend}")
        extras = []
        if payload.get("vix") is not None:
            extras.append(f"VIX {payload['vix']:.1f} ({self._vix_label(payload['vix'])})")
        if payload.get("tnx") is not None:
            extras.append(f"10-yr yield {payload['tnx']:.2f}%")
        if extras:
            out.append("; ".join(extras))
        sectors = sorted(payload.get("sectors", []), key=lambda s: s["month"], reverse=True)
        if len(sectors) >= 4:
            best = ", ".join(f"{s['name']} {_pct(s['month'])}" for s in sectors[:2])
            worst = ", ".join(f"{s['name']} {_pct(s['month'])}" for s in sectors[-2:][::-1])
            out.append(f"Sectors, 1 month: best {best} | weakest {worst}")
        if today and payload["as_of"] < (today - timedelta(days=3)).isoformat():
            out.append(f"(market data is from {payload['as_of']})")
        return out
