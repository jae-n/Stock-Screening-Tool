"""QualityCalculator singleton: measures durable advantage (moat proxy) and debt load.

A moat can't be read from financial statements, but its *results* can: a business with a
real advantage earns high returns on capital year after year, with stable margins and
positive free cash flow. That is what this measures.

Approximations:
  * Debt, cash, EBITDA and interest coverage use the latest quarter's balance sheet and
    trailing-12-month flows when 10-Q data allows (Config.use_ttm); ROIC uses fiscal years.
  * Cash includes short-term investments (marketable securities).
  * ROIC = operating income x (1 - tax_rate) / (equity + debt - cash)
  * Missing debt tags + negligible interest expense => assumed debt-free (flagged).
    Missing debt tags + material interest expense => debt UNKNOWN (screen fails it).
"""

from statistics import mean, pstdev

from screener.config import Config
from screener.database import Database
from screener.metrics import effective_cash
from screener.singleton import SingletonMeta
from screener.summarizer import Summarizer
from screener.ttm import TTMCalculator

FIELDS = {
    "revenue": "revenue", "gross_profit": "gross_profit", "op_income": "operating_income",
    "da": "depreciation_amortization", "ocf": "operating_cash_flow", "capex": "capex",
    "equity": "equity", "debt": "long_term_debt", "debt_current": "debt_current",
    "cash": "cash", "cash_agg": "cash_and_st_investments", "st_inv": "short_term_investments",
    "interest": "interest_expense",
}


class QualityCalculator(metaclass=SingletonMeta):
    def __init__(self):
        self._config = Config()
        self._db = Database()
        self._ttm = TTMCalculator()

    @staticmethod
    def _vals(annual, end):
        v = {key: (annual.get(metric, {}).get(end) or (None, None))[0]
             for key, metric in FIELDS.items()}
        v["cash"] = effective_cash(v["cash"], v.pop("cash_agg"), v.pop("st_inv"))
        return v

    @staticmethod
    def _invested_capital(v):
        if v["equity"] is None:
            return None
        return v["equity"] + (v["debt"] or 0) + (v["debt_current"] or 0) - (v["cash"] or 0)

    def compute(self, ticker):
        annual = self._db.annual_rows(ticker)
        revenue_rows = annual.get("revenue")
        if not revenue_rows:
            return None
        cfg = self._config
        ends = sorted(revenue_rows)[-cfg.moat_years:]

        roics, op_margins, gross_margins, fcf_flags = [], [], [], []
        for end in ends:
            v = self._vals(annual, end)
            capital = self._invested_capital(v)
            if v["op_income"] is not None:
                if v["revenue"]:                       # pre-revenue companies report 0
                    op_margins.append(v["op_income"] / v["revenue"])
                if capital and capital > 0:
                    roics.append(v["op_income"] * (1 - cfg.tax_rate) / capital)
            if v["gross_profit"] is not None and v["revenue"]:
                gross_margins.append(v["gross_profit"] / v["revenue"])
            if v["ocf"] is not None and v["capex"] is not None:
                fcf_flags.append(v["ocf"] - abs(v["capex"]) > 0)

        # ---- balance sheet: latest quarter, with trailing-12-month flows ----
        snap = self._ttm.snapshot(ticker)
        i = snap["inputs"]
        assumed_zero = False
        debt_total = None
        if i["debt"] is None and i["debt_current"] is None:
            interest = i["interest"]
            if interest is None or (i["revenue"] is not None and interest <= 0.005 * i["revenue"]):
                debt_total, assumed_zero = 0.0, True
        else:
            debt_total = (i["debt"] or 0) + (i["debt_current"] or 0)

        net_debt_to_ebitda = debt_to_equity = interest_coverage = None
        if debt_total is not None:
            net_debt = debt_total - (i["cash"] or 0)
            ebitda = i["op_income"] + (i["da"] or 0) if i["op_income"] is not None else None
            if ebitda and ebitda > 0:
                net_debt_to_ebitda = net_debt / ebitda
            elif net_debt <= 0:
                net_debt_to_ebitda = 0.0
            if debt_total == 0:
                debt_to_equity = 0.0
            elif i["equity"] and i["equity"] > 0:
                debt_to_equity = debt_total / i["equity"]
            if debt_total > 0 and i["interest"] and i["interest"] > 0 and i["op_income"] is not None:
                interest_coverage = i["op_income"] / i["interest"]

        return {
            "fiscal_year_end": ends[-1],
            "basis": snap["basis"],
            "flows_as_of": snap["as_of"],
            "balance_as_of": snap["balance_as_of"],
            "roic_years": len(roics),
            "avg_roic": mean(roics) if len(roics) >= 3 else None,
            "roic_consistency": (sum(r >= cfg.roic_floor for r in roics) / len(roics)
                                 if len(roics) >= 3 else None),
            "op_margin_stdev": pstdev(op_margins) if len(op_margins) >= 3 else None,
            "gross_margin_avg": mean(gross_margins) if gross_margins else None,
            "fcf_positive_all": all(fcf_flags) if len(fcf_flags) >= 3 else None,
            "rev_cagr": Summarizer.cagr({e: revenue_rows[e][0] for e in ends}, max_years=cfg.moat_years),
            "debt_total": debt_total,
            "debt_assumed_zero": assumed_zero,
            "net_debt_to_ebitda": net_debt_to_ebitda,
            "debt_to_equity": debt_to_equity,
            "interest_coverage": interest_coverage,
        }
