# ASKa-Piyu Cybersecurity Audit Report

| Field | Value |
|-------|--------|
| **System** | ASKa-Piyu (Flutter + FastAPI + PostgreSQL + Chroma + nginx/Docker) |
| **Scope** | Full repository static review |
| **Date** | 2026-07-26 |
| **Assessor role** | Security review (static analysis; no live pentest / CVE DB scan) |
| **Branch reviewed** | `main` + local security hardening (logout, XFF, PDF auth, signup, HSTS) |

---

## 1. Executive summary

ASKa-Piyu is in **good security posture** for a campus RAG chatbot + ticketing platform.

| Metric | Result |
|--------|--------|
| Critical code vulnerabilities | **0** |
| High code vulnerabilities | **0** (High residual is **ops**: do not expose lab HTTP) |
| Medium residual (code + ops) | Several — see §4 |
| Injection / SSRF / classic IDOR | **Not found** under reviewed controls |
| Production readiness (security) | **Near-ready** — ship with HTTPS overlay + signup policy + secret rotation |

**Verdict:** Safe to proceed to campus deployment **if** operators use the HTTPS Compose overlay, set production secrets, tighten signup (domain/invite or disable), and protect backups. Do **not** expose the lab HTTP `:8080` stack to the public internet.

---

## 2. Scope and method

### In scope
- Authentication & session management
- Authorization / IDOR / privilege escalation
- Secrets & credential handling
- Injection (SQL, command, path)
- File upload / download confinement
- XSS / CSRF / CORS
- Rate limiting / abuse / DoS
- SSRF / outbound HTTP
- Crypto / TLS configuration
- Database & backup exposure
- Dependencies (manifest review; no live CVE feed)
- Docker / nginx / CI misconfiguration
- Privacy / PII / logging
- Business logic (tickets, KB, guest Ask, signup)

### Out of scope / not performed
- Dynamic penetration testing against a live host
- Automated dependency CVE database correlation
- Physical / social engineering / office process review
- Source-code license compliance

### Method
Static review of application routes, services, Flutter client storage, Compose/nginx deploy configs, and security-focused tests (`test_security_hardening.py`, auth, document citations).

---

## 3. Security strengths (correctly implemented)

1. **Password hashing** — PBKDF2-SHA256, 210,000 iterations, random salt, constant-time verify (`backend/app/services/passwords.py`).
2. **JWT sessions** — HMAC-SHA256, expiry check, signature compare; authorization uses DB `User.role` / `is_active` / `credentials_version`, not a spoofable role claim alone.
3. **Session revocation** — Logout, password change, admin reset, and account disable bump `credentials_version` (invalidates outstanding JWTs).
4. **Production startup gates** — Rejects missing/placeholder auth secret, CORS `*`, localhost-only CORS, and unsafe `create_all` in production.
5. **Ticket authorization** — Owner / assigned office / admin checks; cross-user IDOR covered by tests.
6. **Source PDFs** — Require login; faculty manuals restricted to faculty/admin.
7. **Uploads** — Magic-byte allowlist, size limits, path jail for ticket attachments and stored documents.
8. **Postgres / Chroma** — Not published to the host in production Compose; volumes only.
9. **Edge + app rate limits** — nginx zones for login/signup/Ask; in-app limits; proxy uses `X-Real-IP` / `$remote_addr` (not client-spoofable leftmost XFF).
10. **OpenAPI** — Disabled by default in production.
11. **Hard-delete hygiene** — User hard-delete removes ticket attachment files after successful DB commit.
12. **Signup controls** — Optional domain allowlist, invite code, and `ASKA_ALLOW_PUBLIC_SIGNUP=false`.
13. **HSTS** — Enabled on the HTTPS nginx overlay.
14. **CORS** — Bearer tokens (low classic CSRF risk); production origins must be explicit HTTPS hosts.

---

## 4. Findings register

