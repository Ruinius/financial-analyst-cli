## 2025-02-25 - Fix Path Traversal
**Vulnerability:** Path traversal vulnerability in `src/services/edgar_client.py` due to unsanitized SEC API filenames.
**Learning:** APIs can return malicious data and should not be fully trusted.
**Prevention:** Sanitize all external inputs, even from trusted APIs, before using them in file paths.
## 2025-03-05 - Missing Input Length Limits in API endpoints
**Vulnerability:** The `do_POST` endpoint in `src/viewer/server.py` lacked a limit on the `Content-Length` header, making it susceptible to Denial of Service (DoS) attacks via memory exhaustion from extremely large payloads.
**Learning:** Python's built-in `http.server.SimpleHTTPRequestHandler` does not automatically restrict payload sizes. When directly reading `self.rfile.read(content_length)`, it will attempt to allocate memory for the full length specified, which can crash the server if unbounded.
**Prevention:** Always enforce a maximum payload size limit (e.g., `MAX_PAYLOAD_SIZE = 1048576` bytes) before calling `rfile.read()`, returning a `413 Payload Too Large` response if the limit is exceeded.
## 2025-03-05 - SSRF and XSS Fix in Viewer
**Vulnerability:** The `do_OPTIONS` method in `src/viewer/server.py` was vulnerable to Server-Side Request Forgery (SSRF) bypass due to a weak `.startswith()` origin check. Furthermore, `src/viewer/index.html` was vulnerable to Cross-Site Scripting (XSS) due to unsafe `.innerHTML` assignment.
**Learning:** `startswith` string checks for URLs are inherently insecure and easily bypassed (e.g., `http://localhost:3000.evil.com`). Using `.innerHTML` allows execution of arbitrary scripts injected through APIs.
**Prevention:** Always parse URLs securely using `urllib.parse.urlparse` and validate the `.hostname` strictly. Use safe DOM manipulation methods such as `document.createElement`, `appendChild`, and `.textContent` instead of `.innerHTML`.
## 2025-03-05 - Path Traversal in SEC Filing Download
**Vulnerability:** The `download_filings` method in `src/services/edgar_client.py` constructed file paths using the `accessionNumber` from the SEC API response without sanitization (`f"{accession}_{safe_doc_name}"`), allowing an attacker or compromised upstream to perform path traversal attacks using `../../../`.
**Learning:** Even though we already sanitize the `doc_name`, any untrusted input combined in a file path must be thoroughly sanitized. Path joining combined with unsanitized prefixes allows escaping intended directories.
**Prevention:** Always sanitize all parts of a dynamically constructed path derived from external sources, for instance by stripping non-alphanumeric characters or restricting to expected formats (`re.sub(r'[^a-zA-Z0-9_-]', '', input)`).
## 2026-06-14 - Exponentiation DoS Vulnerability
**Vulnerability:** The mathematical expression evaluator in `src/services/math_solver.py` allowed exponentiation operations with bases and exponents up to 10,000. Python's arbitrary-precision integers mean `10000**10000` (or nested expressions like `9**9**9`) can easily consume enough CPU and memory to cause a Denial of Service (DoS) when exposed to users via the `fa chat` `= expr` interface.
**Learning:** Even when using `ast.parse` and restricting allowed operators safely, the inherent complexity of certain operators (like `**`) can be abused. High limits (like 10000) are not always safe enough for CPU-intensive mathematical operations.
**Prevention:** Strictly limit input sizes and operator arguments (e.g. limit `left` and `right` operands for `ast.Pow` to `100` or less) when executing untrusted mathematical expressions to prevent resource exhaustion attacks.
