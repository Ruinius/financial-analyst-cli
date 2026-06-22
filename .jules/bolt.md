## 2024-06-20 - Fast String Search vs Behavior Match
**Learning:** Attempting to optimize markdown parsing by locating section boundaries via index tracking (`str.find`) can lead to subtle behavioral regressions if the original code intentionally parsed multiple matching blocks (e.g., all occurrences of `## Target Table`). Additionally, complex string slicing logic dramatically reduces readability for a minor execution speed improvement compared to native python string methods like `str.startswith`.
**Action:** When optimizing loop bottlenecks, prefer fast-fail checks before allocating heavy operations (like `.split("\n")`) or use efficient tuple-checks `startswith(("# ", "## ", "### "))`. Never rewrite simple array iteration into complex index-tracking loops unless there is a verified 1000x gain that preserves behavior perfectly.

## 2024-06-22 - Replace re.search with native string find
**Learning:** Native Python string methods like `.find()` combined with `.lower()` are significantly faster (10-15x) than `re.search` for exact case-insensitive substring matching on large texts (like markdown files).
**Action:** When performing simple static substring checks (e.g. searching for a markdown section header), use native string lookup methods rather than regular expressions to reduce latency and overhead.
