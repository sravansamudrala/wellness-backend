# Auth & JWT — Study Notes

Notes for the multi-user auth feature (custom FastAPI JWT + `users` table).

## 1. The goal
Turn a single-user app into multi-user: **a token proves *who* you are; a `user_id`
column + query filter controls *what* you can see.** Data isolation is just
`WHERE user_id = <you>` on every query — the hard part is reliably knowing who's
asking, which the JWT solves.

## 2. Password hashing (bcrypt)
- **Never store plaintext passwords.** Store a **one-way hash**.
- bcrypt properties:
  - *One-way* — can't reverse hash → password.
  - *Salted* — random salt per password, so the same password → different hashes
    (beats rainbow tables). The salt is stored inside the hash string.
  - *Slow (work factor)* — makes brute-force expensive (`$2b$10$…` → factor 10;
    lowered from bcrypt's default of 12 since 12 rounds took ~2.6s on Render's
    weak free-tier CPU — still within OWASP's recommended floor).
- **Login** = hash the submitted password and compare; never "decrypt."
- Functions: `hash_password()`, `verify_password()` in `app/core/security.py`.

## 3. JWT structure — 3 parts, dot-separated
```
header . payload . signature
```
| Part | Contents | Notes |
|---|---|---|
| header | `{"alg":"HS256","typ":"JWT"}` | which algorithm (metadata) |
| payload | `{"sub": user_id, "ver": token_version, "exp": expiry}` | the claims; holds the user id and a version number used to invalidate old sessions (see §6.1). base64 only → **readable by anyone**. Never put secrets here. |
| signature | `HMAC_SHA256("header.payload", JWT_SECRET)` | the tamper-proof seal |

- **Stateless**: no server-side session store — the token carries the identity.
- `exp` makes it auto-expire.

## 4. HMAC & HS256
- **HMAC** = Hash-based Message Authentication Code → a fingerprint of a message
  made with a **secret key**; only the key-holder can produce/verify it.
- **HS256** = **HMAC + SHA-256**.
  - SHA-256 = one-way hash (any input → 256-bit digest).
  - HMAC = wraps the hash with the secret key → unforgeable without the key.
- Roles when signing:
  ```
  signature = HMAC( key = JWT_SECRET , message = "header.payload" )
                    private, stays          public, rides in token
                    on backend
  ```
- **Symmetric** (same secret signs + verifies) → right for one backend.
  Asymmetric (RS256/ES256: private signs, public verifies) is for when a
  different party verifies.

## 5. The secret (`JWT_SECRET`)
- A long random value in **backend env only** (Render + local `.env`).
- Used as the **key** to sign/verify — **never embedded in the token**, never
  sent to the browser.
- Analogy: signature = wax seal (travels); secret = signet ring (stays home).

## 6. Token lifecycle
Created (once, at login/register):
```
UI sends {email, password}
 → verify password (bcrypt)
 → create_access_token(user.id, user.token_version)  → payload {sub, ver, exp}, sign w/ secret
 → return {access_token, token_type:"bearer"}
 → UI stores it in localStorage
```
Extracted + verified (every later request):
```
UI axios interceptor → header: Authorization: Bearer <token>
 → HTTPBearer extracts token from header
 → decode_token_claims → jwt.decode: recompute HMAC w/ secret, compare, check exp
   • invalid/expired signature → 401 (endpoint never runs)
   • valid → read user_id from `sub`, look up that user's *current*
     token_version in the DB, compare against the token's `ver` claim
     • match    → proceed
     • mismatch → 401 (an old session from before a password reset)
 → service filters queries by user_id
```

### 6.1 Session invalidation on password reset
JWTs are otherwise stateless (no server-side session store), which normally
means there's no way to "log out" a specific already-issued token before its
natural 30-day expiry — a stolen token would keep working even after the
legitimate user notices and resets their password. `User.token_version`
(default `0`) closes that gap cheaply: `AuthService.reset_password` bumps it
by 1 on every successful reset, and `get_current_user` (`app/api/deps.py`)
compares the token's embedded `ver` against the user's current
`token_version` on every request — a stale value means the token predates a
reset and is rejected, regardless of its signature/expiry still being valid.

A missing `ver` claim (a token minted before this feature shipped) is treated
as version `0`, so already-logged-in sessions survive the deploy; they're
only invalidated the next time that specific user resets their password.

This does add one indexed DB lookup (`SELECT token_version FROM users WHERE
id = ...`) to every authenticated request — deliberately *not* cached, after
a design review found a cache introduces a real race condition (a stale read
could transiently un-invalidate a reset token). Measured negligible
(low tens of ms) now that Render sits in the same region as Supabase; revisit
only if real load ever shows otherwise.

## 7. What's in the request
| Location | Holds |
|---|---|
| Header `Authorization: Bearer <token>` | the token |
| Body (JSON) | operation data only (`{email,password}` on login; feature data otherwise) |
| `user_id` | NEVER sent by client — **derived server-side from the verified token** |

Crucial rule: the client never sends its own `user_id` (else anyone could
impersonate). It comes from the token.

## 8. Data ownership model
- **Shared (no `user_id`):** exercise catalog, muscle groups, equipment, seeded
  template plans.
- **Per-user (`user_id` + filtered):** skincare entries, reminder settings, push
  subscriptions, gym state, workout sessions.
- **Legacy data:** first account to register "claims" existing rows (stamps them
  with its `user_id`).

## 9. Where it lives in the code
| Concern | File · function |
|---|---|
| hashing + JWT create/verify | `app/core/security.py` |
| auth config (`jwt_secret`, expiry) | `app/core/config.py` |
| `User` table | `app/models/user.py` |
| token → `user_id` per request (+ session-invalidation check) | `app/api/deps.py` `get_current_user` (+ `HTTPBearer`) |
| register/login logic | `app/services/auth_service.py` |
| `/register /login /me` routes | `app/api/auth.py` |
| `user_id` columns + query scoping | models + services |
| frontend: store/attach token, login page, guards | `AuthContext`, `api.ts`, `Login.tsx`, `App.tsx` |

## 10. Security rules of thumb
- Hash passwords (bcrypt), verify by re-hashing.
- Keep `JWT_SECRET` in env, never in code/token/client.
- Derive `user_id` from the token, never trust it from the body.
- Verify signature AND expiry on every request.
- Never put secrets in the payload (it's readable).
- Never store plaintext passwords or log tokens.
- Bump `User.token_version` on any credential-changing action (password reset
  today; a future explicit "change password" or "log out everywhere" would
  do the same) — it's the cheap way to invalidate stateless tokens per-user.

## 11. Secrets rotation plan — what to actually do if one leaks

No tooling needed for this app's scale (solo maintainer) — just knowing the steps per secret:

| Secret | If it leaks, do this | Consequence of rotating |
|---|---|---|
| `JWT_SECRET` | Generate a new value (`python -c "import secrets; print(secrets.token_urlsafe(64))"`), update in Render + redeploy. | **Every** existing token fails verification instantly — all users logged out, must log in again. Cheap, acceptable. (For a *single* compromised account rather than a leaked secret, resetting that user's password is the targeted equivalent — see §6.1 — no need to rotate the shared secret for everyone.) |
| `DATABASE_URL` | Rotate the DB password from Supabase's dashboard, update `DATABASE_URL` in Render + local `.env`, redeploy. | Brief reconnect blip only. **Highest urgency to rotate fast** — this is the one that exposes actual user data (real DB access) if delayed. |
| `VAPID_PRIVATE_KEY` / `VAPID_PUBLIC_KEY` | Generate a fresh VAPID keypair, update both the backend env var and the frontend's `VITE_VAPID_PUBLIC_KEY`, redeploy both. | Every existing push subscription breaks (tied to the old public key) — users must reopen the PWA to re-subscribe. Lower urgency; leaked key alone isn't very exploitable without separately-obtained subscriber endpoints. |
| `DISPATCH_TOKEN` | Generate a new token, update in Render, update the saved URL in the cron-job.org config, redeploy. | Low actual damage if leaked before rotating — sends are already deduped per `(user, day, slot)`, so worst case is wasted compute, not spam. |

None of these require a code change — rotation here just means "generate a new value, update it in Render/`.env`/the cron config, redeploy." The only thing worth remembering: `DATABASE_URL` is the one to act on fastest, since it's the only leak with a direct path to real user data.