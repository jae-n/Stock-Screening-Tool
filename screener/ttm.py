"""Build a latest-quarter balance sheet plus trailing-twelve-month income/cash flows."""
from screener.database import Database
from screener.singleton import SingletonMeta

FLOW = {"revenue", "operating_income", "depreciation_amortization", "operating_cash_flow", "capex", "interest_expense"}
BALANCE = {"equity", "long_term_debt", "debt_current", "cash", "cash_and_st_investments", "short_term_investments"}

class TTMCalculator(metaclass=SingletonMeta):
    def __init__(self): self._db = Database()

    @staticmethod
    def _quarterly_values(qseries, ytdseries, annualseries):
        """Reconstruct discrete fiscal quarters from SEC quarterly/YTD/annual facts."""
        out = {}
        # Q1 observations are generally standalone three-month values.
        for end, (value, filed, fp) in qseries.items():
            if value is not None and fp == "Q1": out[end] = value
        # Q2/Q3 YTD values become individual quarters by subtracting the prior YTD.
        ytd_by_year = {}
        for end, (value, filed, fp) in sorted(qseries.items()):
            if fp == "Q1" and value is not None:
                ytd_by_year[(end[:4], "Q1")] = value
        for end, (value, filed, fp) in sorted(ytdseries.items()):
            if value is None: continue
            year = end[:4]
            if fp == "Q2":
                prev = ytd_by_year.get((year, "Q1"))
                if prev is not None: out[end] = value - prev
                ytd_by_year[(year, "Q2")] = value
            elif fp == "Q3":
                prev = ytd_by_year.get((year, "Q2"))
                if prev is not None: out[end] = value - prev
                ytd_by_year[(year, "Q3")] = value
            elif fp == "Q1":
                ytd_by_year[(year, "Q1")] = value
        # Q4 = full-year value minus first nine months (when both are present).
        for end, (value, filed) in annualseries.items():
            q3 = ytd_by_year.get((end[:4], "Q3"))
            if q3 is not None: out[end] = value - q3
        return out

    def snapshot(self, ticker):
        annual = self._db.annual_rows(ticker)
        quarterly = self._db.period_rows(ticker, "quarterly")
        ytd = self._db.period_rows(ticker, "ytd")
        # Prefer latest quarterly instant values for balance sheet; fall back to annual.
        inputs = {}
        balance_end = None
        for metric in BALANCE:
            series = quarterly.get(metric, {})
            if series:
                end = max(series)
                inputs[metric] = series[end][0]
                balance_end = max(balance_end or end, end)
            else:
                a = annual.get(metric, {})
                inputs[metric] = a[max(a)][0] if a else None

        inputs["debt"] = inputs.get("long_term_debt")
        # Flow metrics: add the latest four discrete quarters where possible; otherwise annual.
        flow_ends = []
        for metric in FLOW:
            qseries = quarterly.get(metric, {})
            yseries = ytd.get(metric, {})
            aseries = annual.get(metric, {})
            vals = self._quarterly_values(qseries, yseries, aseries)
            keys = sorted(vals)[-4:]
            if len(keys) == 4:
                inputs[metric] = sum(vals[k] for k in keys)
                flow_ends.extend(keys)
            else:
                inputs[metric] = aseries[max(aseries)][0] if aseries else None
        # Interest may be tagged only in YTD records. Prefer latest annual if quarterly absent.
        if inputs.get("interest_expense") is None:
            s = annual.get("interest_expense", {})
            inputs["interest_expense"] = s[max(s)][0] if s else None
        inputs["op_income"] = inputs.get("operating_income")
        inputs["da"] = inputs.get("depreciation_amortization")
        inputs["interest"] = inputs.get("interest_expense")

        return {"inputs": inputs, "basis": "TTM + latest quarterly balance sheet" if flow_ends else "latest annual fallback",
                "as_of": max(flow_ends) if flow_ends else (max((max(v) for v in annual.values() if v), default=None)),
                "balance_as_of": balance_end or max((max(v) for v in annual.values() if v), default=None)}
