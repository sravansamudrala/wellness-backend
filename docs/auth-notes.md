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
  - *Slow (work factor)* — makes brute-force expensive (`$2b$12$…` → factor 12).
- **Login** = hash the submitted password and compare; never "decrypt."
- Functions: `hash_password()`, `verify_password()` in `app/core/security.py`.

## 3. JWT structure — 3 parts, dot-separated
```
header . payload . signature
```
| Part | Contents | Notes |
|---|---|---|
| header | `{"alg":"HS256","typ":"JWT"}` | which algorithm (metadata) |
| payload | `{"sub": user_id, "exp": expiry}` | the claims; holds the user id. base64 only → **readable by anyone**. Never put secrets here. |
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
 → create_access_token(user.id)  → payload {sub, exp}, sign w/ secret
 → return {access_token, token_type:"bearer"}
 → UI stores it in localStorage
```
Extracted + verified (every later request):
```
UI axios interceptor → header: Authorization: Bearer <token>
 → HTTPBearer extracts token from header
 → decode_token → jwt.decode: recompute HMAC w/ secret, compare, check exp
   • valid   → read user_id from `sub`
   • invalid → 401 (endpoint never runs)
 → service filters queries by user_id
```

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
| token → `user_id` per request | `app/api/deps.py` `get_current_user` (+ `HTTPBearer`) |
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