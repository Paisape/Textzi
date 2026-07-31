# Textzi

Textzi is a multi-tenant CPaaS platform for DLT-compliant SMS and WhatsApp Business messaging in
India — self-service DLT registration, prepaid wallet billing, a dashboard for compose/reporting,
and a programmatic API for integrators, alongside a full platform-admin backend (customer
management, rate cards, billing/invoicing, ERPNext accounting sync, and audit trails).

Textzi is a brand of **Paisape Techfin Private Limited**.

## Stack

- **API**: FastAPI + SQLAlchemy 2.0, PostgreSQL 17, Redis (rate limiting), JWT auth.
- **Web**: Vue 3 + Vite + TypeScript + Vuetify (Vuexy admin theme) — a public marketing site plus
  an authenticated dashboard shell that renders entirely different navigation for customers vs.
  platform admins.
- **Accounting**: optional sync to a self-hosted ERPNext instance for invoice generation (falls
  back to an in-app fpdf2-rendered PDF if unconfigured or if a sync attempt fails).

## Local development

1. Copy `.env.example` to `.env` and fill in real values — see the comments in that file for what
   each one does and how to generate secrets. `ENVIRONMENT=development` is fine for local work.
2. `docker compose up --build` — provisions PostgreSQL, Redis, RabbitMQ (provisioned for a future
   async worker, not yet consumed by any code), the API, and an nginx-served production build of
   the frontend.
3. For frontend iteration with hot reload instead of the built nginx image, run the API via Docker
   (`docker compose up postgres redis rabbitmq api`) and the frontend separately:
   ```
   cd apps/web && pnpm install && pnpm dev
   ```
   Dashboard/API at `http://localhost:8000/docs`, frontend at `http://localhost:5173`.

In development, verification codes (email/mobile OTP, team invites) are echoed back directly in
the relevant API response (`dev_email_code`, `dev_mobile_code`, `dev_invite_token`, etc.) so the
whole flow is testable without a real email/SMS provider wired up. Codes are always stored only as
a hash, never in plaintext, and every one of these echo fields disappears entirely outside
`ENVIRONMENT=development` (enforced per-call, not just by convention).

## Production deployment

The root `docker-compose.yml` is deployment-ready as-is — `web` builds a static production bundle
served by nginx (not the Vite dev server), and `api` runs uvicorn directly. To deploy (including
via **Coolify**, which can deploy directly from a Docker Compose file in this repo):

1. Set `ENVIRONMENT=production` and provide **real, unique** values for `JWT_SECRET`,
   `PROVIDER_SECRET_KEY`, `ADMIN_BOOTSTRAP_KEY`, and `WORKER_KEY` — the app deliberately **refuses
   to start** in production if `JWT_SECRET` or `PROVIDER_SECRET_KEY` are left at their placeholder
   values (both are printed in `app/config.py`, so leaving either one unset in a real deployment
   is a full auth bypass or a full break of every encrypted secret in the system).
2. Set `WEB_ORIGIN` to your real frontend domain (CORS) and `PUBLIC_API_BASE_URL` to your real API
   domain (used to build provider delivery-report webhook URLs).
3. Point `DATABASE_URL` at a real, durable PostgreSQL instance (Coolify can provision one, or use
   the `postgres` service in this compose file with a persisted volume, already configured).
4. Health checks: `GET /health/live` (process up) and `GET /health/ready` (DB reachable) — wire
   these into whatever health-check mechanism your platform uses.
5. If Coolify's own reverse proxy manages ingress/domains for you, you may need to remove or adjust
   the explicit `ports:` mappings in `docker-compose.yml` for `api`/`web` depending on how your
   Coolify instance is configured — check what it expects for Compose-based deployments.
6. Uploaded files (DLT certificates, generated invoice PDFs) are written to the `uploads_data`
   Docker volume, not committed to the repo or baked into the image — make sure your deployment
   target persists named volumes across redeploys, or point `UPLOADS_DIR` at real object storage
   (S3/Blob) if you'd rather not rely on local volume persistence.