Severity: **Critical** > **High** > **Medium** > **Low** > **Informational**  
Status: **Open** | **Partial** | **Fixed** | **Ops-only** | **By design**

### 4.1 Open / residual risks

| ID | Severity | Type | Area | Finding | Impact | Recommendation | Status |
|----|----------|------|------|---------|--------|----------------|--------|
| C-1 | **High** | OPS | TLS | Lab HTTP Compose (`:8080`) sends passwords/JWTs in cleartext if used as “production” | Credential theft on network | Deploy only with `docker-compose.https.yml` | Ops-only |
| R-2 | **Medium** | CODE | Abuse | Guest Ask can consume Groq quota within rate limits | Cost / availability abuse | Monitor usage; optional CAPTCHA or stricter anon limits; API spend caps | Open |
| M-1 | **Medium** | OPS | Signup | Public signup defaults **on**; domain/invite optional | Spam student accounts if internet-facing | Set domain allowlist and/or invite, or `ASKA_ALLOW_PUBLIC_SIGNUP=false` | Partial |
| P-1 | **Medium** | CODE | Supply chain | `requirements.txt` uses lower-bound unpinned deps | Non-reproducible / unexpected vulnerable upgrades | Pin or lockfile + Dependabot | Open |
| A-1 | **Medium** | CODE | Web auth | Remember-me JWT in `localStorage` (default off on web now) | XSS on web origin can steal durable tokens | Keep default off; CSP on Flutter web host; consider HttpOnly cookies later | Partial |
| D-2 | **Medium** | OPS | Backups | Backup dumps include full DB + PDFs + attachments, unencrypted by default | Backup theft = full PII | Encrypt off-host; restrict `deploy/backups/` | Ops-only |
| R-1 | **Medium** | CODE+OPS | Rate limit | In-app limits are per-process; multi-worker multiplies budget | Weaker limits if workers > 1 | Keep `--workers 1` (Compose) or enforce only at nginx | Partial |
| S-1 | **Medium** | OPS | Secrets | Lab bootstrap credentials / shared office seed password | Account takeover if not rotated | Rotate and shred `BOOTSTRAP_CREDENTIALS.txt` before public use | Ops-only |
| A-2 | **Low** | CODE | Auth | Login skips `verify_password` when user missing (timing) | Coarse email enumeration | Dummy hash verify on miss | Open |
| A-3 | **Low** | CODE | Signup | `hmac.compare_digest` on invite can error on length mismatch | Possible 500 during guessing | Pad/hash before compare | Open |
| F-1 | **Low** | CODE | DoS | Admin 50 MB PDF + OCR can stress CPU/memory | Admin-path DoS | Keep admin-only; monitor; optional async queue | Open |
| C-3 | **Low** | OPS | Headers | API proxy lacks `X-Content-Type-Options` / frame / CSP | Residual browser hardening | Add security headers on nginx | Open |
| V-1 | **Low** | CODE | Logging | QA debug may log full context when DEBUG on | PII in log sinks | Keep DEBUG off in prod | Open |
| B-2 | **Low** | CODE | Tickets | Students may set preferred office | Misrouting / spam | Accept or restrict | By design |
| B-3 | **Low** | CODE | Tickets | Office on-behalf email reveals account existence | Enumeration by office role | Generic error | Open |
| B-1 | **Medium** | CODE | LLM | Prompt injection / mis-answer within retrieved context | Misleading campus guidance | Human escalation via tickets; monitor answers | Open (inherent) |
| Z-1 | **Low** | CODE | Authz | Authenticated students can fetch full student-audience PDF by ID | Broader than single cited page | Accept for citation UX or serve page-only | By design |

### 4.2 Recently fixed (confirmed in current code)

