## 2025-02-25 - Fix Path Traversal
**Vulnerability:** Path traversal vulnerability in `src/services/edgar_client.py` due to unsanitized SEC API filenames.
**Learning:** APIs can return malicious data and should not be fully trusted.
**Prevention:** Sanitize all external inputs, even from trusted APIs, before using them in file paths.
## 2025-03-05 - Missing Input Length Limits in API endpoints
**Vulnerability:** The `do_POST` endpoint in `src/viewer/server.py` lacked a limit on the `Content-Length` header, making it susceptible to Denial of Service (DoS) attacks via memory exhaustion from extremely large payloads.
**Learning:** Python's built-in `http.server.SimpleHTTPRequestHandler` does not automatically restrict payload sizes. When directly reading `self.rfile.read(content_length)`, it will attempt to allocate memory for the full length specified, which can crash the server if unbounded.
**Prevention:** Always enforce a maximum payload size limit (e.g., `MAX_PAYLOAD_SIZE = 1048576` bytes) before calling `rfile.read()`, returning a `413 Payload Too Large` response if the limit is exceeded.
