## 2025-02-25 - Fix Path Traversal
**Vulnerability:** Path traversal vulnerability in `src/services/edgar_client.py` due to unsanitized SEC API filenames.
**Learning:** APIs can return malicious data and should not be fully trusted.
**Prevention:** Sanitize all external inputs, even from trusted APIs, before using them in file paths.
