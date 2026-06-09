# Requirements Specification: Financial Analyst CLI

The system prompt should make it clear that the LLM is a senior financial analyst.

The initial config workflow:

1. Full name, email, and project name. Tell the user that this information is needed to access EDGAR API. If these are fake, then the API access may fail.

2. **LLM API Credentials**:
   - The user's API Key (e.g., OpenRouter, Gemini, OpenAI, Anthropic, Fireworks AI). Need at least one.

3. **Model Selection**:
   - The user must specify:
     - A **text-to-text model**
     - A **vision-to-text model**
   - _Alternative_: The user can choose to use the default **Gemma** model, which is natively multi-modal and handles both text and vision tasks.

4. **Workspace Path**:
   - The user must specify the location for their active workspace.
   - **CRITICAL WORKSPACE REMINDER (Always displayed)**:
     > [!IMPORTANT]
     > Each workspace should only contain one company to reduce potential context bloat. Ideally name the workspace directory after the company's ticker symbol (e.g., `AAPL` or `MSFT`), which serves as a convenient unique identifier.

The fa workflow assuming the config is done.

1. the user creates or opens a workspace, which is a folder. Regardless, double check the folder structure and add the necessary folders.

2. the user types `fa run edgar` and the CLI will ask for the company ticker and the time period, which should be limited to five years in the past. Then the CLI will use the EDGAR API to download all the 10K, 10Q, or 20F filings. The files should be downloaded into the 1_ingest_data folder.

3. the user types `fa run ingest` and the CLI will look in the 1_ingest_data folder for files. If there are no files, the CLI will tell the user there is nothing to ingest. If there is something to ingest, then the CLI will do the following in order:
   - for each file, run one-by-one. We need to add a queue and race conditions here. There should also be robust retry and back-off. DO NOT RELY ON AI TO MANAGE THE QUEUE.
     - Deterministic script: hash the file and compare to the hash of all the files documented in the parsed_data.csv. If there is a hash match, skip the file as a duplicate. If the file is new, then append a new entry in the parsed_data.csv with the original file name, hash, and placeholders for new file name, document_type, document_date, and fiscal quarter.
     - Deterministic script: based on the file type, run the correct script to convert the file into a markdown. In particular, the PDF or HTML conversion script should be one that takes into account the spacing and lines, which convey important information in a financial statement. THIS IS IMPORTANT> DO NOT MISS THIS.
     - Deterministic script: the markdown file should be placed in the parsed_data folder and the original raw file should be placed in the archived_data folder.
     - Deterministic script: chunk the markdown into 5000 char chunks and create a simple table of the chunk_id, char X to Y, frequency of numbers, frequency of symbols. Prepend this table onto the markdown file. chunk_id=0 should always be the file metadata and this simple table. Then chunk_id=1 is the first char of the main body and 5000 chars.
     - Give the LLM the document_types.json as reference. Give the LLM the correct entry in the parsed_data.csv and ingest_context.md. Ask the LLM what is the date of the document, keeping in mind that the filing date of 10Q or 10K is often 30-60 days after the date of quarter end, and what is the document type? Add the document type, document date to the parsed_data.csv. If the document_type is 10Q, 10K or earnings_announcement also add fiscal quarter to parsed_data.csv entry. Also rename the markdown file and the raw file. Update the parsed_data.csv entry with the new file name.
     - Self-healing and learning. Create and update 6_company_context/ingest_context.md with what is the likely fiscal year end and therefore which months corresponds to which quarters. Also include in the 6_company_context/ingest_context.md information such as this company likes to include the date of the document in chunk_id=1 while others like to include it in the last chunk. Double check the parsed_data.csv to see if the fiscal quarter for any entry. Also double check if the document date needs to be changed. If the document date changes, then the files should be renamed as well.