| Fix | Evidence | Status |
|-----|----------|--------|
| Logout revokes JWT | `POST /auth/logout` + `credentials_version` | **Fixed** |
| XFF rate-limit spoofing | Prefer `X-Real-IP`; nginx XFF=`$remote_addr` | **Fixed** |
| Guest source PDF download | `/documents/.../source` requires login | **Fixed** |
| Hard-delete leaves files | Attachment unlink after commit | **Fixed** |
| Signup hardening controls | Domain / invite / disable flags | **Fixed** (must enable in ops) |
| HSTS | `deploy/nginx.https.conf` | **Fixed** (HTTPS overlay) |
| Signup email enumeration message | Generic 409 text | **Fixed** |

### 4.3 Not found (clean under review)

| Class | Result |
|-------|--------|
| SQL injection (user-controlled) | Not found — ORM usage |
| Command injection / `eval` / unsafe pickle | Not found in app code |
| SSRF (user-controlled URL fetch) | Not found — Groq URL fixed |
| Classic ticket IDOR | Not found — role/office checks + tests |
| Privilege escalation via JWT role claim | Not found — DB role authoritative |
| Secrets committed to git | Not found — `.env` / certs / bootstrap gitignored |
| CSRF against cookie sessions | N/A — Bearer Authorization |

---

## 5. Risk summary

```
Critical (code) .... 0
High (ops) ......... 1  — exposing lab HTTP as campus prod
Medium ............. ~7 — signup default, Groq abuse, deps, web JWT, backups, workers, secrets rotation
Low ................ several — timing, headers, logging, office email oracle
Informational ...... strengths + design trade-offs
```

**Overall risk rating for a correctly configured HTTPS campus deploy:** **Low–Moderate**  
**Overall risk rating if lab HTTP is internet-facing:** **High**

---

## 6. Priority remediation roadmap

### Before public go-live (ops — mandatory)
1. Deploy with `docker-compose.yml` + `docker-compose.https.yml` only.
2. Run `check_production_env.py`; set strong `ASKA_AUTH_SECRET_KEY`, `POSTGRES_PASSWORD`, Groq key, HTTPS CORS origins.
3. Enable signup policy: domain allowlist and/or invite code, **or** disable public signup.
4. Rotate all bootstrap / seed passwords; remove plaintext credential files from disk.
5. Schedule encrypted off-host backups; restrict backup directory ACLs.
6. Keep API at `--workers 1` unless rate limits are moved entirely to the edge.

### Near-term code hardening (optional)
1. Pin Python dependencies / add lockfile + automated CVE alerts.
2. Equalize login password-verify timing; length-safe invite compare.
3. Add nginx security headers (`X-Content-Type-Options`, `X-Frame-Options` or CSP on web host).
4. Cap or CAPTCHA anonymous Ask if Groq cost becomes an issue.

---

## 7. Compliance / privacy notes (campus)

- Tickets and user profiles contain **PII** (name, email, student ID, free-text issues). Limit admin/office accounts.
- Hard-delete supports removal of user + tickets + attachment files (prefer **disable** for normal offboarding).
- FAQ generation from tickets includes heuristic PII redaction — treat as best-effort, not perfect anonymization.
- Guest Ask is intentional: public Q&A with **student** audience filtering; tickets remain login-gated.

---

## 8. Conclusion

The codebase demonstrates intentional security engineering for a campus deployment: strong password hashing, revocable sessions, production config gates, ticket IDOR controls, path-confined uploads, audience-filtered RAG, and a hardened HTTPS deploy path.

**No critical application vulnerabilities** were identified in this static review. Remaining risk is dominated by **operator choices** (TLS, signup policy, secret rotation, backup custody) and a small set of **Medium** residual code items (dependency pinning, guest Ask cost abuse, web durable token storage).

**Recommendation:** Proceed to campus HTTPS go-live after completing §6 mandatory ops steps. Schedule a follow-up dependency CVE scan and optional dynamic test after the host is online.

---

## 9. Document control

| Version | Date | Notes |
|---------|------|-------|
| 1.0 | 2026-07-26 | Full static audit + recent High/Medium hardening included |

*This report is based on repository evidence. It is not a formal certification or penetration-test attestation.*
