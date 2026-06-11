try:
    from . import _rust as financial_analyst_cli
except ImportError:
    from . import fallback as financial_analyst_cli

# Expose key functions directly
calculate_dcf = financial_analyst_cli.calculate_dcf
