"""DailyReport singleton: turns screen results into the morning message."""

from dataclasses import dataclass, field

from screener.config import Config
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

    @staticmethod
    def _pick_lines(rank, r, found_by=None):
        m, sc = r["metrics"], r["scores"]
        nd = m["net_debt_to_ebitda"]
        debt = "net cash" if nd is not None and nd <= 0 else f"{_x(nd)} net debt/EBITDA"
        score = lambda v: "n/a" if v is None else f"{v:.0f}"
        lines = [
            f"{rank}. {r['ticker']}  score {score(r['composite'])} "
            f"(value {score(sc['value'])}, moat {score(sc['moat'])}, debt {score(sc['debt'])})",
            f"   ROIC {_pct(m['avg_roic'])}, {debt}, FCF yield {_pct(m['fcf_yield'])}, "
            f"{_x(m['rel_history'])} of own history",
        ]
        if found_by and found_by != "watchlist":
            lines.append("   found via Yahoo: " + ", ".join(found_by.split(",")[:2]))
        return lines

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
        sources = sources or {}
        cfg = self._config
        current = [r["ticker"] for r in passers]
        new = []
        dropped = []
        title = f"Stock screen {today.strftime('%b %d')}: {len(passers)} pass"
        if new:
            title += f", {len(new)} new"

        lines = list(overview_lines) + ([""] if overview_lines else [])
        lines.append(f"PASSING ALL GATES: {len(passers)} of {total} checked")
        if passers:
            for rank, r in enumerate(passers[:cfg.alert_top_n], 1):
                lines += self._pick_lines(rank, r, sources.get(r['ticker']))
            if len(passers) > cfg.alert_top_n:
                lines.append("+ " + ", ".join(current[cfg.alert_top_n:]))
        else:
            lines.append("None today. The gates are strict, so that is normal.")

        if previous is None:
            lines += ["", "(First message, so nothing is marked new yet.)"]
        if new:
            lines += ["", "NEW: " + ", ".join(new)]
        if dropped:
            lines += ["", "DROPPED:"] + [f"  {t}: {self._why_dropped(t)}" for t in dropped]

        if near:
            lines += ["", "CLOSEST MISSES:"]
            for r in near[:cfg.alert_near_misses]:
                why = "; ".join(f"{n} {r['gates'][n]['detail']}" for n in r["failed"])
                lines.append(f"  {r['ticker']}: {why}")

        for w in warnings:
            lines += ["", f"WARNING: {w}"]
        lines += ["", "Candidates to research, not buy signals."]

        return Report(title=title, body="\n".join(lines), priority=4 if new else 3,
                      passers=current, new=new, dropped=dropped)
