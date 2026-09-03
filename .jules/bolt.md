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

## 2024-05-27 - [Optimize Markdown Table splitlines overhead with Bounds Slicing]
**Learning:** For functions processing massive text documents looking for bounded structures (like tables), calling `splitlines()` on the entire document allocates a massive list of strings in memory and causes significant latency. Finding the bounds of the target structure first (e.g., using `content.find("|")` and `content.rfind("|")` to find table bounds) and then slicing the string before calling `splitlines()` on just that segment is ~100x faster and drastically reduces memory overhead, while `content.count('\n')` can correctly preserve accurate original line indexing.
**Action:** When validating or parsing bounded text structures, use string bounds checking (`find`/`rfind`) to isolate the structure before executing memory-heavy operations like `splitlines()` or `.split()`.

## 2024-11-28 - [Native str.translate for Bulk Character Frequency Counting]
**Learning:** When counting the frequency of a group of characters (like digits or symbols) in large text blocks, using a generator expression with `str.count` (e.g., `sum(chunk.count(d) for d in "0123456789")`) is significantly slower than using a global translation table with `str.translate()`. By precomputing a `str.maketrans` table that removes all target characters, and calculating the difference `len(chunk) - len(chunk.translate(table))`, the overhead of Python-level loops is completely bypassed, yielding a ~6x speedup.
**Action:** Default to using `str.translate` combined with length subtraction when checking the total frequency of specific character groups (like all digits or all symbols) in large text bodies, rather than summing individual `.count()` results inside a generator.
## 2024-05-28 - [Fast-Fail Over Allocations for Optional String Processing]
**Learning:** In functions parsing massive text blocks for optional tabular data, directly calling `content.split("\n")` immediately generates thousands of strings in memory. For markdown parsing where tables are identified by specific delimiters (like the pipe `|`), inserting a native fast-fail check (`if "|" not in table_text: return []`) instantly aborts the function for non-tabular content. This avoids allocating a huge array of strings for slices of text that could never logically contain the target structure.
**Action:** When extracting structures that mandate specific characters, inject a native character presence check (e.g., `in`) before triggering expensive memory allocations like `.split()` or `.splitlines()`.

## 2024-05-29 - [Cache Object Methods in Tight Loops]
**Learning:** Inside tight loops (like iterating over stream chunks from an LLM response), repeatedly calling expensive object methods like `.model_dump()` to extract optional fields incurs substantial object allocation and serialization overhead. Caching the result of the method call in a local variable if it hasn't been accessed yet avoids repeated execution and redundant object creations, yielding measurable speedups on large payloads.
**Action:** When querying multiple keys from a complex object or dictionary generation method (like `.model_dump()`) inside a tight loop, evaluate it once and cache the result into a local variable rather than calling the method repeatedly inside conditional checks (like `or`).

## 2024-05-24 - Testing Network Caches
**Learning:** When implementing class-level caching for network clients (like caching SEC ticker lookups to bypass `httpx.get`), standard sequential mock side effects (`mock_get.side_effect = [resp1, resp2]`) will fail because cache hits skip expected HTTP calls. Furthermore, class-level state persists across tests, causing cross-test pollution.
**Action:** When testing caching logic, use URL-routing for mock `side_effect` functions (`def side_effect(url): if "x" in url: return resp1`) and explicitly reset the cache state to `None` at the start of tests to ensure isolation.

## 2024-05-30 - [Bypassing splitlines overhead for Chunking]
**Learning:** For functions dividing massive documents into structural chunks, invoking `.split("\n")` completely loads the entire text into memory as an array of millions of strings, causing tremendous memory overhead. Finding newlines incrementally (`text.find("\n", start_idx)`) in a while-loop and slicing on demand achieves the exact same split functionality while entirely avoiding the massive list allocation.
**Action:** When iterating over lines of an exceptionally large string without returning all of them at once, avoid `.split("\n")`. Instead, write a fast `str.find("\n")` iterator loop to extract and process each line sequentially without memory explosion.

## 2024-07-21 - [Native string methods for table separator validation]
**Learning:** When validating markdown table separator rows, checking native string methods (e.g. `.strip(":")` followed by checking if `.replace("-", "")` is empty) is significantly faster than using regex matching (`re.match(r"^:?-+:?$")`). The native method provides a ~1.8x speedup by completely avoiding regex engine overhead.
**Action:** Replace simple regex checks with native string slicing, stripping, and replacing where possible to eliminate regex engine overhead.

