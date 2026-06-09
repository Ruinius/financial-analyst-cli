"""
Fetch market data for a stock ticker from Yahoo Finance.

A single, consistent tool for all yfinance lookups across financial-analyst-skills.
Supersedes the standalone validate_ticker.py — validation is now a subcommand.

Usage:
    python market_data.py validate BIDU
    python market_data.py profile BIDU
    python market_data.py fx CNY USD
    python market_data.py profile BIDU --verbose

Commands:
    validate  — Validate ticker and return company name (lightweight)
    profile   — Full market data: price, beta, market cap, currency, shares
    fx        — Exchange rate between two currencies

All commands return JSON to stdout. Errors go to stderr.
"""

import argparse
import json
import sys

try:
    import yfinance as yf
except ImportError:
    print(json.dumps({
        "error": "yfinance not installed. Run: pip install yfinance"
    }))
    sys.exit(1)


# ── Currency Aliases ──────────────────────────────────────────────────────────

CURRENCY_ALIASES = {
    "RMB": "CNY",
    "RENMINBI": "CNY",
}


def _normalize_currency(code: str) -> str:
    """Map common aliases to ISO currency codes."""
    return CURRENCY_ALIASES.get(code.upper(), code.upper())


# ── Validate ──────────────────────────────────────────────────────────────────

def validate_ticker(ticker: str, verbose: bool = False) -> dict:
    """
    Validate a ticker symbol using Yahoo Finance (lightweight check).
    
    Returns:
        {"valid": bool, "ticker": str, "company_name": str|null, "error": str|null}
    """
    result = {
        "valid": False,
        "ticker": ticker.upper().strip(),
        "company_name": None,
        "error": None,
    }
    
    if not ticker or not ticker.strip():
        result["error"] = "Empty ticker provided"
        return result
    
    ticker = ticker.upper().strip()
    
    try:
        ticker_obj = yf.Ticker(ticker)
        info = ticker_obj.info
        
        if verbose:
            print(f"[DEBUG] Yahoo Finance info keys: {list(info.keys())[:10]}...", file=sys.stderr)
        
        short_name = info.get("shortName")
        long_name = info.get("longName")
        company_name = short_name or long_name
        
        if company_name:
            result["valid"] = True
            result["company_name"] = company_name
        else:
            result["error"] = "No company name found — ticker may be invalid"
                
    except Exception as e:
        result["error"] = f"Yahoo Finance lookup failed: {str(e)}"
    
    return result


# ── Profile ───────────────────────────────────────────────────────────────────

def get_market_profile(ticker: str, verbose: bool = False) -> dict:
    """
    Fetch comprehensive market data for a ticker.
    
    Returns everything needed for WACC, intrinsic value, and FX conversion:
      - Company name, currency, exchange
      - Share price, market cap, shares outstanding
      - Beta (raw levered)
      - Sector and industry (for context)
    """
    result = {
        "valid": False,
        "ticker": ticker.upper().strip(),
        "company_name": None,
        "currency": None,
        "exchange": None,
        "share_price": None,
        "market_cap": None,
        "shares_outstanding": None,
        "beta": None,
        "sector": None,
        "industry": None,
        "error": None,
    }
    
    if not ticker or not ticker.strip():
        result["error"] = "Empty ticker provided"
        return result
    
    ticker = ticker.upper().strip()
    
    try:
        ticker_obj = yf.Ticker(ticker)
        info = ticker_obj.info
        
        if verbose:
            print(f"[DEBUG] Full info keys: {sorted(info.keys())}", file=sys.stderr)
        
        # ── Identity ──
        short_name = info.get("shortName")
        long_name = info.get("longName")
        company_name = short_name or long_name
        
        if not company_name:
            result["error"] = "No company name found — ticker may be invalid"
            return result
        
        result["valid"] = True
        result["company_name"] = company_name
        result["currency"] = info.get("currency")
        result["exchange"] = info.get("exchange")
        result["sector"] = info.get("sector")
        result["industry"] = info.get("industry")
        
        # ── Price ──
        # Try fast_info first (faster, more reliable for price)
        price = getattr(ticker_obj.fast_info, "last_price", None)
        if price is None:
            price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price is None:
            # Last resort: recent history
            try:
                hist = ticker_obj.history(period="5d")
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
            except Exception:
                pass
        result["share_price"] = round(float(price), 2) if price else None
        
        # ── Market Cap ──
        market_cap = getattr(ticker_obj.fast_info, "market_cap", None)
        if market_cap is None:
            market_cap = info.get("marketCap")
        result["market_cap"] = int(market_cap) if market_cap else None
        
        # ── Shares Outstanding ──
        shares = info.get("sharesOutstanding")
        if shares is None:
            shares = getattr(ticker_obj.fast_info, "shares", None)
        result["shares_outstanding"] = int(shares) if shares else None
        
        # ── Beta ──
        beta = info.get("beta")
        result["beta"] = round(float(beta), 4) if beta else None
        
        if verbose:
            print(f"[DEBUG] {company_name}: price={result['share_price']}, "
                  f"mcap={result['market_cap']}, beta={result['beta']}, "
                  f"currency={result['currency']}", file=sys.stderr)
        
    except Exception as e:
        result["error"] = f"Yahoo Finance lookup failed: {str(e)}"
        if verbose:
            print(f"[DEBUG] Exception: {e}", file=sys.stderr)
    
    return result


