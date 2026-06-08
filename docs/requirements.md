# Requirements Specification: Financial Analyst CLI

This document outlines the core requirements for the command-line version of the financial analyst assistant. It translates the concepts from `financial-analyst-skills` into a local, terminal-friendly application.

## Core Features

1. **Ticker Insights & Overview**
   - Fetch company profile, sector, industry, and general description.
   - Summarize recent news and sentiment for a specific ticker.

2. **Financial Statements Analysis**
   - Retrieve and analyze Income Statements, Balance Sheets, and Cash Flow Statements.
   - Compute key financial metrics (e.g., margins, debt-to-equity, return on equity) over multi-year periods.
   - Compare performance across quarters or years.

3. **Valuation Models**
   - **Discounted Cash Flow (DCF)**: Calculate intrinsic value using revenue growth projections, terminal growth rate, and WACC.
   - **Comps Analysis**: Price-to-Earnings (P/E), Price-to-Sales (P/S), and EV/EBITDA comparison against competitors.

4. **Technical & Market Data Analysis**
   - Fetch historical stock price data.
   - Calculate moving averages (SMA/EMA) and basic indicators (RSI, MACD) to summarize current market trends.

5. **Report Generation**
   - Export structured reports (Markdown, PDF, or JSON).
   - Display terminal-optimized tables and summaries using formatting libraries (e.g., `rich`).