4. the user types `fa run extract` and the CLI will look at the 2_parse_data folder and 4_extracted_data folder and compare their respective csv files. For all the files that is in the parsed_data but not in the extracted_data, add to the queue. COMMENT: we need to consider using a single queue for the entire CLI, so there's no race conditions across commands. Based on the queue, for each file, the CLI will do the following:
   - Deterministic script: based on the document_type, the AI agent will be asked to do a different task.
   - COMMENT: The LLM should determine based on the simple table of chunks which chunk_id it needs and access the chunks one by one to determine if it has gathered sufficient information. However, each time the LLM accesses a new chunk, it should summarize what that chunk is about in 1-2 sentences and append the chunk_id and summary in YYYYMMDD_filetype_extracted.md. At the very end, append the final result to the YYYYMMDD_filetype_extracted.md.
   - If the document_type is analyst_report then write a short summary on the analyst views on the company with a special focus on the company's economic moat (none, narrow, wide), future margins (decreasing, stable, increasing), and future growth (decelerating, stable, accelerating).
   - If the document_type is press_release, news_article, and other, then write a short summary that focuses on what is different, not mundane, or special.
   - If the document_type is transcript, then write a short summary focusing on the analyst questions and focus on what is different, not mundane, or special.
   - If the document_type is 10Q, 10K, 20F (this is currently missing in document_types.json. Need to add it), or earnings announcement, then the LLM needs to extract the financial statement of the current fiscal quarter or year. Look through the chunks to find the balance sheet and income statement. For the 10Q, 10K, 20F, and earnings_announcement, the LLM should also extract the past period revenue and calculate a simple growth rate. The LLM should try and find constant currency or organic growth. The LLM should find the basic shares outstanding and diluted shares outstanding. Use frequency of numbers and frequency of symbols to prioritize the chunks to focus on. The LLM could also use the search tool to find specific items.
   - For the 10Q, 10K, 20F, and earnings_announcement, after extracting the financial statement, the CLI also needs to categorize the line items into operating and non-operating (financial-analyst-skills used a tiger-transformer model, but I would like to switch back to LLM judgement here) and calculate Invested Capital, EBITA, adjusted taxes, NOPAT, ROIC, and other calculations.
   - Self-healing and learning. Create and update 6_company_context/extract_context.md. This is the most important for 10Q, 10K, 20F, and earnings_announcement. For example, how does the company's financial statement label its dates on the financial statement? Some companies like to use Quarter. Some companies use a date. How does the company organize its financial statement? Some companies like to separate the revenue and cost by business units. Other uses weird formatting where indention signify total instead of writing total. The user may ask to make changes to the operating vs non-operating classification sometimes. These requests should also be documented in the this self-healing file.

5. the user types `fa run historical` and the CLI will look at the 4_extracted_data folder and 5_historical_analysis folder and compare their csv files. For all the files that is not already incorporated in the historical analysis, add to the queue. For each file in the queue, the CLI will do the following:
   - Deterministic script: based on the document_type, the AI agent will be asked to do a different task.
   - If the document_type is analyst_report then create or edit a 5_historical_analysis/analyst_views.md. The goal here is to track how the analyst reviews have changed over time, especially regarding the company's economic moat (none, narrow, wide), future margins (decreasing, stable, increasing), and future growth (decelerating, stable, accelerating). Maintain a table of how the views changed with each file. Keep comments about specific files to a minimum and focus on summarizing an overarching view.
   - If the document_type is press_release, news_article, and other, then create or edit a 5_historical_analysis/news_trend.md. The goal here is to surface interesting trends, contradictions, or other non-obvious news. Maintain a table of how the views changed with each file. Keep comments about specific files to a minimum and focus on summarizing an overarching view.
   - If the document_type is transcript, then create or edit a 5_historical_analysis/transcript_trend.md. The goal here is to surface interesting trends, contradictions, or other non-obvious news. Maintain a table of how the views changed with each file. Keep comments about specific files to a minimum and focus on summarizing an overarching view.
   - If the document_type is 10Q or earnings announcement, then create or edit a 5_historical_analysis/financials_quarter.md. The goal here is to maintain a longitudinal quarterly view of the financial statements and analysis.
   - If the document_type is 10K or 20F, then create or edit a 5_historical_analysis/financials_annual.md. The goal here is to maintain a longitudinal annual view of the financial statements and analysis.
   - Self-healing and learning. When a 10Q, earnings_announcement, 10K or 20F is processed, the LLM should check if there is sufficient information to calculate a missing fourth quarter in 5_historical_analysis/financials_quarter.md. Sometimes, a fourth quarter income statement is only obtained by subtracting three quarters worth of numbers from the annual number.