# ── FX ────────────────────────────────────────────────────────────────────────

def get_exchange_rate(from_currency: str, to_currency: str = "USD", verbose: bool = False) -> dict:
    """
    Fetch the exchange rate between two currencies via Yahoo Finance.
    
    Example: get_exchange_rate("CNY", "USD") returns the CNY→USD rate.
    
    Returns:
        {"from": "CNY", "to": "USD", "rate": 0.1379, "error": null}
    """
    from_curr = _normalize_currency(from_currency)
    to_curr = _normalize_currency(to_currency)
    
    result = {
        "from": from_curr,
        "to": to_curr,
        "rate": None,
        "error": None,
    }
    
    if from_curr == to_curr:
        result["rate"] = 1.0
        return result
    
    try:
        # Yahoo Finance FX ticker format: "CNYUSD=X"
        fx_ticker = f"{from_curr}{to_curr}=X"
        
        if verbose:
            print(f"[DEBUG] Fetching FX ticker: {fx_ticker}", file=sys.stderr)
        
        data = yf.Ticker(fx_ticker)
        
        # Try fast_info first
        price = getattr(data.fast_info, "last_price", None)
        
        if price is None:
            # Fallback to history
            hist = data.history(period="5d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
        
        if price is not None and price > 0:
            result["rate"] = round(float(price), 6)
            if verbose:
                print(f"[DEBUG] {from_curr}/{to_curr} = {result['rate']}", file=sys.stderr)
        else:
            result["error"] = f"No rate data for {fx_ticker}"
                
    except Exception as e:
        result["error"] = f"FX lookup failed: {str(e)}"
        if verbose:
            print(f"[DEBUG] Exception: {e}", file=sys.stderr)
    
    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Yahoo Finance market data tool for financial-analyst-skills",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python market_data.py validate BIDU
  python market_data.py profile AAPL
  python market_data.py profile BIDU --verbose
  python market_data.py fx CNY USD
  python market_data.py fx RMB USD
        """
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # validate
    p_validate = subparsers.add_parser("validate", help="Validate a ticker symbol")
    p_validate.add_argument("ticker", help="Stock ticker symbol")
    p_validate.add_argument("--verbose", "-v", action="store_true")
    
    # profile
    p_profile = subparsers.add_parser("profile", help="Get full market profile")
    p_profile.add_argument("ticker", help="Stock ticker symbol")
    p_profile.add_argument("--verbose", "-v", action="store_true")
    
    # fx
    p_fx = subparsers.add_parser("fx", help="Get exchange rate")
    p_fx.add_argument("from_currency", help="Source currency (e.g., CNY, RMB)")
    p_fx.add_argument("to_currency", nargs="?", default="USD", help="Target currency (default: USD)")
    p_fx.add_argument("--verbose", "-v", action="store_true")
    
    args = parser.parse_args()
    
    if args.command == "validate":
        result = validate_ticker(args.ticker, verbose=args.verbose)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["valid"] else 1)
        
    elif args.command == "profile":
        result = get_market_profile(args.ticker, verbose=args.verbose)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["valid"] else 1)
        
    elif args.command == "fx":
        result = get_exchange_rate(args.from_currency, args.to_currency, verbose=args.verbose)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["rate"] is not None else 1)
        
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