## 2024-05-31 - [Bypass text chunking overhead for small strings]
**Learning:** Functions that parse and chunk texts (like text splitters) often iterate line-by-line looking for newlines. This introduces considerable iteration and tracking overhead for strings that are already smaller than the max chunk size, which happens frequently in applications chunking smaller fragments.
**Action:** Always introduce a fast-fail check (`if len(text) <= max_chars: return [text]`) at the very beginning of text chunking/splitting functions. This completely bypasses the iterative loop overhead for strings that do not need to be chunked.
## 2024-05-32 - [Avoid Redundant String Scans for Fast-Fails]
**Learning:** When attempting to bypass expensive operations (like a backward `rfind` scan) by introducing a fast-fail check for a required character, combining `if char in text:` with a subsequent `text.find(char)` forces two O(N) string traversals on successful matches. Evaluating `idx = text.find(char)` directly and checking `if idx == -1:` provides the exact same fast-fail optimization for absent characters without penalizing the happy path with a redundant scan.
**Action:** When combining native string operations for fast-failing, avoid redundant O(N) scans. Execute `text.find(char)` directly and use the return value (`-1`) to determine presence, rather than preceding it with an `in` check.
## 2024-06-01 - [Avoid Redundant String Scans for Fast-Fails in Loops]
**Learning:** When searching for a substring in a loop, introducing a fast-fail check with `in` (e.g., `if target_name not in text_lower:`) before entering the loop (which uses `text_lower.find(target_name)`) forces an extra O(N) string traversal just to check presence. Removing the `in` check and simply letting the `find()` inside the loop return `-1` provides the exact same fast-fail optimization for absent characters without penalizing the function with a redundant full-string scan.
**Action:** When using `find()` in a loop, avoid preceding the loop with an `in` check. Execute `find()` directly in the loop and use its return value to determine presence, rather than forcing a redundant scan.
## 2024-06-02 - [Avoid Unnecessary Iterative Document Compilations]
**Learning:** During processes that stabilize chunking offsets or iterate multiple times to format a large document, appending to large lists (`parts.append`) and repeatedly invoking `"".join(parts)` on every iterative pass creates heavy memory allocation overhead and spikes latency by allocating megabytes of useless strings in memory that are immediately thrown away.
**Action:** When running multi-pass stabilization loops where only the final constructed string is returned or saved, introduce an `is_final` boolean flag inside the loop (`is_final = iteration == max_iterations`). Wrap massive list operations (like `.append(chunk)`) and especially the final `"".join()` call with `if is_final:` to completely bypass the memory overhead of intermediate iterations.

## 2024-06-03 - [Bypass splitlines overhead for Text Chunking]
**Learning:** For functions dividing massive documents into fixed-size structural chunks, invoking `.split("\n")` first completely loads the entire text into memory as an array of thousands of strings, causing tremendous memory overhead. Further, iteratively rebuilding chunks with `"\n".join()` scales poorly. By checking bounds first and using `text.rfind("\n", start_idx, end_idx + 1)` to find clean break points within a while loop, we can slice directly (`text[start_idx:newline_idx]`). This achieves the exact same chunk functionality while entirely avoiding the massive list allocation and joining operations, providing a ~3.5x speedup and lower memory usage.
**Action:** When creating text chunking utilities, avoid `.split("\n")`. Instead, write a native bounds slicing loop using `str.rfind()` to extract chunks directly on demand without generating intermediate line arrays.
## 2024-05-24 - Avoid Reinstantiating Sets in Loops
**Learning:** Instantiating `set("abcdefghijklmnopqrstuvwxyz")` on every loop iteration to check for alphanumeric characters incurs heavy memory allocation and hashing overhead, making simple validation loops extremely slow. Native string methods execute in C and are drastically faster.
**Action:** When iterating over characters or small strings in tight loops, always use native Python string methods (e.g., `s.isascii() and s.isalpha()`) rather than repeatedly creating objects for membership testing.

