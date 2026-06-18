# Refactoring Ideas

- The curator agent writing the model_learning.md should also check extract_learning.md and extract_learning.md to see if there are things that should be incorporated. Double check when does the curator agent currently runs. I would like it to run once before the final dcf_modeling agent starts (to incorporate learnings from growth, margin, wacc, non-operating agents) and another time after the dcf_modeling agent runs to incorporate learnings from the dcf_modeling. The second curator agent run should also update the wiki.

- For the modeling, there should be a 10-turn modeling agent with access to the following tools:
  - for context, this agent should have model_learning.md, the current model markdown (with input from the other modeler agents, financial_quarters.md).
  - tool for running the valuation all the way to comparing the current share prices and fair value
  - tool for accessing any of the 5_historical_analysis. Double check these tools, which should already exist. We may need to create a tool folder.
  - tool for accessing any of the 4_extracted_data
  - tool for finalize, which will create the markdown append for the valuation section and full dcf table. There should be another section above the valuation section that is the list of assumptions actually used (vs what each of the agents said is a reasonable number above).
  - tool for accessing market data (which should be limited to share price, currency)
  - The reason for the 10-turns is because the AI agent should see if the dcf modeling results make any sense. If there are obvious errors like currency, then it should fix the input.

- Instead of "Ingested Sources" (this should be removed) in the wiki, I want a separate indexer_agent that maintains a TICKER_folder_index.md that keeps track of all the files in 4_extracted_data and 5_historical_analysis 6_financial_model. This index is important and goes hand-in-hand for when an agent is given a tool to read files in those folders. This agent should run after every extract, analyze, and model run.
