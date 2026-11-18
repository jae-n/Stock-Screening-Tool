import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Stock Screener")
    parser.add_argument("tickers", nargs="*")
    parser.add_argument("--file", default="tickers.txt")
    parser.add_argument("--db")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-discovery", action="store_true")
    parser.add_argument("--no-refresh", action="store_true")
    parser.add_argument("--no-prices", action="store_true")
    parser.add_argument("--refresh-only", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    from screener import Config, DailyJob
    from screener.database import Database
    from main import parse_tickers

    Config().configure(db_path=args.db)

    if args.self_test:
        Database()
        tickers = parse_tickers(args)
        print("Imports: OK")
        print("Database: OK")
        print(f"Ticker file: OK ({len(tickers)} symbols)")
        print("No network calls or notifications made.")
        return 0

    tickers = parse_tickers(args)

    return DailyJob().run(
        tickers,
        refresh=not args.no_refresh,
        prices=not args.no_prices,
        discover=not args.no_discovery,
        send=not args.refresh_only,
        dry_run=args.dry_run,
        force=args.force
    )

if __name__ == "__main__":
    raise SystemExit(main())
