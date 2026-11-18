from pathlib import Path
import re

def parse_tickers(args):
    supplied = getattr(args, "tickers", None) or []
    if supplied:
        raw = supplied
    else:
        filename = getattr(args, "file", None)
        if not filename:
            return []
        path = Path(filename)
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8").splitlines()

    result = []
    seen = set()
    for line in raw:
        symbol = str(line).split("#", 1)[0].strip().upper()
        if symbol and re.fullmatch(r"[A-Z0-9.^=_-]{1,20}", symbol):
            if symbol not in seen:
                result.append(symbol)
                seen.add(symbol)
    return result
