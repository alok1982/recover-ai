# CR-04 — Role picker at registration, admin approval for the bank role

Status: implemented (Oct 2026). Builds on CR-03 (phone + password victim accounts).

## What the user asked for
- **Home page and signup** get a role picker: *I've been scammed* (victim, default) or *I work at a bank (fraud team)*.
  - Victim signup is unchanged: phone + password, then straight to `/cases`.
  - Bank staff signup: work email + password, full name, bank (per-country list or Other), employee ID, designation,
    optional note. It creates the Firebase user and `bank_access_requests/{uid}` with status `PENDING`.
    It does **not** grant `role: bank`. After login the applicant sees a *Pending admin approval* page with no bank data.
- **Single login, role-based redirect**: `role: bank` → bank desk (`/bank`), `role: admin` → admin console (`/admin`),
  pending/rejected/revoked applicant → `/pending`, anyone else (phone account) → victim `/cases`. `next=` is kept when
  it fits the role. `/bank` and the existing analyst login keep working with the same password.
- **Admin console `/admin`**: needs the `role: admin` custom claim. Lists pending, approved, rejected and revoked
  requests. Approve sets the custom claims `role: bank` + `bankId`; Reject records a reason; Revoke removes the claim.
  Every action writes an audit entry (who, when, what, reason). The client forces `getIdToken(true)` (login and
  *Check again*) so the redirect works right after approval.
- **APIs**: `POST /api/bank-access/request`; `GET /api/me` (adds `role`, `requestStatus`); admin only:
  `GET /api/admin/bank-requests?status=`, `POST /api/admin/bank-requests/{uid}/approve`, `POST …/reject`,
  `POST /api/admin/users/{uid}/revoke-bank` (plus `GET /api/admin/audit` for the console).
- **Admin bootstrap**: `scripts/create_admin.py` (run from the box with gcloud ADC, never from Cloud Run) creates
  `admin@recoverai-demo.example` with a generated password in git-ignored `deploy/.state/admin_password`.
- A seeded pending applicant keeps the admin queue non-empty for demos.
- i18n: EN/HI/MS for victim-facing text (role picker); admin and bank UI in English.

## Design decisions
- **Two account kinds, two Firebase app instances.** Victims sign in with phone + password (synthetic
  `<digits>@phone.recoverai.app`); staff sign in with a work email on the separate "bank" Firebase app instance, so
  a victim session and a staff session in the same browser don't interfere.
- **A victim account never becomes a bank account.** `POST /api/bank-access/request` from a phone account returns
  `409 USE_WORK_EMAIL`. Bank staff who were also scammed keep a separate phone account. Mixing victim cases and bank
  access on one uid would let a bank role see (or be confused with) its own victim data.
- **Staff accounts are not victims.** Victim routes reject work-email accounts and `bank`/`admin` roles with
  `403 VICTIM_ACCOUNT_REQUIRED`; no victim profile is created for them.
- **Roles only come from the server.** Claims are set with the Admin SDK (backend for approve/revoke, box script for
  the admin). Request bodies can't set `role`, `status` or `bankId`. Firestore rules deny all client writes.
- **Revoke is immediate.** An issued ID token keeps its claims for up to an hour, so the backend's `bank_user` check
  and the Firestore `isBank()` rule also require the account's access request (if it has one) to be `APPROVED`.
  Revoke also revokes refresh tokens. The seeded analyst has no request document and is unaffected.
- **Admins can't be revoked or given the bank role** from the console, and can't revoke themselves.
- **Audit**: `admin_audit/{id}` = `{at, actorUid, actorEmail, actorRole, action, targetUid, reason, …}` for
  `request_submitted`, `approve`, `reject`, `revoke_bank`, `request_deleted_by_applicant`. Readable only by admins.
- **Rejected or revoked applicants** can re-apply (back to `PENDING`); an admin decides again.
- **`bankId`** defaults to `<country>-<bank-slug>` (e.g. `in-hdfc-bank`), editable before approving. The bank desk
  does not yet filter by `bankId` (out of scope; every bank analyst sees the shared sandbox queue as before).

## IAM
- Cloud Run's service account `recoverai-api@…` gets a **custom role `recoveraiAuthClaims` with the single permission
  `firebaseauth.users.update`** (set custom claims, revoke refresh tokens), the narrowest grant that can set claims.
  Reading claims uses the already-granted `roles/firebaseauth.viewer`. Deleting users isn't granted.
  `./deploy/deploy.sh iam` (also part of `platform`) creates and binds it.
- The admin account is created from the box with the operator's ADC: `./deploy/deploy.sh admin`.

## Data
| Collection | Written by | Readable by |
|---|---|---|
| `bank_access_requests/{uid}` | backend only | the applicant, admins |
| `admin_audit/{id}` | backend only | admins |

## Tests
`backend/tests/test_roles.py`, `firestore-tests/rules.test.mjs` (CR-04 block), `scripts/e2e_demo.py` (Roles
section, mock + live), `scripts/cr04_roles_check.py` (browser flow, mock + live).
