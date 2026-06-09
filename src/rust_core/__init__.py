try:
    import financial_analyst_cli
except ImportError:
    from . import fallback as financial_analyst_cli

# Expose key functions directly
calculate_dcf = financial_analyst_cli.calculate_dcf
calculate_ebita = financial_analyst_cli.calculate_ebita
calculate_invested_capital = financial_analyst_cli.calculate_invested_capital
calculate_tax_rates = financial_analyst_cli.calculate_tax_rates
calculate_roic = financial_analyst_cli.calculate_roic
