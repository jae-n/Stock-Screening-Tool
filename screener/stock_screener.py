"""StockScreener singleton: applies pass/fail gates for
    (1) little debt, (2) durable advantage, (3) undervalued,
then ranks the survivors. Thresholds live in Config.

Not a buy signal: the screen produces candidates to research. "Cheap vs its own history"
can also mean the business is deteriorating, so read the filings before acting.
"""

from statistics import median

from screener.config import Config
from screener.quality import QualityCalculator
from screener.singleton import SingletonMeta
from screener.valuation import ValuationCalculator

EARNINGS_MULTIPLES = ("pe", "p_fcf", "ev_ebitda")   # used for the "undervalued" test


def scale(x, bad, good):
    """Map x to 0-100: `bad` -> 0, `good` -> 100 (works in either direction)."""
    if x is None:
        return None
    t = (x - bad) / (good - bad)
    return max(0.0, min(1.0, t)) * 100


def mean_available(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _x(v):
    return "n/a" if v is None else f"{v:.2f}x"


def _pct(v):
    return "n/a" if v is None else f"{v * 100:.1f}%"


class StockScreener(metaclass=SingletonMeta):
    def __init__(self):
        self._config = Config()
        self._quality = QualityCalculator()
        self._valuation = ValuationCalculator()
        self.last_errors = []            # tickers that raised during the last screen()

    @staticmethod
    def _gate(group, ok, detail):
        return {"group": group, "ok": bool(ok), "detail": detail}

    @staticmethod
    def _relative(rel_map):
        """Median of the available earnings-based relative multiples (needs >= 2)."""
        values = [rel_map[m] for m in EARNINGS_MULTIPLES if rel_map.get(m) is not None]
        return median(values) if len(values) >= 2 else None

    def evaluate(self, ticker):
        q = self._quality.compute(ticker)
        if q is None:
            return None
        val = self._valuation.analyze(ticker)
        cfg = self._config
        gates = {}

        # ---- debt ----
        nd = q["net_debt_to_ebitda"]
        gates["net_debt_ebitda"] = self._gate(
            "debt", nd is not None and nd <= cfg.max_net_debt_to_ebitda,
            ("net cash" if nd is not None and nd <= 0 else _x(nd)) + f" (max {cfg.max_net_debt_to_ebitda:.1f}x)"
            + (" [debt assumed zero]" if q["debt_assumed_zero"] else ""))
        de = q["debt_to_equity"]
        gates["debt_equity"] = self._gate(
            "debt", de is not None and de <= cfg.max_debt_to_equity,
            f"{_x(de)} (max {cfg.max_debt_to_equity:.2f}x)")
        cov = q["interest_coverage"]
        if q["debt_total"] == 0:
            gates["interest_cover"] = self._gate("debt", True, "no debt")
        elif cov is None:
            gates["interest_cover"] = self._gate("debt", True, "no interest data (skipped)")
        else:
            gates["interest_cover"] = self._gate(
                "debt", cov >= cfg.min_interest_coverage,
                f"{cov:.1f}x (min {cfg.min_interest_coverage:.1f}x)")

        # ---- advantage ----
        roic = q["avg_roic"]
        gates["avg_roic"] = self._gate(
            "moat", roic is not None and roic >= cfg.min_avg_roic,
            f"{_pct(roic)} avg over {q['roic_years']}y (min {_pct(cfg.min_avg_roic)})")
        cons = q["roic_consistency"]
        gates["roic_consistency"] = self._gate(
            "moat", cons is not None and cons >= cfg.min_roic_consistency,
            f"{_pct(cons)} of years >= {_pct(cfg.roic_floor)} (min {_pct(cfg.min_roic_consistency)})")
        gates["fcf_positive"] = self._gate(
            "moat", q["fcf_positive_all"] is True,
            {True: "positive every year", False: "negative in some year",
             None: "not enough data"}[q["fcf_positive_all"]])
        gates["revenue_growth"] = self._gate(
            "moat", q["rev_cagr"] is not None and q["rev_cagr"] >= cfg.min_rev_cagr,
            f"{_pct(q['rev_cagr'])} CAGR (min {_pct(cfg.min_rev_cagr)})")

        # ---- undervalued ----
        if val is None:
            for name in ("disc_history", "disc_sector", "fcf_yield"):
                gates[name] = self._gate("value", False, "no market data (run with --prices)")
            rel_hist = rel_sector = fcf_yield = None
        else:
            rel_hist = self._relative(val["vs_history"])
            rel_sector = self._relative(val["vs_sector"])
            fcf_yield = val["current"]["fcf_yield"]
            gates["disc_history"] = self._gate(
                "value", rel_hist is not None and rel_hist <= cfg.max_rel_history,
                f"{_x(rel_hist)} of own history (max {cfg.max_rel_history:.2f}x)")
            if rel_sector is None and not cfg.require_sector:
                gates["disc_sector"] = self._gate(
                    "value", True, f"too few sector peers ({val['sector_peers']}), skipped")
            else:
                gates["disc_sector"] = self._gate(
                    "value", rel_sector is not None and rel_sector <= cfg.max_rel_sector,
                    f"{_x(rel_sector)} of sector median (max {cfg.max_rel_sector:.2f}x)")
            gates["fcf_yield"] = self._gate(
                "value", fcf_yield is not None and fcf_yield >= cfg.min_fcf_yield,
                f"{_pct(fcf_yield)} (min {_pct(cfg.min_fcf_yield)})")

        # ---- ranking score (only meaningful for stocks that pass) ----
        value_score = mean_available([scale(rel_hist, 1.0, 0.5), scale(rel_sector, 1.0, 0.5),
                                      scale(fcf_yield, 0.03, 0.10)])
        moat_score = mean_available([scale(roic, 0.10, 0.30), scale(cons, 0.6, 1.0),
                                     scale(q["op_margin_stdev"], 0.10, 0.02)])
        debt_score = mean_available([
            scale(nd, 3.0, 0.0), scale(de, 1.0, 0.0),
            100.0 if q["debt_total"] == 0 else scale(cov, 3.0, 20.0)])
        parts = [(value_score, cfg.weight_value), (moat_score, cfg.weight_moat),
                 (debt_score, cfg.weight_debt)]
        weight = sum(w for s, w in parts if s is not None)
        composite = sum(s * w for s, w in parts if s is not None) / weight if weight else None

        failed = [name for name, g in gates.items() if not g["ok"]]
        return {
            "ticker": ticker,
            "basis": {"type": q["basis"], "flows_as_of": q["flows_as_of"],
                      "balance_as_of": q["balance_as_of"]},
            "passed": not failed,
            "failed": failed,
            "gates": gates,
            "scores": {"value": value_score, "moat": moat_score, "debt": debt_score},
            "composite": composite,
            "metrics": {"avg_roic": roic, "net_debt_to_ebitda": nd, "debt_to_equity": de,
                        "fcf_yield": fcf_yield, "rel_history": rel_hist, "rel_sector": rel_sector},
        }

    def screen(self, tickers, near_miss_max=2):
        """Return (passers ranked best-first, near misses, tickers with no data)."""
        results, no_data, self.last_errors = [], [], []
        for t in tickers:
            try:
                r = self.evaluate(t)
            except Exception as exc:         # odd data in one company must not stop the others
                self.last_errors.append(f"{t}: {type(exc).__name__}: {exc}")
                continue
            (results if r else no_data).append(r or t)
        passers = sorted((r for r in results if r["passed"]),
                         key=lambda r: r["composite"] or 0, reverse=True)
        near = sorted((r for r in results if 0 < len(r["failed"]) <= near_miss_max),
                      key=lambda r: (len(r["failed"]), -(r["composite"] or 0)))
        return passers, near, no_data