## 2024-05-24 - O(N^2) nested loop string replacements
**Learning:** Checking for string matches within a nested loop like `for x in list_a: for y in list_b: if x.lower() == y.lower()` scales poorly (O(N*M)) and repeatedly allocates strings.
**Action:** Always precompute a hash map for the target list (e.g., `map = {x.lower(): x for x in list_a}`) outside the loop and use `map.get(y.lower())` inside the loop to achieve O(N) complexity with minimal allocations.

## 2024-06-04 - [Optimize List Padding with list.extend]
**Learning:** When padding lists to a specific length (e.g. padding rows to have equal columns), using a `while` loop to repeatedly `.append()` items forces Python to do O(N) method calls and length checks. Calculating the required difference and using `list.extend([""] * diff)` achieves the same result in O(1) time and is significantly faster.
**Action:** Replace `while len(list) < max_cols: list.append("")` loops with O(1) list extension operations like `diff = max_cols - len(list); if diff > 0: list.extend([""] * diff)`.

## 2024-06-05 - [Bypass splitlines overhead for Table Validation]
**Learning:** In functions like `validate_markdown_table_syntax`, processing large text segments into tables by calling `.splitlines()` allocates a massive array of strings, leading to performance bottlenecks when chunk sizes are massive or documents contain immense tables. We can maintain identical correctness by lazily finding line boundaries with `str.find('\n', pos)` in a while loop.
**Action:** When validating formatting line-by-line across potentially massive strings, use an inner while loop with `str.find('\n')` to avoid creating a massive list of strings via `splitlines()`.

## 2024-06-06 - [Bypass splitlines overhead for Table Extractors]
**Learning:** In functions extracting optional structures like markdown tables from large text strings, validating presence via fast-fail checks (`if "|" not in table_text`) avoids the immediate allocation of massive lists of strings from `split("\n")` for completely invalid strings. However, when valid tables do exist in the text block, calling `split("\n")` still incurs tremendous O(N) allocation overhead for the lines of the entire string slice. Using a memory-efficient `while` loop that sequentially extracts lines with `text.find("\n", start_idx)` eliminates the list overhead while achieving the same line-by-line processing semantics.
**Action:** Replace `split("\n")` allocations in line-by-line parsing functions (like table extraction) with `while` loops and native `str.find("\n")` bounds slicing for scalable parsing of massive strings.

## 2024-08-15 - [Fast-fail Early Return for Markdown Stripping]
**Learning:** Found that string preprocessing functions often execute expensive O(N) operations like `.lower()` on full documents before checking if the transformation is even applicable.
**Action:** Always add early return fast-fail checks using native string bounds like `.startswith()` or `.endswith()` to skip unnecessary string allocations (like `.lower()`) when the target pattern is clearly absent.

