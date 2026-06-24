## 2024-06-20 - Fast String Search vs Behavior Match
**Learning:** Attempting to optimize markdown parsing by locating section boundaries via index tracking (`str.find`) can lead to subtle behavioral regressions if the original code intentionally parsed multiple matching blocks (e.g., all occurrences of `## Target Table`). Additionally, complex string slicing logic dramatically reduces readability for a minor execution speed improvement compared to native python string methods like `str.startswith`.
**Action:** When optimizing loop bottlenecks, prefer fast-fail checks before allocating heavy operations (like `.split("\n")`) or use efficient tuple-checks `startswith(("# ", "## ", "### "))`. Never rewrite simple array iteration into complex index-tracking loops unless there is a verified 1000x gain that preserves behavior perfectly.

## 2024-06-22 - Replace re.search with native string find
**Learning:** Native Python string methods like `.find()` combined with `.lower()` are significantly faster (10-15x) than `re.search` for exact case-insensitive substring matching on large texts (like markdown files).
**Action:** When performing simple static substring checks (e.g. searching for a markdown section header), use native string lookup methods rather than regular expressions to reduce latency and overhead.

## 2024-06-23 - Fast Markdown Code Block Stripping
**Learning:** Using `re.sub` for simple string replacements like stripping leading and trailing markdown code block fences (e.g. ` ```markdown `) is extremely slow and inefficient compared to native string methods. The regex engine overhead is not justified for these simple static matching scenarios.
**Action:** Replace `re.sub` calls with native string methods like `.startswith()`, `.endswith()`, and string slicing for simple text trimming/stripping operations to achieve massive performance gains (~25x faster).

## 2024-06-25 - Fast Fail Bypassing Regex
**Learning:** For extremely frequent string parsing operations (like parsing serialized prompts or scanning for numbers), simply adding a "fast fail" condition (e.g. `if "---" not in text: return`) or doing simple string iterations avoids loading the regex engine completely, resulting in 100x+ performance gains on edge cases or empty scenarios.
**Action:** Always consider if a regex operation can be completely bypassed by a simple native string check (like `.find()`, `in`, or native character scans) before defaulting to `re.split` or `re.search`.

## 2024-11-20 - [Native String Replace > Regex for repetitive whitespace]
**Learning:** For replacing multiple consecutive characters (like formatting \n{3,} to \n\n in large crawled HTML/Markdown), a simple `while "\n\n\n" in text: text = text.replace("\n\n\n", "\n\n")` loop executes ~5x faster than Python's `re.sub` due to bypassing regex engine overhead for massive strings.
**Action:** Default to native `str.replace` in a while loop when reducing repeating single characters or simple static substrings instead of regex.

## 2024-11-21 - Fast Float Parsing before Regex
**Learning:** For utility functions that clean and parse numerical strings (like `clean_val`), attempting a direct `float()` conversion after simple native string stripping (e.g., removing `$`, `,`, `%`, `()`) is significantly faster (~2.5x speedup) than immediately matching with a regular expression like `re.search`. Regex should only be invoked as a fallback for "noisy" inputs.
**Action:** When parsing cleanly formatted numerical data, create a "fast path" using `float()` combined with native string replacements to bypass regex engine overhead entirely.
