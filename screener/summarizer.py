"""Summarizer singleton: derived ratios, a starting point for the scoring engine."""

from datetime import date

from screener.database import Database
from screener.singleton import SingletonMeta


class Summarizer(metaclass=SingletonMeta):
    def __init__(self):
        self._db = Database()

    @staticmethod
    def cagr(series, max_years=5):
        points = sorted(series.items())
        if len(points) < 2:
            return None
        last_end, last_val = points[-1]
        first_end, first_val = points[max(0, len(points) - 1 - max_years)]
        years = (date.fromisoformat(last_end) - date.fromisoformat(first_end)).days / 365.25
        if years < 1 or first_val <= 0 or last_val <= 0:
            return None
        return (last_val / first_val) ** (1 / years) - 1

    def adjusted_eps(self, ticker, annual=None):
        """Diluted EPS per fiscal year restated to today's share count (needs split data
        from --prices; without it nothing is adjusted)."""
        annual = annual if annual is not None else self._db.annual_rows(ticker)
        return {end: value / self._db.split_factor_after(ticker, filed)
                for end, (value, filed) in annual.get("eps_diluted", {}).items()}

    def summarize(self, ticker):
        """Return a dict of latest-year ratios, or None if no revenue data exists."""
        annual = self._db.annual_rows(ticker)
        data = {m: {e: v for e, (v, _f) in s.items()} for m, s in annual.items()}
        revenue = data.get("revenue")
        if not revenue:
            return None
        end = max(revenue)

        def at(metric):
            return data.get(metric, {}).get(end)

        net_income, equity, debt = at("net_income"), at("equity"), at("long_term_debt")
        op_cash, capex = at("operating_cash_flow"), at("capex")

        per_revenue = lambda x: x / revenue[end] if x is not None and revenue[end] else None
        return {
            "fiscal_year_end": end,
            "revenue_b": revenue[end] / 1e9,
            "rev_cagr_5y": self.cagr(revenue),
            "eps_cagr_5y": self.cagr(self.adjusted_eps(ticker, annual)),
            "net_margin": per_revenue(net_income),
            "roe": net_income / equity if net_income is not None and equity and equity > 0 else None,
            "debt_to_equity": debt / equity if debt is not None and equity and equity > 0 else None,
            "fcf_margin": (per_revenue(op_cash - abs(capex))
                           if op_cash is not None and capex is not None else None),
        }
