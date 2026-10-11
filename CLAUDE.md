# Achyuta — project brief

The full design is in `Docs/DESIGN.md`. Read the relevant section before building any feature; this file is the summary and the rules.

## Purpose

- A mobile-first personal ledger that answers one question at any moment: where is my money, and who owes whom.
- Every money movement has a From and a To (double-entry underneath, never shown to the user), so balances, dues and reconciliation follow automatically.
- Personal money, company books, borrowed money (Father, friends), the Vyom pass-through fund and Vishnu Wings deals stay separate and traceable, in a private workspace per user.

## Stack

| Layer | Choice |
| --- | --- |
| Backend | Django 5, PostgreSQL |
| Frontend | Django templates + HTMX + Alpine.js, Tailwind CSS (no SPA build) |
| PWA | Manifest, service worker, offline draft queue synced by `client_uuid` |
| Jobs | django-q or cron management commands (recurring drafts, reminders, backups) |
| Files | Private media folder, served only through authenticated views |
| Server | gunicorn + Nginx + systemd on an Ubuntu VPS, Certbot TLS |
| Admin | Django admin (Jazzmin) |
| Tooling | pytest-django, ruff, pre-commit, Makefile |
| Later (Phase 4) | Django REST Framework API, Flutter apps |

## Django apps

| App | Owns |
| --- | --- |
| `core` | Workspace, users, invites, PIN, settings |
| `ledger` | Account, PaymentApp, Book, Person, Transaction, Posting, LineItem, Attachment, AuditLog |
| `catalog` | Category, Tag, Merchant |
| `deals` | Deal, FundingLine, Agreement, Vyom Fund logic |
| `planning` | RecurringTemplate, groups and splits, FixedDeposit, Asset |
| `reconcile` | BalanceCheck, Suspense; later statement import |
| `reports` | Dashboard queries, reports, PDF/Excel export, statements |

## Integrity rules

Enforced in the service layer. Never weaken or bypass these; each one needs a test.