## 2024-08-16 - [Fast-fail lower() on entire string]
**Learning:** Found that string preprocessing functions sometimes call `.lower()` on the full document just to check a short prefix case-insensitively (e.g. `text.lower().startswith("```markdown")`). For massive strings, this creates a huge memory allocation.
**Action:** When doing case-insensitive prefix checks on massive strings, slice the specific length first (e.g. `text[:11].lower() == "```markdown"`) to avoid allocating a massive lowercased copy of the entire string.

## 2024-08-19 - [Combine List Comprehensions into a Single Pass]
**Learning:** Performing multiple list comprehensions over the same collection to filter and sum different categories introduces redundant O(N) iteration overhead. For example, iterating over a list of line items four times to calculate four different sums is inefficient.
**Action:** When calculating multiple sums or aggregations from a single collection based on different conditions, refactor the code to perform a single O(N) `for` loop and accumulate all values simultaneously to avoid redundant traversal overhead.

## 2024-08-19 - [Combine List Comprehensions into a Single Pass]
**Learning:** Performing multiple list comprehensions over the same collection to filter and sum different categories introduces redundant O(N) iteration overhead. For example, iterating over a list of line items four times to calculate four different sums is inefficient.
**Action:** When calculating multiple sums or aggregations from a single collection based on different conditions, refactor the code to perform a single O(N) `for` loop and accumulate all values simultaneously to avoid redundant traversal overhead.

## 2024-08-19 - [Fast-fail string list parsing]
**Learning:** When sanitizing strings into lists, adding a native fast-fail check (`if "," not in text and "\n" not in text:`) before expensive operations like `.split()` entirely bypasses list allocation overhead for simple, clean strings.
**Action:** Add fast-fail checks before `.split()` operations on strings to bypass overhead for strings that do not contain the split delimiters.

## 2024-08-20 - [Fast-fail string sanitization for numbers]
**Learning:** Functions designed to sanitize noisy numeric strings (like `clean_val` removing commas, dollar signs, and parentheses) often unnecessarily apply these string operations (like `.replace()` or `.strip()`) to inputs that are already perfectly clean numbers (e.g., `"123.45"`). This incurs unnecessary string allocation and traversal overhead on the happy path.
**Action:** When parsing potentially noisy numerical data, always implement a fast-fail path by attempting an immediate `float()` conversion inside a `try/except` block as the absolute first step. This bypasses all string stripping and native replacements entirely for already perfectly clean inputs.
## 2024-11-30 - [Fast-fail Float Parsing]
**Learning:** For utility functions that clean and parse numerical strings (like `clean_val`), attempting a direct `float()` conversion as the absolute first step is significantly faster (~4x speedup) than executing native string stripping and replacements first (e.g., removing `$`, `,`, `%`, `()`) for perfectly clean inputs.
**Action:** When parsing potentially noisy numerical data, always create a "fast path" using an immediate `float()` conversion inside a `try/except` block to bypass all string operations completely for clean inputs.

## 2024-11-30 - [Fast-fail string sanitization for numbers to bypass replacements]
**Learning:** Found that string preprocessing functions for noisy numeric strings (like `clean_val`) often apply multiple `.replace()` and `.strip()` operations (e.g. for commas, dollar signs, parentheses) even when the string doesn't contain these characters, simply because they contain other non-numeric characters (like `"12.3 abc"`). This incurs unnecessary string allocation and traversal overhead.
**Action:** When parsing potentially noisy numerical data, after fast-path float attempts fail, implement a fast-fail path for strings lacking formatting characters using `if "," not in val_str and "$" not in val_str and "%" not in val_str and "(" not in val_str:` to bypass string replacements and directly extract numbers via regex.

## 2024-11-30 - [Fast-fail pattern for parsing positive noisy strings]
**Learning:** Found that string preprocessing functions for noisy numeric strings (like `clean_val`) often apply multiple `.replace()` and `.strip()` operations (e.g. for commas, dollar signs, parentheses) even when the string doesn't contain these characters, simply because they contain other non-numeric characters (like `"12.3 abc"`). I attempted to bypass these operations using a fast-fail condition that checks for the absence of specific formatting characters (`if "," not in val_str and "$" not in val_str and "%" not in val_str and "(" not in val_str:`). However, I failed to realize that the function manually processes the minus sign (`-`) later in the function. Since the regex only returns unsigned numbers (because of the manual negation check later), skipping the entire function block caused negative numbers to be parsed as positive.
**Action:** When implementing bypass optimizations in string parsers, make sure all conditions that alter the core business logic (such as negative values `"-"`) are strictly accounted for in the exclusion logic.
## 2024-11-30 - [Lazy boundary resolution via reverse search]
**Learning:** When resolving positional boundaries inside huge texts (e.g., matching a keyword to its enclosing section chunk), parsing the entire document upfront to build a boundary map (even with fast native string methods) incurs significant O(N) traversal overhead. Lazily finding the nearest boundaries on demand using native reverse search (`str.rfind()`) from the matched position completely bypasses the full-document parse overhead.
**Action:** When mapping keyword matches to their enclosing chunk or section, avoid upfront whole-document parsing. Use `.rfind()` backwards from the match index to extract the enclosing boundaries locally.
## 2024-11-30 - [Safe fast-fail for parsing floats]
**Learning:** When creating fast-fail parsing optimizations in functions like `clean_value` (e.g. using `float()` to parse cleanly formatted numbers directly to bypass `.replace()` calls), it is crucial to handle edge cases like booleans (`float(True)` is `1.0`), `NaN`, and `Inf`, which the original string replacement/regex logic may have correctly failed on (or ignored). Also, the fast-fail condition that bypasses string replacements must ensure it correctly accounts for spaces if the original logic strips spaces for formatted numbers (e.g. `"1 000"`).
**Action:** Always test fast-fail string bypass paths by considering booleans, `NaN`/`Inf`, and space separators, ensuring semantic equivalence with the original (often slower) logic. Guard `NaN` and `Inf` with `math.isnan` and `math.isinf` and verify that spaces are also excluded from the bypass path.
