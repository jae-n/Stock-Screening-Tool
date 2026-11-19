"""DailyReport singleton: turns screen results into the morning message."""

from dataclasses import dataclass, field

from screener.config import Config
from screener.database import Database
from screener.singleton import SingletonMeta
from screener.stock_screener import StockScreener


@dataclass
class Report:
    title: str
    body: str
    priority: int
    passers: list = field(default_factory=list)   # tickers that passed every gate
    new: list = field(default_factory=list)
    dropped: list = field(default_factory=list)


def _pct(v):
    return "n/a" if v is None else f"{v * 100:.1f}%"


def _x(v):
    return "n/a" if v is None else f"{v:.2f}x"


class DailyReport(metaclass=SingletonMeta):
    def __init__(self):
        self._config = Config()
        self._screener = StockScreener()
        self._db = Database()

    @staticmethod
    def _pick_lines(self, rank, r, found_by=None):
        m = r["metrics"]
        nd = m["net_debt_to_ebitda"]
        debt = "Net cash" if nd is not None and nd <= 0 else _x(nd)

        name = self._db.company_name(r["ticker"]) or r["ticker"]

        return [
            f"{r['ticker']} — {name}",
            f"{r['composite']:.0f}/100 QUALITY SCORE",
            "",
            f"ROIC: {_pct(m['avg_roic'])}",
            f"FCF yield: {_pct(m['fcf_yield'])}",
            f"Net debt / EBITDA: {debt}",
            f"Historical valuation: {_x(m['rel_history'])}",
        ]
    def _why_dropped(self, ticker):
        r = self._screener.evaluate(ticker)
        if r is None:
            return "no data"
        if not r["failed"]:
            return "no longer ranked"
        name = r["failed"][0]
        return f"{name} {r['gates'][name]['detail']}"

    def build(self, passers, near, total, previous, today, warnings=(),
              overview_lines=(), sources=None):
        cfg = self._config
        current = [r["ticker"] for r in passers]
        new = []
        dropped = []

        title = f"Stock Screen: {len(passers)} found"

        lines = [
            f"{len(passers)} stock{'s' if len(passers) != 1 else ''} found",
            "",
        ]

        if passers:
            for r in passers[:cfg.alert_top_n]:
                lines += self._pick_lines(1, r)
                lines.append("")
            if len(passers) > cfg.alert_top_n:
                lines.append("+ " + ", ".join(current[cfg.alert_top_n:]))
        else:
            lines.append("No stocks passed all screening gates today.")

        lines += [
            "",
            "TODAY'S SCAN",
            f"{total} stocks checked",
            f"{len(passers)} passed all gates",
        ]

        if warnings:
            for w in warnings:
                lines.append(w)

        if near:
            lines += ["", "CLOSEST MISSES"]
            for r in near[:cfg.alert_near_misses]:
                why = "; ".join(
                    f"{n} {r['gates'][n]['detail']}" for n in r["failed"]
                )
                lines.append(f"{r['ticker']}: {why}")

        lines += ["", "Research candidates only — not buy signals."]

        return Report(
            title=title,
            body="\n".join(lines),
            priority=3,
            passers=current,
            new=new,
            dropped=dropped,
        )
