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

## 2024-11-23 - Streaming file line-by-line parsing vs memory loading
**Learning:** When scanning files for regex matches line-by-line, reading the entire file contents into memory and splitting it (`path.read_text().split("\n")`) is extremely inefficient and memory-intensive. Pre-compiling the regex and streaming the file via a context manager (`with path.open("r"): for line in f:`) yields roughly 20x faster performance on large files with significantly lower memory consumption, while perfectly maintaining string matching semantics like `line.strip()`.
**Action:** Always prefer file iterators (`for line in path.open():`) combined with pre-compiled regex objects when searching large files line-by-line, rather than reading and splitting the whole text blob into memory.

## 2024-11-25 - [Native str.count vs Regex for Frequency Counting]
**Learning:** For analyzing the frequency of character classes (like digits or common symbols) in large text chunks, using a generator expression with native `str.count` (e.g., `sum(chunk.count(d) for d in "0123456789")`) executes roughly 2x faster than a regular expression like `len(re.findall(r"\d", chunk))`. Native python operations bypass regex engine overhead entirely.
**Action:** Default to generator expressions combining `str.count` with predefined character strings when counting specific simple characters, rather than defaulting to `re.findall`.

## 2024-11-26 - [Pre-compile Regex + Fast Fail on Clean Data]
**Learning:** For frequently called utility functions that sanitize structured text (like JSON or Markdown), executing `re.sub` is extremely slow if the input is often clean. Pre-compiling the regex and adding a fast-fail native string check (e.g., `if "/*" in text:`) avoids the regex engine overhead entirely for clean inputs, resulting in up to 6x faster execution.
**Action:** Always pre-compile regular expressions at the module level. Before executing a regex substitution or search, use native string checks (`in` or `.find()`) as a fast path to return early if the target pattern is obviously missing.

## 2024-11-26 - [Pre-compile Regex + Fast Fail for Parsing Loops]
**Learning:** Compiling regular expressions repeatedly inside loops or heavily called utility functions (like `re.search`, `re.match`, or `re.finditer`) adds significant overhead. Additionally, even with pre-compiled regexes, executing the `.match` or `.search` operation is slower than skipping it entirely for mismatched strings. For simple patterns like a markdown table separator (`^:?-+:?$`), adding a native python fast-fail check (`if "-" not in cell:`) before executing the regex can dramatically reduce processing latency on invalid inputs.
**Action:** Always pre-compile regular expressions at the module level when they are used in tight loops or string parsing utilities. When practical, pair the pre-compiled regex with a fast-fail native Python check (`in`, `startswith`) to avoid calling the regex engine entirely when the string obviously does not match.

## 2024-11-27 - [Pre-compiled Regex > Complex Native Fast Paths]
**Learning:** While replacing `re.sub(r"[^a-zA-Z0-9_-]", "", text)` with a native fast path `if text.isascii() and text.replace("-", "").replace("_", "").isalnum():` paired with a fallback generator yields a ~5x speedup, it drastically sacrifices code readability for a microscopic gain (saving ~1us). Additionally, `isalnum()` has Unicode implications that require further assertions (`isascii()`), compounding complexity. Instead, simply pre-compiling the regex object (`re.compile(r"[^a-zA-Z0-9_-]")`) at the module level provides a clean ~3x performance boost over inline execution while remaining idiomatic and strictly safe.
**Action:** Default to pre-compiling simple regular expressions at the module level to optimize overhead rather than contorting into complex native string comprehension hacks that sacrifice readability.

## 2025-02-23 - [Fast-Fail Pre-Filter for Complex Loop Regexes]
**Learning:** In functions mapping through large lists of search items (e.g. keywords) against massive text documents using expensive regex lookups per-item (like chunk index spanning), filtering the original list up front by using native string presence checks (`if kw in content_lower`) can save an astronomical amount of execution overhead. The pre-filter entirely bypasses the inner regex overhead loops when nothing matches.
**Action:** When performing list-based matching across large texts, apply a single fast native string presence check (`item in text`) to pre-filter items before performing detailed contextual extraction, chunk mapping, or regular expressions.

## 2025-02-23 - [Precompute Static Values & Join Lists > String Concat in Loops]
**Learning:** Inside deeply nested generation loops (like creating markdown documents from chunks), continuously modifying long strings using `+=` and re-calculating static variables inside the loop introduces huge memory reallocation overhead and duplicated effort. By precomputing static frequencies outside the loop and appending loop parts to a list to be concatenated using `"".join(parts)` at the very end, we can achieve ~3x faster execution speeds on large document assembly.
**Action:** When assembling large documents iteratively, never use string concatenation (`+=`). Always append fragments to a list and use `"".join()` at the end. Additionally, audit loops to pull completely static calculations (e.g. counting frequencies of an unmodified chunk list) outside the loop.
## 2024-05-24 - [Optimize Markdown Table Parsing with Fast-Fails]
**Learning:** Iterating over every line in a large markdown file to extract markdown tables is expensive when using string `.strip()`, `.startswith()`, and `.endswith()` for every line, as well as splitting on `|` to count columns. Strings in Python allocate memory, which creates overhead when executed thousands of times.
**Action:** Fast-fail logic that bypasses slow native string methods when possible leads to massive performance gains. Use explicit boolean and native character checks like `if not line: continue` or counting characters `line.count('|')` before doing heavy allocations like string strips and splits.
## 2024-05-25 - [Optimize Markdown Table Parsing with Substring Bounds]
**Learning:** In functions that extract tables from extremely large markdown strings, searching the entire string line-by-line via `.split("\n")` causes massive memory allocation overhead (spiking latency). Finding the exact character bounds of the target section first via native string searches (`str.find()`) and *then* splitting only that specific substring avoids generating thousands of useless string objects in memory for irrelevant document portions.
**Action:** Always constrain large string manipulations. Use `str.find()` to locate bounds of the text you need, slice it, and then apply expensive operations like `.split()` or regex parsing only on the sliced region.
## 2026-07-04 - [Native str.find loop vs Regex finditer for Tag Extraction]
**Learning:** For extracting metadata tags or positional markers spanning huge strings (like `<!-- CHUNK_START: 1 -->`), using a `while True:` loop containing `content.find("<!-- CHUNK_START:")` is drastically faster (~15x) than executing `re.finditer` over the whole string. The regex engine's state machine overhead per character on large documents is completely bypassed by pure C-level substring search.
**Action:** Replace `re.finditer` and `re.search` with while-loops using `.find()` when looking for exact static prefixes/suffixes within massive documents (e.g. bounded tags).
## 2026-07-05 - [Bypassing splitlines overhead with native string fast fails]
**Learning:** For functions parsing massive text blobs for specific formatting structures (like markdown tables), immediately allocating a massive list of strings via `content.splitlines()` takes considerable memory and time even if the required structure isn't present in the string. For example, if checking for a markdown table, checking `if "|" not in content:` up front provides a ~1000x speedup for invalid strings by instantly bypassing the `splitlines` memory allocation. Furthermore, doing a similar check `if "|" not in line:` per line within a parsing loop bypasses the overhead of `.strip()` and bounding checks for lines that couldn't possibly be a table row.
**Action:** When validating or parsing text for patterns heavily reliant on a specific delimiter or structure (e.g., markdown tables, XML tags), implement an overarching fast-fail absence check using native Python (`if char not in text: return`) *before* executing expensive memory allocations like `text.splitlines()`.
