"""Transparent valuation multiples and comparisons with price history/sector peers.

Historical comparisons use today's per-share fundamentals against historical split-adjusted
prices. They are a screening approximation, not a reconstructed historical valuation series.
"""
from statistics import median
from screener.config import Config
from screener.database import Database
from screener.singleton import SingletonMeta

class ValuationCalculator(metaclass=SingletonMeta):
    def __init__(self): self._cfg, self._db = Config(), Database()

    @staticmethod
    def _latest(series):
        return series[max(series)][0] if series else None

    def _fundamentals(self, ticker):
        a = self._db.annual_rows(ticker)
        def v(k): return self._latest(a.get(k, {}))
        rev, ni, ocf, capex = v("revenue"), v("net_income"), v("operating_cash_flow"), v("capex")
        op, da = v("operating_income"), v("depreciation_amortization")
        debt = (v("long_term_debt") or 0) + (v("debt_current") or 0)
        cash = v("cash_and_st_investments")
        if cash is None: cash = (v("cash") or 0) + (v("short_term_investments") or 0)
        fcf = ocf - abs(capex) if ocf is not None and capex is not None else None
        return {"revenue":rev,"net_income":ni,"fcf":fcf,"ebitda":(op+da if op is not None and da is not None else None),
                "debt":debt,"cash":cash or 0}

    @staticmethod
    def _multiples(price, shares, f):
        if not price or not shares: return {}
        equity = price * shares
        ev = equity + f["debt"] - f["cash"]
        eps = f["net_income"] / shares if f["net_income"] and f["net_income"] > 0 else None
        fcfps = f["fcf"] / shares if f["fcf"] and f["fcf"] > 0 else None
        ebitda = f["ebitda"]
        return {"pe": price / eps if eps and eps > 0 else None,
                "p_fcf": price / fcfps if fcfps and fcfps > 0 else None,
                "ev_ebitda": ev / ebitda if ebitda and ebitda > 0 and ev > 0 else None,
                "fcf_yield": f["fcf"] / equity if f["fcf"] is not None and equity > 0 else None}

    def analyze(self, ticker):
        market = self._db.get_market(ticker)
        if not market or not market.get("price"): return None
        shares = market.get("shares_outstanding")
        if not shares or shares <= 0:
            a = self._db.annual_rows(ticker).get("shares_diluted", {})
            shares = self._latest(a)
            if shares and a: shares *= self._db.split_factor_after(ticker, a[max(a)][1])
        if not shares or shares <= 0: return None
        f = self._fundamentals(ticker)
        current = self._multiples(market["price"], shares, f)
        closes = self._db.get_closes(ticker)
        history = []
        for month, price in sorted(closes.items()):
            if price and price > 0:
                m = self._multiples(price, shares, f)
                history.append(m)
        hist_rel = {}
        for key in ("pe", "p_fcf", "ev_ebitda"):
            vals = [x[key] for x in history if x.get(key) and x[key] > 0]
            hist_rel[key] = current.get(key) / median(vals) if current.get(key) and len(vals) >= self._cfg.min_hist_points else None
        peers = self._db.tickers_in_sector(market.get("sector")) if market.get("sector") else []
        peer_values = {k: [] for k in ("pe", "p_fcf", "ev_ebitda")}
        for peer in peers:
            if peer == ticker: continue
            pm = self._db.get_market(peer)
            if not pm: continue
            ps = pm.get("shares_outstanding")
            if not ps: continue
            vals = self._multiples(pm.get("price"), ps, self._fundamentals(peer))
            for k in peer_values:
                if vals.get(k) and vals[k] > 0: peer_values[k].append(vals[k])
        sector_rel = {k: current.get(k) / median(v) if current.get(k) and len(v) >= self._cfg.min_sector_peers else None
                      for k, v in peer_values.items()}
        return {"current": current, "vs_history": hist_rel, "vs_sector": sector_rel,
                "sector_peers": max((len(v) for v in peer_values.values()), default=0),
                "sector": market.get("sector")}