6. the user types `fa run model` and the CLI will look at 5_historical_analysis and generate a financial model based on the latest files.
   - Deterministic script: calculate the base_WACC, base_capital_turnover, base_revenue, base_ebita_margin, base_adjusted_tax_rate, base_growth_rate, base_terminal_growth
   - Based on the analyst_views.md, financials_quarter.md, and financials_annual.md, determine what is the fair base_ebita_margin, base_growth_rate, base_terminal_growth, and base_revenue (only really relevant if there is an acquisition or one-time event).
   - Based on context, financial_quarter.md, and financial_annual.md, determine what is the fair WACC, capital_turnover, and adjusted_tax_rate (only really relevant if there are major distorting effects).
   - Show the user a table of the assumptions and ask for feedback or proceed. If there is feedback to change one of the values. Document this change in self-healing and learning. Specifically, create and update 6_company_context/model_context.md.
   - Deterministic script: create the financial model and output the markdown in 7_financial_model and json in 8_historical_model_json

### 2. `query` Command Group

Retrieves and displays processed financial analysis data from the workspace directories.

- **`fa query summary <ticker>`**
  - Displays the company profile and the calculated historical financial metrics summary table (Revenue, EBITA, Tax Rate, Invested Capital, NOPAT, ROIC, and Organic Growth) by reading from `5_historical_analysis/`.
- **`fa query assessment <ticker>`**
  - Displays the qualitative assessments (economic moat, EBITA margin trajectory, organic growth trajectory) with their bullet rationales and confidence ratings by reading from `5_historical_analysis/`.
- **`fa query valuation <ticker>`**
  - Displays the calculated WACC details (beta, risk-free rate, equity risk premium, cost of debt/equity), DCF assumptions, 10-year projected cash flows, terminal value, and calculated intrinsic value per share by reading from `7_financial_model/`.

  ### 3. `viewer` Command

Serves the interactive zero-dependency DCF HTML viewer.

- **`fa viewer`**
  - Launches `tools/simple_frontend_server.py` to serve the interactive valuation viewer.
  - The viewer scans and loads JSON models from `8_historical_model_json/` (e.g., `YYYYMMDD_ticker_0.json`) and enables the user to modify assumptions and save updated versions back to the same folder as `YYYYMMDD_ticker_1.json`, etc.
  - Options:
    - `--port`: Port to listen on (default: `3000`).
    - `--host`: Host address to bind to (default: `127.0.0.1`).

### 4. `config` Command Group

Manages settings, API credentials, and active workspaces.

- **`fa config init`**
  - Interactively configures paths to the directories, API keys (Yahoo Finance, OpenRouter/OpenAI/Gemini keys), and standard LLM configurations. When a new workspace path is set, automatically initializes the 8 workspace subfolders (`1_ingest_data/` to `8_historical_model_json/`) with instructions.
- **`fa config show`**
  - Prints the current system settings, path locations, active workspace, and API configurations (with sensitive API keys masked).

Tools that the CLI should have access to:

- COMMENT: look at opencode and other open source CLI tools and copy their tools for generic file manipulation. DO NOT REINVENT THE WHEEL.
- Search for terms that retrieves a json of results with the location, 200 chars before and after the term.
- Prepend, append, and insert text into a markdown.
- Prepend, append, and insert entries into a csv.
- Get a specific section of a parsed_data markdown identified by chunk id, which translates to between char X and char Y. We should NEVER pass a giant document directly to the LLM. The LLM should use chunk_id=0 which and pull chunk_id=? one at a time asking if itself if it has enough information.
- Search whether a line_item is operating or non-operating. This should first search a CLI internal dictionary. If nothing is found, then search the web, specifically investopedia.
- This is not a comprehensive list.
