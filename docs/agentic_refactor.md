# Refactoring Ideas

- The curator agent writing the model_learning.md should also check extract_learning.md and extract_learning.md to see if there are things that should be incorporated. Double check when does the curator agent currently runs. I would like it to run once before the final dcf_modeling agent starts (to incorporate learnings from growth, margin, wacc, non-operating agents) and another time after the dcf_modeling agent runs to incorporate learnings from the dcf_modeling. The second curator agent run should also update the wiki.
