## 2024-06-10 - Path Traversal in Local Viewer Server
**Vulnerability:** A critical path traversal vulnerability was discovered in the `do_GET` handler of `src/viewer/server.py`. The HTTP server directly concatenated user input from the URL (`/api/models/<filename>`) to the base directory path without sanitization, allowing an attacker to read arbitrary files via `../` sequences.
**Learning:** The simple `.replace("/api/models/", "")` does not sanitize URL parameters or prevent directory traversal characters. Using `pathlib.Path` concatenation without resolving and checking bounds is insecure when handling user-provided file names.
**Prevention:** Always use `urllib.parse.unquote` to decode the filename, then use `pathlib.Path.resolve()` to get the absolute path, and finally verify the target is within the intended directory using `is_relative_to(base_dir.resolve())`. Also ensure the target is actually a file using `.is_file()`.

## Arbitrary File Write / Path Traversal in /api/save-scenario
**Vulnerability:**
The `ticker` field was taken directly from the user's JSON payload in `/api/save-scenario` and concatenated into a path to write a JSON file. An attacker could provide a `ticker` string containing path traversal characters like `../` to write arbitrary `.json` files outside the intended models directory, potentially leading to arbitrary file write or overwriting sensitive files.

**Learning:**
We learned that all strings taken from untrusted inputs that will be interpolated into file paths must be strictly sanitized, irrespective of their apparent benign nature or structure in the schema (e.g. `ticker`).

**Prevention:**
Enforce strict validation (like a regex match) or sanitization (like `re.sub(r"[^a-zA-Z0-9_-]", "", ticker)`) for all user-controlled data before it interacts with the file system. Use `resolve()` and ensure that the resulting path falls within the intended directory hierarchy before performing file operations.
