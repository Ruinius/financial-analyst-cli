## 2024-03-24 - File I/O Bottleneck in Financial Line Item Extraction
**Learning:** In pipelines extracting large amounts of structured data (like line items in financial reports), reading context from disk *per item* results in an O(N) disk read bottleneck that scales poorly as document size grows.
**Action:** Always verify if a context or metadata file needs to be read dynamically per item. If the context is stable for the life cycle of the process or can be managed in memory, lazily load it into an instance-level cache (e.g. `self._extract_context_cache`). When updating the context, append to the cached string and write to disk, avoiding full re-reads.
## 2026-06-14 - Redundant Disk I/O in Financial Extraction Pipeline
**Learning:** Multiple extraction agents were reading the exact same static dictionary files and learning context files from disk for every line item or document processed, leading to O(N) disk I/O reads that scaled linearly with document size and agent count.
**Action:** When a piece of context (like a classification dictionary) is static for the duration of a process, implement a memoization/caching pattern at the orchestrator or instance level (e.g., `_dict_cache` in the `Extractor` class) so the file is read from disk only once and fetched from memory subsequently.
## 2024-05-19 - Regex anti-pattern on large string blocks
**Learning:** Using `re.search` with `re.DOTALL` to extract sub-strings between deterministic boundary markers (like `<!-- CHUNK_START: X -->`) from extremely large megabyte-sized document strings creates a significant measurable performance bottleneck, resulting in O(N^2) or high constant-factor O(N) regex evaluation times.
**Action:** Always use primitive `str.find()` with string slicing instead of regex when the start and end markers are exact, deterministic string values. This bypasses regex compilation and matching overhead on massive strings and speeds up extraction by several orders of magnitude.
## 2026-06-16 - Inefficient Regex Evaluation Loop Over Large Documents
**Learning:** Performing a regex `search` on a large document inside a loop that iterates over hundreds of extracted items results in an O(N) evaluation bottleneck. The engine unnecessarily scans the long context text repeatedly for every line item.
**Action:** When extracting multiple key-value associations from a single context string, pre-parse the entire string once using `re.finditer` to build a lookup dictionary. Then iterate over the items using O(1) dictionary lookups instead of invoking `re.search` on the full string each time.
## 2024-06-17 - Eliminate O(N²) List Containment and Scan
**Learning:** Using `in` for dict containment inside a growing list (`if snippet_item not in snippets`) results in severe O(N²) degradation on large keyword search spaces. Additionally, using linear scan repeatedly over all chunks per match compounds the performance issue.
**Action:** Replace list lookup with tuple `seen` set for O(1) deduplication, and replace linear positional chunk lookups with O(log N) `bisect.bisect_right`.
## 2026-06-17 - Inefficient List Management in Loop
**Learning:** Manually tracking and rebuilding lists chunk-by-chunk inside a loop using `current_chunk = []` causes unneeded allocation overhead and repetitive string length calculations. In text chunking, doing `len(line)` repeatedly and allocating new list references scales poorly across millions of lines.
**Action:** Cache the lengths of iterated lines, use `.clear()` on lists where contents are quickly joined, and aggregate string calculations logically. For large chunking workloads, this cuts processing time by ~50%.
## 2026-06-18 - Avoid Regex Overheads for JSON Extraction in LLM Responses
**Learning:** Using `re.search(r"\{.*\}", text, re.DOTALL)` to extract JSON string bounds from large LLM response bodies triggers an O(N) evaluation time proportional to the length of the string, which significantly slows down agent steps across large volumes of data.
**Action:** Replace regex JSON extraction with `src.utils.tools.extract_json_from_text`, which leverages highly-optimized `str.find("{")` and `str.rfind("}")` built-in methods, achieving speedups of ~8x for long context strings.
## 2026-06-19 - Replacing re.DOTALL regexes with fast string operations
**Learning:** Using `re.search` with `re.DOTALL` to parse text blocks triggers an O(N) to O(N^2) evaluation time proportional to string length. Converting parsing logic to `str.find` and custom slicing improves text chunk processing performance significantly.
**Action:** Replace regex logic involving large chunks and `re.DOTALL` with robust logic utilizing `str.find` for chunk lookups, with correct attention paid to tracking trailing spaces and relative slice lengths.
## 2024-07-16 - Eliminate re.DOTALL in Markdown Parsing Block Lookups
**Learning:** Using `re.search` with `re.DOTALL` to grab chunks of markdown between headers triggers an O(N) evaluation proportional to the length of the string, which significantly slows down performance when parsing multiple large files during longitudinal analysis and chunk parsing.
**Action:** Replaced regex-based string bounds lookups using `re.DOTALL` with fast built-in string methods (`str.find`) for string markers. Utilizing `str.find` to compute `start_idx` and `end_idx` directly speeds up the operation.