1. **Postings sum to zero.** A transaction saves only if its signed posting amounts sum to exactly zero.
2. **Proxy accounts never change tracked balances.** A proxy account (e.g. Father's SBI, `track_balance = False`) appears on the transaction for traceability only; the postings go to the person ledgers (recipient owes me, I owe the owner).
3. **Deal returns are capital-first, oldest-first.** Each returned chunk recovers capital before counting as profit, allocated to the oldest active deal first, unless the user overrides.
4. **Rollover is blocked while a borrowed funding line is undecided.** Every borrowed line (e.g. Father's) needs a decision — settle now, carry into the new deal, or pay from the cash part — before the rollover can save.
5. **All edits are audited.** Confirmed entries are edited, never silently replaced; every create, edit and delete is written to AuditLog. Deletes are soft for 30 days.

Related domain rules that are easy to get wrong:

- Transfers are never income or expense: ATM withdrawal, bank to FD, lending and repayment, card bill payment, Vyom Fund movements, deal capital and its recovery, rollovers, adjustments, on-behalf settlements.
- A UPI app is a tag linked to a bank account, not an account. There is no "PhonePe balance".
- Borrowed money keeps its owner through deals and rollovers (FundingLine) until repaid.

## Coding rules

- **Money is `Decimal` with 2 places, never `float`.** Use `DecimalField(max_digits=…, decimal_places=2)` in models and `Decimal("…")` built from strings in code and tests. No float arithmetic anywhere on amounts, including templates and JavaScript.
- **Every query is scoped by workspace.** Every model carries a workspace FK; every queryset filters on `request.workspace` (or a workspace argument in services). No shared lists, people or categories between users. Unscoped `Model.objects.all()` on workspace data is a bug.
- **Business logic lives only in `services.py`.** Views parse input, call a service and render; templates only display. No posting creation, balance maths or allocation logic in views, templates, forms, signals or admin. Future API endpoints call the same services, never raw posting writes.
- **Every service function has pytest tests**, including the worked examples in the design (Father ₹10,000 to Ramesh, Friend/Person C ₹3,000, Blinkit ₹619 split, the deal and rollover examples). Service functions that write are atomic.
- **Mobile-first UI at 375px width.** Design and check every screen at 375px first, comfortable one-handed; five bottom tabs (Home, Entries, People, Deals & Funds, More) plus a floating Add button. Wider layouts are an enhancement.
- Labels are English only. Currency is INR.

## Commands

The Django project package is `paisa`; apps sit at the repo root. Everything runs from the virtualenv in `.venv` through the Makefile. Config comes from `.env` (see `.env.example`).

| Task | Command | Runs |
| --- | --- | --- |
| First-time setup | `make setup` | venv, `pip install -r requirements-dev.txt`, `pre-commit install`, Tailwind CLI into `bin/` |
| Tests | `make test` | `pytest` (settings `paisa.settings.dev`, creates `test_paisa`) |
| One test | `.venv/bin/pytest core/tests/test_services.py -k name` | |
| Lint | `make lint` | `ruff check .` and `ruff format --check .` |
| Auto-fix lint | `make format` | `ruff check --fix .` and `ruff format .` |
| Dev server | `make run` | builds CSS, then `manage.py runserver` (`ADDR=0.0.0.0:8000` to override) |
| CSS | `make css` / `make css-watch` | Tailwind standalone CLI: `static_src/app.css` → `static/css/app.css` (not committed) |
| Migrations | `make migrations` / `make migrate` | `makemigrations` / `migrate` |

Run tests and lint before every commit. Rebuild CSS (`make css`) after adding Tailwind classes to templates.

## Conventions already in place

- Settings: `paisa/settings/{base,dev,prod}.py`. `manage.py` and pytest use `dev`; `wsgi.py` uses `prod`.
- `LoginRequiredMiddleware` is on: every view needs a login unless marked `login_not_required`.
- `core.middleware.WorkspaceMiddleware` sets `request.workspace` (the user's workspace, created on first use; `None` when anonymous).
- `ATOMIC_REQUESTS` is on.
- New models inherit `core.models.WorkspaceModel` (workspace FK, timestamps, and a `clean()` that rejects links into another workspace).
- Amounts use `core.fields.MoneyField` (Decimal, 14 digits, 2 places).
- Posting sign: positive means the account goes up (money into a bank, a person owes you more, an expense); negative is the reverse (money out, you owe a person, income, money held for a fund).
- A Postgres deferred constraint trigger (`ledger/migrations/0002_postings_balanced.py`) refuses to commit a confirmed transaction unless it has two or more postings summing to zero. Drafts are exempt. In tests, call `connection.check_constraints()` to run it before the test ends.
- A proxy account gets no postings: the transaction records it in `Transaction.proxy_account` and the postings go to the person ledgers.
- FKs between workspace rows use `on_delete=RESTRICT` (not `PROTECT`), so rows in use cannot be deleted but deleting a whole workspace still cascades.
- Entries are created only through `ledger/services.py` (`spend`, `spend_with_items`, `receive`, `transfer`, `lend`, `borrow`, `settle`, `pay_from_proxy`, `pay_on_behalf`). Each takes the workspace first, is atomic, checks every object belongs to that workspace, writes an AuditLog row and returns the Transaction. Add new entry types the same way, through `_post()`.
- Service amounts must be `Decimal`, `int` or `str`; a float raises `TypeError`. Errors the user can fix raise `django.core.exceptions.ValidationError`.
- A spend or receive without a category is saved as a draft (To review). Balances (`account_balance`, `person_net`) include drafts unless `include_drafts=False`.
- Each workspace has one `Expenses` and one `Income` account, created on first use; the category sits on the posting.
- Admin classes for workspace models inherit `core.admin.WorkspaceScopedAdmin` / `WorkspaceScopedInline`.
- Templates extend `templates/base.html`; tab pages pass `active_tab` (`home`, `entries`, `people`, `deals`, `more`) to highlight the bottom nav.
- HTMX and Alpine.js are vendored in `static/vendor/`; no CDN links.

## Working method

- Build in the phase order of `Docs/DESIGN.md` (section "Build phases"), one prompt per session, committing after each with the prompt number in the message.
- Do not build ahead of the current phase.
