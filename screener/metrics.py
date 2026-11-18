"""Shared financial-data helpers."""
def effective_cash(cash, cash_and_short_term_investments, short_term_investments):
    """Prefer the broad combined SEC tag; otherwise add cash and marketable securities."""
    if cash_and_short_term_investments is not None:
        return cash_and_short_term_investments
    if cash is None and short_term_investments is None:
        return None
    return (cash or 0.0) + (short_term_investments or 0.0)
