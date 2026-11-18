"""Convert SEC companyfacts JSON into normalized annual/quarterly metric rows.

SEC XBRL tags differ between issuers. This parser uses ordered US-GAAP aliases and
keeps the latest filed observation for each period. Values are USD unless noted.
"""
from datetime import date

ALIASES = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "Revenues", "SalesRevenueGoodsNet"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "depreciation_amortization": ["DepreciationDepletionAndAmortization", "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment", "DepreciationAmortizationAndAccretionNet"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "debt_current": ["ShortTermBorrowings", "LongTermDebtCurrent", "ShortTermDebtAndCurrentPortionOfLongTermDebt"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "cash_and_st_investments": ["CashCashEquivalentsAndShortTermInvestments"],
    "short_term_investments": ["ShortTermInvestments", "MarketableSecuritiesCurrent"],
    "interest_expense": ["InterestExpenseNonOperating", "InterestAndDebtExpense", "InterestExpenseDebt"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}

class FactsParser:
    def __init__(self):
        self._tag_map = {tag: metric for metric, tags in ALIASES.items() for tag in tags}

    @staticmethod
    def _facts(facts):
        return facts.get("facts", {}).get("us-gaap", {})

    def _rows(self, ticker, facts):
        out = []
        for tag, spec in self._facts(facts).items():
            metric = self._tag_map.get(tag)
            if not metric:
                continue
            units = spec.get("units", {})
            for unit, observations in units.items():
                for item in observations:
                    end = item.get("end")
                    filed = item.get("filed")
                    if not end or not filed:
                        continue
                    form = item.get("form", "")
                    if form not in ("10-K", "10-K/A", "20-F", "40-F", "10-Q", "10-Q/A"):
                        continue
                    val = item.get("val")
                    if not isinstance(val, (int, float)):
                        continue
                    start = item.get("start")
                    duration_days = (date.fromisoformat(end) - date.fromisoformat(start)).days if start else 0
                    # Balance sheet facts are instants; income/cash-flow facts are durations.
                    is_instant = start is None
                    if is_instant:
                        ptype = "annual" if form in ("10-K", "10-K/A", "20-F", "40-F") else "quarterly"
                    elif duration_days >= 330:
                        ptype = "annual"
                    elif 130 <= duration_days <= 320:
                        ptype = "ytd"
                    else:
                        ptype = "quarterly"
                    fy = item.get("fy")
                    fp = item.get("fp")
                    out.append({"ticker": ticker, "metric": metric, "period_type": ptype,
                                "period_end": end, "value": float(val), "unit": unit,
                                "form": form, "filed": filed, "fy": fy, "fp": fp,
                                "duration_days": duration_days, "start": start})
        return out

    def to_rows(self, ticker, facts):
        """Return SQL-ready tuples in Database.store_company column order."""
        raw = self._rows(ticker, facts)
        chosen = {}
        for r in raw:
            key = (r["metric"], r["period_type"], r["period_end"])
            prev = chosen.get(key)
            if prev is None or r["filed"] > prev["filed"]:
                chosen[key] = r
        return [(r["ticker"], r["metric"], r["period_type"], r["period_end"], r["value"],
                 r["unit"], r["form"], r["filed"], r["fy"], r["fp"]) for r in chosen.values()]

    def to_pit_rows(self, ticker, facts):
        return [(r["ticker"], r["metric"], r["period_type"], r["period_end"], r["filed"],
                 r["value"], r["unit"], r["fp"]) for r in self._rows(ticker, facts)]
