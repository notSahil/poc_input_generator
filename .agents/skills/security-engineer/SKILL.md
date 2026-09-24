---
name: security-engineer
description: Enforces industry-standard application security (AppSec), OWASP Top 10 defensive patterns, credential safety, and secure coding across Python, Salesforce, and Streamlit.
---

# Enterprise Security Engineer: Secure Coding Standards

When this skill is activated, enforce rigorous application security standards across all code design, modifications, reviews, and infrastructure configurations.

---

## 1. Credentials & Secrets Management (Zero Leaks Policy)

- **Never Commit Secrets**: Hardcoded passwords, API keys, private keys (`.key`, `.pem`), client secrets, or OAuth tokens must NEVER appear in source code, commit history, or comments.
- **Environment Isolation**: All sensitive values must be read from environment variables or secure credential files registered in `.gitignore` (e.g. `.env`, `.sf_auth_*.json`, `*.key`).
- **Telemetry & Log Masking**:
  - Never print or log raw Salesforce access tokens, instance URLs with auth codes, or user credentials.
  - In log outputs and error reports, sanitize or redact sensitive values (e.g., `token[:4] + '...' + token[-4:]`).
  - Sanitize exceptions: do not let raw connection strings or stack traces expose database credentials to the UI.

---

## 2. Injection Prevention (SOQL, SQL & Shell)

- **Salesforce SOQL Injection**:
  - Never construct SOQL queries by blindly concatenating untrusted user inputs with raw strings:
    ```python
    # ❌ INSECURE: Vulnerable to SOQL Injection
    query = f"SELECT Id, Name FROM sitetracker__Site__c WHERE Name = '{user_input}'"

    # ✅ SECURE: Sanitize input or escape single quotes
    safe_input = user_input.replace("\\", "\\\\").replace("'", "\\'")
    query = f"SELECT Id, Name FROM sitetracker__Site__c WHERE Name = '{safe_input}'"
    ```
  - For lists of IDs or references, validate format (alphanumeric/UUID) before interpolating into `WHERE Id IN (...)`.
- **Command & Subprocess Injection**:
  - Avoid `shell=True` in `subprocess.run()` or `os.system()`.
  - Pass command arguments as explicit lists: `subprocess.run(["git", "status"], check=True)`.

---

## 3. Spreadsheet & CSV Formula Injection (Formula Hashing/Escaping)

When generating CSV files for user download, prevent Formula Injection (CSV Injection) where an attacker crafts cell values starting with `=,+,-,@,\t,\r` that Excel interprets as formulas:
- In `csv_sanitizer.py` and CSV export utilities:
  - If a text cell begins with `=`, `+`, `-`, `@`, `\t`, or `\r`, prepend a single quote `'` or prefix to neutralize formula execution.
  - Strip leading/trailing control characters from user data.

---

## 4. Path Traversal & File System Boundaries

- **Resolve & Validate**:
  - When accepting user-supplied filenames or report IDs, sanitize against directory traversal (`../` or `..\`).
  - Use `pathlib.Path.resolve()` to verify that the target path is strictly within the allowed root directory:
    ```python
    target_path = (base_dir / user_supplied_path).resolve()
    if not target_path.is_relative_to(base_dir.resolve()):
        raise SecurityError("Access denied: path traversal attempt detected.")
    ```
- **Safe File Operations**:
  - Restrict permissions on sensitive cache or state files (`chmod 600` on generated auth tokens and private keys).

---

## 5. Streamlit Frontend Security (XSS & Session Safety)

- **Cross-Site Scripting (XSS)**:
  - Avoid `st.markdown(..., unsafe_allow_html=True)` with unescaped user-supplied inputs or file contents.
  - If HTML rendering is required, explicitly sanitize user values using `html.escape()`.
- **Session State Isolation**:
  - Reset ad-hoc mapping caches and credentials across different uploads to prevent cross-file data leakage.
  - Never expose administrative or destructive actions (such as rollback or batch upload) without explicit user confirmation barriers.

---

## 6. Transport Security & Network Hardening

- **HTTPS Everywhere**:
  - All public traffic must be encrypted over TLS 1.3 / TLS 1.2 with HSTS (`Strict-Transport-Security`).
  - Internal application processes (e.g. Streamlit on `8501`, code-server on `8080`) must bind to `127.0.0.1` and be reverse-proxied through a hardened web server (Nginx).
- **HTTP Security Headers**:
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains`
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: SAMEORIGIN`
  - `X-XSS-Protection: 1; mode=block`
  - `Referrer-Policy: strict-origin-when-cross-origin`
- **Upload Size Bounds**:
  - Enforce explicit request body limits (e.g., `client_max_body_size 100M`) to prevent memory exhaustion Denial of Service (DoS).

---

## 7. Automated Security Verification (SAST & Audit)

When auditing or reviewing code, run automated security checks:

```bash
# 1. Static Application Security Testing (SAST) with Bandit
uv run bandit -r core/ salesforce/ ui/ config/ -ll

# 2. Dependency Vulnerability Audit
uv run pip-audit  # or uv audit
```

- **Bandit Severity**: Zero High or Medium severity vulnerabilities allowed in production code.
- **Fail-Safe Defaults**: If a security check or token validation fails, fail closed (abort operation and log audit event), never fail open.