7. Wallet recharge via Razorpay needs **live-mode** keys (`RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET`)
   from your own Razorpay account; without them, recharge falls back to a clearly-labelled
   dev-mode direct credit (fine for staging, not for real payments).
8. SMTP (for OTP/invoice/notification emails) and the platform's own SMS sending identity (for
   login OTPs) are configured from the admin UI (Platform Settings), not `.env` — nothing sends
   real email/SMS until those are filled in there.

RabbitMQ is provisioned in `docker-compose.yml` but not yet consumed by any code (message dispatch
is currently synchronous, inline). It's safe to remove that service if you don't plan to build an
async worker soon, or leave it if you do.

## SMS provider routing

Outbound SMS goes through a generic, configurable HTTPS/TTBS provider adapter
(`apps/api/app/providers.py`) rather than a direct SMPP connection. Provision a route (endpoint,
auth style, field mapping) via the admin Provider Routes page; until one exists for a given route
name, sends fall back to a safe simulated provider.

## External send API

`POST /v1/sms/send` and `/v1/sms/send-bulk`, authenticated via `X-Api-Key`, take `template_id` (the
real DLT-registered template ID) and `message` (the complete, already-composed text) — the caller's
own system renders variables into the template itself; Textzi verifies the template/DLT mapping is
approved for the calling entity and resolves routing. This is deliberately different from the
dashboard's own Compose flow (`alias` + `variables`, server-rendered), since an integrator's system
has already composed the exact text it wants sent.

## Wallet & billing

Prepaid wallet, debited per SMS segment at send time (GSM-7: 160 chars single-segment / 153 per
segment concatenated; Unicode content: 70 / 67 — UTF-16 code units, not Python codepoints, so
surrogate-pair emoji count correctly). Every credit/debit is recorded in an immutable
`wallet_transactions` ledger, and every charge (recharge, DLT fee, channel subscription, admin
credit) produces a GST invoice, synced to ERPNext when configured or rendered in-app otherwise.

- **Razorpay** — `POST /v1/wallet/recharge/razorpay/order` + `/verify`. The credited amount always
  comes from the server-side order record created at checkout start, never the client's
  post-payment report, and signatures are verified server-side via the Razorpay SDK.
- **Dev-mode direct credit** — instant, no gateway required, clearly labelled as such in every
  response it appears in; automatically disabled once Razorpay keys are configured.

## Security baseline

- Every admin-tier bootstrap secret (`ADMIN_BOOTSTRAP_KEY`, `WORKER_KEY`, `JWT_SECRET`,
  `PROVIDER_SECRET_KEY`) is checked against its known placeholder value outside development —
  the two most critical ones refuse to let the app start at all if left unset.
- Sensitive account actions (API key generation, IP allow-list changes, key revocation) require a
  fresh one-time code delivered to the account's verified mobile/email, independent of TOTP 2FA.
- Financial admin actions (rate cards, wallet credits, user role changes) require a recent 2FA
  step-up on top of admin-tier auth, for any admin account that has 2FA enabled.
- Message content and recipient numbers can be encrypted at rest per channel (Fernet, via
  `PROVIDER_SECRET_KEY`); masked in every report/admin view either way.
- TLS termination, a managed secrets store, private database networking, and dependency scanning
  are the deploying operator's responsibility — this repo doesn't provision any of that for you.

## Initial DLT provisioning (admin)

Use the `X-Admin-Key` header (`ADMIN_BOOTSTRAP_KEY`) only from a trusted, scripted admin context —
normal day-to-day admin work should go through a real admin login instead. Provision in order:
organisation → entity → PE ID → header → template → entity API key. Customers can also self-serve
all of this (DLT self-registration or an assisted-registration request) from their own dashboard.
