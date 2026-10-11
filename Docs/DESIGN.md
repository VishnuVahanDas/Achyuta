# Personal Accounts App — Detailed Design

Oct 12, 2026 · @Vipul

## Overview
AppName: Achyuta
A mobile-first personal ledger that answers one question at any moment: where is my money, and who owes whom. It replaces scattered memory, UPI app histories and bank statements with one record where every movement has a source and a destination.

**Problems it solves**

- Money lent and borrowed, with return dates, is forgotten or disputed.
- Cash, UPI apps and bank accounts get mixed up.
- Personal money mixes with Vinatay Skytech, HolyTrail, Vishnu Wings and Vyom money.
- Third-party payments (Father's account, on behalf of a friend, Vyom pass-through) blur who owes whom.
- Vishnu Wings deals span many sources, return in chunks and roll over.
- Bank balances do not match what was recorded.

**Design principles**

| Principle | What it means in practice |
| --- | --- |
| Every entry has a From and a To | Balances, dues and reconciliation follow automatically |
| Track bank accounts, not UPI apps | A UPI app is a tag; the money leaves a bank account |
| Borrowed money remembers its owner | Father's, a friend's or Vyom's money stays traceable through deals and rollovers until repaid |
| Transfers are not expenses | ATM, FD, lending, card bill, Vyom Fund and settlements never inflate spending |
| Quick by default, detailed when it matters | A 5-second entry for daily spends; items, splits and receipts for big ones |
| Imperfect but regular | Weekly balance checks and a Suspense bucket catch what was missed |
| Private per user | Each user has an independent, isolated workspace |

## Core concepts

Fourteen concepts cover every case discussed. Each is a building block in the data model.

| Concept | Meaning | Example |
| --- | --- | --- |
| Account | A place money sits or a party money is owed to/by | SBI, HDFC, Cash, HDFC Card, FD-SBI-01 |
| Account type | Bank, Cash, Card, Wallet, FD, Proxy, Person, Fund, Capital, Income, Expense | Father's SBI = Proxy |
| Payment app | How money moved; linked to a default bank | PhonePe → SBI, GPay → HDFC |
| Payment mode | UPI, NEFT, IMPS, RTGS, NetBanking, Cash, Card, Cheque | Internet banking transfer = NEFT |
| Book | Whose business an entry belongs to | Personal, Vinatay, HolyTrail, Vishnu Wings |
| Person | Anyone you owe or who owes you; can have several ledgers | Father, Friend, Brajesh (Personal), Brajesh (Vishnu Wings) |
| Proxy account | Someone else's account you use; balance not tracked | Father's SBI |
| On behalf of | A payment that settles someone else's obligation | Paid Person C for Friend |
| Fund | Money held for someone else | Vyom Fund with me |
| Deal | One investment round with Vishnu Wings | VW-01, VW-02 |
| Funding line | The owner of each rupee inside a deal | You ₹10,000, Father ₹10,000 |
| Rollover / Adjustment | A non-cash settlement agreed between parties | Keep ₹25,000 for VW-02, return ₹5,000 |
| Check balance | Actual balance entered to detect mismatches | SBI shows ₹42,310; app shows ₹43,010 |
| Suspense | Temporary bucket for unexplained differences | ₹700 parked until resolved |

**Payment app vs account:** the app never shows a "PhonePe balance". Choosing PhonePe auto-fills SBI as the debited account. If an app is linked to two banks, the entry asks which one and remembers the last choice.

## Data model

The model is double-entry underneath: every Transaction holds two or more Postings whose signed amounts sum to zero. The user never sees debits and credits; the entry screens generate the postings.

### Tables

| Table | Key fields | Notes |
| --- | --- | --- |
| Workspace | owner, name, currency (INR), start\_date | One per user; every other table carries workspace\_id |
| Account | name, type, book, opening\_balance, is\_active, track\_balance | track\_balance = false for Proxy accounts |
| PaymentApp | name, default\_account, other\_accounts | PhonePe, GPay, Paytm, BHIM |
| Book | name, kind (personal, company, investment) | Personal, Vinatay, HolyTrail, Vishnu Wings |
| Person | name, phone, notes | One person, many ledgers via Person accounts |
| Category | name, parent, kind (expense, income) | Two levels; user editable |
| Tag | name | Free labels: #bike, #kartik-yatra, #brother |
| Merchant | name, default\_category, default\_payment\_app | Blinkit, Swiggy, Indian Oil |
| Transaction | date, kind, description, merchant, payment\_app, mode, utr, book, on\_behalf\_of, status (draft, confirmed), created\_by | One user action = one transaction |
| Posting | transaction, account, amount (signed), category, person, deal, funding\_owner | Sum of amounts per transaction = 0 |
| LineItem | transaction, name, amount, category, qty | Blinkit apple ₹120, charger ₹499 |
| Attachment | transaction, file, kind (receipt, screenshot, 80G, agreement) | Stored privately on the VPS |
| Deal | code, counterparty\_group, book, opened\_on, expected\_profit, status | VW-01; status in the deal lifecycle section |
| FundingLine | deal, owner (self or person), amount\_in, amount\_returned | Carries ownership through rollovers |
| Agreement | date, parties, text, proof attachment, follow\_up\_date | Rollovers, adjustments, verbal deals |
| RecurringTemplate | name, schedule, amount, from\_account, to\_category, next\_due | EMI, rent, subscriptions, seva |
| FixedDeposit | account, principal, rate, start, maturity, interest\_payout | One row per FD account |
| Asset | name, purchase\_txn, price, warranty\_until | Laptop, phone, camera |
| BalanceCheck | account, date, actual\_balance, app\_balance, difference, resolved | Drives reconciliation |
| AuditLog | object, field, old, new, at | Every edit is recorded |

### How the special cases post

Paid ₹10,000 to Ramesh from Father's account:

| Account | Amount | Effect |
| --- | --- | --- |
| Ramesh (person) | +10,000 | Ramesh owes you |
| Father (person) | −10,000 | You owe Father |

The proxy account appears on the transaction for traceability but its balance is not tracked.

Paid ₹3,000 to Person C on behalf of Friend:

| Account | Amount | Effect |
| --- | --- | --- |
| Friend (person) | +3,000 | Your debt to Friend falls |
| SBI | −3,000 | Bank balance falls |

Vyom sends ₹50,000 for third-party payments:

| Account | Amount | Effect |
| --- | --- | --- |
| SBI | +50,000 | Money in your bank |
| Vyom Fund | −50,000 | Held for Vyom; not income |

Rollover of ₹25,000 from VW-01 to VW-02 (no bank movement):

| Account | Amount | Effect |
| --- | --- | --- |
| Vishnu Wings Capital (VW-02) | +25,000 | New deal capital |
| Vishnu Wings Capital (VW-01) | −25,000 | Old deal recovered |

Funding lines move with it, so Father's share stays visible.

## Key user flows

Every flow starts from one Add button with entry types: Spend, Receive, Transfer, Lend/Borrow, Settle, Deal, Check balance.

### 1. Quick spend (about 5 seconds)

1. Tap Add, type the amount.
2. Pick a merchant or category chip; payment app and account auto-fill from merchant memory.
3. Save. Missing details go to the To review inbox.

### 2. Detailed purchase (Blinkit example)

1. Merchant: Blinkit. App: PhonePe (auto: SBI). Total ₹619.
2. Add items: Apple ₹120 → Food › Fruits; Charger ₹499 → Assets › Accessories.
3. Attach the order screenshot; optional order ID.
4. Save. The bank sees one ₹619 debit; reports see two categories.

### 3. Lend and get back

1. Lend ₹5,000 to Ramesh from SBI, expected back by a date.
2. The reminder fires on that date; overdue items turn red.
3. Partial returns reduce the balance. A shareable statement goes to WhatsApp.

### 4. Pay from Father's account

1. Spend or Lend, From: Father's SBI (proxy).
2. The app records that the recipient owes you and that you owe Father, in one entry.
3. When the recipient repays, the app prompts: settle Father?

### 5. Pay on behalf of someone

1. Spend, From: SBI, To: Person C, On behalf of: Friend, Purpose: Vyom.
2. Your debt to Friend falls by the amount; Person C owes nothing.

### 6. Vyom Fund (pass-through)

1. Receive from Vyom → Vyom Fund with me (not income).
2. Pay a third party → choose "from Vyom Fund"; attach the bill.
3. Personal use of Vyom money → recorded as "I owe Vyom Fund" until put back.
4. The Vyom Fund screen shows received, paid out, used personally and should-have-now.

### 7. Shared expense (trip, seva, family)

1. Create a group (e.g. Vrindavan Yatra) with members.
2. Add expenses with who paid; split equally or custom.
3. The app shows the minimum settlements; settling posts to each person's ledger.

### 8. Recurring payments

1. Create a template: EMI, rent, Google One, Claude, monthly seva.
2. On the due date a draft entry appears; tap Paid to confirm or skip.

### 9. Vishnu Wings deal

1. New deal VW-01: add funding lines from several sources (SBI ₹5,000 via PhonePe, HDFC ₹5,000 to Brajesh via GPay, Father's account ₹10,000 via Paytm). Each line records channel: company account or Brajesh.
2. Returns arrive in chunks from either channel. Each chunk recovers capital first, then counts as profit.
3. When capital is fully back, the deal moves to Capital recovered, profit awaited. Later chunks auto-tag as profit.
4. Optional expected profit: less received shows profit still due; more received asks what the extra is.
5. As soon as recovered capital covers Father's line, the app prompts: pay Father.
6. You close the deal when Brajesh confirms nothing more is due.

### 10. Rollover to a new deal

1. Choose Rollover on VW-01: amount kept for VW-02 and cash still to return.
2. If Father's money is inside, the app asks: settle Father now (recommended), carry his line into VW-02, or pay him from the cash part.
3. An Agreement note stores the terms and a WhatsApp screenshot; a reminder tracks the pending cash return.

&#91;embedded content: Vishnu Wings deal lifecycle · 3 states, rollover branch\]

Returns move a deal from Active to Capital recovered; only your confirmation closes it. A rollover opens the next deal once every borrowed funding line (such as Father's) has a decision.

### 11. Brajesh: personal vs deal

1. Every Brajesh entry asks: Vishnu Wings deal or Personal (pre-selected when an active deal fits).
2. Adjustment entries move amounts between his two ledgers, with an agreement note.
3. His screen shows both ledgers and one net position.

### 12. Check balance and Suspense

1. Open an account, tap Check balance, type the balance from your bank app.
2. Zero difference: marked verified up to today.
3. A difference shows unconfirmed entries since the last check; fix them, or park the gap in Suspense.
4. Suspense items stay on the home screen until resolved.

### 13. Fixed deposit

1. Transfer SBI → new FD account with principal, rate and maturity date.
2. Reminder 7 days before maturity.
3. On maturity, FD → SBI; interest posts as income, TDS as a tax line.

## Screens and navigation

Five bottom tabs plus a floating Add button, designed for one-hand use on a phone and installable as a PWA.

| Tab | Purpose | Main contents |
| --- | --- | --- |
| Home | Clarity at a glance | Balance cards, owe/owed, due this week, suspense, to review count |
| Entries | Everything recorded | Day-grouped list, search, filters (account, person, book, category, tag, app, mode, merchant) |
| People | Who owes whom | Person list with net balance and age; Father, Friend, Brajesh with two ledgers |
| Deals & Funds | Money held by or for others | Vishnu Wings deals, Vyom Fund, company books, FDs |
| More | Setup and reports | Accounts, payment apps, categories, merchants, recurring, groups, reports, export, settings |

### Detail screens

| Screen | Shows | Actions |
| --- | --- | --- |
| Add entry | Amount, type switcher, From/To chips, app, mode, book, category, person, on behalf of, tags, note, date, attachments | Save, save and add another, split into items |
| Account | Balance, last verified date, entries | Check balance, transfer, edit |
| Person | Net balance, ledger(s), expected return dates, age | Lend, borrow, settle, share statement |
| Deal | Funding lines, chunks received, capital out, profit, status, agreements | Add return, rollover, mark profit only, close |
| Vyom Fund | Received, paid to third parties, used personally, should have now | Receive, pay out, put back, share statement |
| Group | Members, expenses, who paid, settlements | Add expense, settle up |
| Check balance | Actual vs app balance, unconfirmed entries since last check | Fix entry, park in Suspense |
| To review | Quick entries missing details | Complete, leave as is |
| Reports | Monthly, category, merchant, payment app, income source, donations, FDs | Filter, export PDF/Excel |

### Entry screen behaviour

- The 6 most used categories and merchants appear as chips.
- Choosing a merchant fills its usual app, account and category.
- Choosing a person reveals expected return date.
- Choosing a Vishnu Wings or Brajesh counterparty asks deal or personal.
- A proxy account in From reveals the owner and posts the debt automatically.
- Amount field supports simple maths (e.g. 450+120).

## Dashboard, reports and statements

The Home screen answers what is happening with my money in six cards; reports answer where it went.

### Home cards

| Card | Shows | Tap opens |
| --- | --- | --- |
| Where my money is | Spendable total; each bank, cash, card due | Account list |
| Others owe me | Total, top people, oldest due | People, filtered |
| I owe | Total incl. Father and Vyom Fund used personally | People, filtered |
| Due this week | Expected returns, EMIs, recurring, FD maturities | Calendar list |
| Held for others / invested | Vyom Fund balance, Vishnu Wings capital out, profit pending, FDs | Deals & Funds |
| This month | Income vs spending, top 5 categories | Monthly report |

A strip above the cards shows To review and Suspense counts when not zero.

### Reports

| Report | Answers |
| --- | --- |
| Monthly summary | Income, spending, savings, by category |
| Category and sub-category | Where spending goes over months |
| Merchant | Spend and items at Blinkit, Swiggy, Amazon |
| Payment app and mode | PhonePe vs GPay vs NEFT volume |
| Income by source | Salary vs profit; Vyom, Vinatay, Vishnu Wings, HolyTrail, freelance |
| Person spend | Gifts and family needs per person per year |
| Vishnu Wings performance | Capital out, profit, return % and duration per deal |
| Donations | Per organisation per year, with 80G receipts |
| FDs | Principal, rate, maturity, interest earned |
| Tag report | Full cost of one trip or one vehicle |

### Shareable statements

- Person statement: dated lines, running balance, net due (PDF or WhatsApp text).
- Brajesh statement: deals and personal, separate or combined, with UTRs.
- Vyom Fund statement: received, paid with bills, balance held.
- Year-end statement for the CA: income by source, donations, interest, company dues.

## Categories, income sources and tags

Two levels of categories plus free tags. This is the starting set; categories can be added, renamed, merged or hidden at any time.

### Expense categories

| Category | Sub-categories |
| --- | --- |
| Food | Grocery, Vegetables, Fruits, Milk and dairy, Eating out, Online order, Snacks and tea, Prasadam ingredients |
| Fuel and vehicle | Petrol, Diesel, Service and repair, Insurance, Parking and toll, Accessories |
| Travel | Train, Flight, Bus, Cab/Auto, Metro, Hotel/Stay, Travel food |
| Assets and electronics | Laptop, Phone, Camera, Drone parts (personal), Accessories, Repairs |
| Work related | Tools, Components, Courier, Printing, Software, Work travel |
| Health | Doctor, Medicines, Tests, Health insurance, Fitness |
| Online platforms | Claude, Google One, Apple/iCloud, YouTube Premium, Domain and hosting, VPS, Mobile recharge, Internet |
| Gifts | Friends, Family, Festivals, Weddings and functions |
| Family needs | Brother, Sister, Parents, Home contribution, Education |
| Home and living | Rent, Electricity, Water, Gas, Household items, Repairs, Furniture |
| Personal | Clothes, Footwear, Grooming, Books |
| Donations and seva | Temple, Nitya Seva, Annadan, Charity |
| Learning | Courses, Books, Certifications, Events |
| Finance charges | Bank charges, Card fees, Interest, Late fees |
| Uncategorised | Temporary; listed in To review |

### Income categories

| Category | Sub-categories (source) |
| --- | --- |
| Salary | Vyom Drones, Vinatay Skytech, Vishnu Wings, Other |
| Profit / share | Vinatay Skytech, Vishnu Wings, HolyTrail, Other |
| Freelance / clients | Website projects, Consulting, Other |
| Interest | FD, Savings |
| Gifts received | Family, Friends |
| Refunds / cashback | — |
| Other income | — |

### Never expenses or income (transfers)

ATM withdrawal, bank to FD, lending and repayment, credit card bill payment, Vyom Fund movements, deal capital and its recovery, rollovers, adjustments and on-behalf settlements.

### Tags

Tags add context across categories: vehicle (#bike, #car), trip (#kartik-yatra), person (#brother) or event. A tag report totals every entry carrying it.

## Users, security, privacy and backups

Each user gets an isolated workspace; financial data is protected at login, in transit, at rest and in backups.

| Area | Decision |
| --- | --- |
| Signup | Invite only; the superuser issues invite links |
| Isolation | Every query is scoped by workspace; no shared lists, people or categories between users |
| Login | Password plus a 4–6 digit app PIN for quick re-entry; optional TOTP two-factor |
| Sessions | Auto-lock after inactivity; device list with remote sign-out |
| Transport | HTTPS only (Certbot), HSTS, secure cookies |
| Attachments | Private media served only through authenticated views, never public URLs |
| Sensitive fields | Notes and account numbers encrypted at field level; only last four digits shown |
| Admin access | Superuser cannot browse other workspaces in the app; tell invited friends the server admin has database access |
| Audit | Every edit and delete logged; deletes are soft for 30 days |
| Backups | Daily encrypted pg\_dump plus media archive, 30-day retention, one off-server copy; monthly restore test |
| Export | User can export all data as Excel/CSV at any time |

## Tech stack and architecture

Same pattern as the sadhana report site: Django and PostgreSQL on the existing VPS, server-rendered pages with light interactivity, installable as a PWA.

| Layer | Choice | Why |
| --- | --- | --- |
| Backend | Django 5, PostgreSQL | Familiar stack; transactions and constraints keep postings balanced |
| Frontend | Django templates + HTMX + Alpine.js, Tailwind CSS | Fast mobile pages without a separate SPA build |
| PWA | Manifest, service worker, offline draft queue | Home-screen install; entries saved offline sync later |
| API (later) | Django REST Framework | For a future Flutter app (SMS reading needs native Android) |
| Jobs | Celery or django-q with Redis, or cron management commands | Recurring drafts, reminders, FD maturity, backups |
| Notifications | Web push; email fallback | Due dates, overdue returns, Father prompts |
| Files | Private media folder, served through auth views | Receipts, screenshots, 80G, agreements |
| Server | Nginx + gunicorn + systemd, Certbot | Matches the current VPS setup |
| Admin | Django admin (Jazzmin) | Fits the planned central database dashboard |

### Django apps

| App | Owns |
| --- | --- |
| core | Workspace, users, invites, PIN, settings |
| ledger | Account, PaymentApp, Book, Person, Transaction, Posting, LineItem, Attachment, AuditLog |
| catalog | Category, Tag, Merchant |
| deals | Deal, FundingLine, Agreement, Vyom Fund logic |
| planning | RecurringTemplate, groups and splits, FixedDeposit, Asset |
| reconcile | BalanceCheck, Suspense; later statement import |
| reports | Dashboard queries, reports, PDF/Excel export, statements |

### Integrity rules (enforced in the service layer)

- A transaction saves only if its postings sum to zero.
- Posting to a Proxy account never changes a tracked balance.
- Deal returns allocate to capital before profit, oldest deal first, unless overridden.
- A rollover cannot save while a borrowed funding line has no decision.
- Confirmed entries are edited, never silently replaced; every change is logged.

## Native apps (Android and iPhone)

The PWA serves both phones through Phases 1–3. A Flutter app comes in Phase 4, built by GitHub Actions for Android and iPhone from one repository, talking to the same Django backend through DRF.

### Why native later

| Gain | Android | iPhone |
| --- | --- | --- |
| Automatic bank SMS reading | Yes (with permission) | Not allowed by iOS |
| Biometric lock (fingerprint / Face ID) | Yes | Yes |
| Home-screen widgets (quick add, balances) | Yes | Yes |
| Offline-first with sync | Yes | Yes |
| Share-sheet: send a payment screenshot to the app | Yes | Yes |

### CI pipelines

| Step | Android | iPhone 16 Pro |
| --- | --- | --- |
| Runner | ubuntu-latest | macos-latest |
| Build | flutter build appbundle / apk | flutter build ipa |
| Signing | Upload keystore stored as base64 secret | Distribution certificate (.p12) + provisioning profile, via fastlane match or secrets |
| Account | None (Play Console optional, one-time fee) | Apple Developer Program, about $99 per year |
| Delivery | APK as release artifact, or Play internal testing | TestFlight upload with App Store Connect API key |
| Trigger | Every push to main | Tagged releases only (macOS minutes cost more) |

### Secrets

| Secret | Used by |
| --- | --- |
| ANDROID\_KEYSTORE\_BASE64, ANDROID\_KEYSTORE\_PASSWORD, ANDROID\_KEY\_ALIAS, ANDROID\_KEY\_PASSWORD | Android signing |
| IOS\_P12\_BASE64, IOS\_P12\_PASSWORD, IOS\_PROFILE\_BASE64 | iOS signing (if not using match) |
| MATCH\_GIT\_URL, MATCH\_PASSWORD | fastlane match (alternative) |
| ASC\_KEY\_ID, ASC\_ISSUER\_ID, ASC\_KEY\_P8\_BASE64 | TestFlight upload |
| API\_BASE\_URL | App backend address |

### Backend additions for the app

- DRF endpoints mirroring the entry services (never raw posting writes from the app).
- Token auth with refresh, device registration, remote sign-out.
- Sync endpoint: entries created offline carry a client UUID so retries never duplicate.
- Push via Firebase Cloud Messaging (Android) and APNs through FCM (iPhone).

## Build phases

Phase 1 alone fixes the daily confusion; later phases add planning and automation. Each phase ends with a gate before the next starts.

| Phase | Scope | Gate to move on |
| --- | --- | --- |
| 1. Core ledger | Workspace and login, accounts, payment apps, books, people, categories, merchants, quick and detailed entry, line items, attachments, proxy and on-behalf, Home dashboard, check balance, suspense, audit log, backups | Two weeks of daily use; all accounts verified once with zero difference |
| 2. Money with others | Vyom Fund, Vishnu Wings deals with funding lines, chunked returns, rollover and adjustments, Brajesh dual ledger, shareable statements | One real deal tracked from send to close |
| 3. Planning | Recurring templates, reminders and push, expected return dates, groups and splits, FDs, assets and warranties, budgets | Reminders fire correctly for a full month |
| 4. Automation | Statement import with per-bank mapping and matching, email alert parsing, screenshot reading for items, reports export for the CA, invites for friends, DRF API, Flutter apps for Android and iPhone built by GitHub Actions | Import matches 90% of a month's lines without manual edits |

Start date: choose a cut-off (e.g. 1 November 2026), enter opening balances per account and current dues per person, and skip old history.

## Open questions and decisions

### Decided

| Topic | Decision |
| --- | --- |
| Labels | English only |
| UPI apps | Tags linked to bank accounts, not accounts |
| Vyom extra money | Pass-through fund for third-party payments; never income |
| Father's money | Principal only, no profit share; tracked by funding line until repaid |
| Vishnu Wings | Both a book and an investment counterparty; deals cover company and Brajesh channels |
| Brajesh | Separate personal and deal ledgers with adjustments and a net view |
| Investments | FDs included |
| Donations | Included, with 80G receipts |
| Bank import | Deferred to Phase 4; check balance covers Phase 1 |
| Users | Independent invite-only workspaces |

### Open

- [ ] Subdomain and app name
- [ ] Start date and opening balances
- [ ] Exact list of bank accounts, cards and payment apps to seed
- [ ] Does a friend's Vyom money need its own fund, or is the friend ledger enough?
- [ ] Credit card statement cycle and due dates per card
- [ ] Should groups (shared expenses) be in Phase 1 instead of Phase 3?

## Claude Code prompts

Run these in order, one prompt per session, committing after each. Every prompt assumes this document is saved in the repo as docs/DESIGN.md (export this doc as Markdown).

### How to run

1. Create an empty Git repo, add docs/DESIGN.md, open Claude Code in the repo folder.
2. For prompts marked Plan first, press Shift+Tab to enter plan mode, review the plan, then approve.
3. After each prompt: run the tests, try the screen on your phone, commit with the prompt number in the message.
4. If something is wrong, say exactly what and where in the same session before moving on.

### Phase 1 — Core ledger

**P0 — Project memory (CLAUDE.md)**

```text
Read docs/DESIGN.md fully. Create CLAUDE.md at the repo root as the permanent project brief for future sessions. Include: product purpose in 3 lines; stack (Django 5, PostgreSQL, Django templates + HTMX + Alpine.js, Tailwind, PWA, gunicorn + Nginx + systemd on Ubuntu VPS); the Django apps and what each owns; the integrity rules from the design (postings sum to zero, proxy accounts never change tracked balances, deal returns capital-first oldest-first, rollover blocked while a borrowed funding line is undecided, all edits audited); coding rules (all money as Decimal with 2 places, never float; all queries scoped by workspace; business logic only in services.py, never in views or templates; every service function has pytest tests; mobile-first UI at 375px width); and commands to run tests, lint and the dev server. Do not write application code yet.
```

**P1 — Scaffold** (Plan first)

```text
Following CLAUDE.md, scaffold the Django project "paisa" (rename later if needed) with apps core, ledger, catalog, deals, planning, reconcile, reports. Set up: settings split into base/dev/prod with django-environ; PostgreSQL; custom User model in core; Tailwind via django-tailwind or standalone CLI; HTMX and Alpine.js loaded from static files; base template with mobile bottom navigation (Home, Entries, People, Deals & Funds, More) and a floating Add button; pytest-django, ruff, pre-commit; a Makefile with run, test, lint, migrate. Add a Workspace model (owner, name, currency default INR, start_date) and middleware that attaches request.workspace for the logged-in user. Login and logout pages only; signup is invite-only and comes later. Show me the tree and how to run it.
```

**P2 — Data model** (Plan first)

```text
Implement the Phase 1 models from docs/DESIGN.md section Data model: Account (types: bank, cash, card, wallet, fd, proxy, person, fund, capital, income, expense; book; opening_balance; track_balance; is_active), PaymentApp (default_account, other_accounts M2M), Book, Person, Category (two-level, kind expense/income), Tag, Merchant (default_category, default_payment_app, default_account), Transaction (date, kind, description, merchant, payment_app, mode choices UPI/NEFT/IMPS/RTGS/NetBanking/Cash/Card/Cheque, utr, book, on_behalf_of, status draft/confirmed, client_uuid unique), Posting (transaction, account, signed Decimal amount, category, person, funding_owner nullable), LineItem, Attachment (private storage), AuditLog. Every model has workspace FK and created/updated timestamps. Add a database-level check or deferred validation so a confirmed transaction's postings sum to zero. Register all in Django admin with workspace filtering. Write model tests. Do not build UI yet.
```

**P3 — Posting engine**

```text
Create ledger/services.py with one function per entry type, each atomic, each returning the saved Transaction: spend(), receive(), transfer(), lend(), borrow(), settle(), spend_with_items() for line items split across categories, pay_from_proxy() (recipient owes me, I owe the proxy owner, proxy balance untouched), pay_on_behalf() (reduces my debt to the named person; payee owes nothing). Payment app selection must auto-resolve the bank account from PaymentApp.default_account unless an account is passed. Add balance helpers: account_balance(account, as_of), person_net(person) split into owes_me and i_owe. Write pytest tests covering every worked example in the design: Father ₹10,000 to Ramesh, Friend/Person C ₹3,000, Blinkit ₹619 split into Fruits ₹120 and Accessories ₹499, ATM withdrawal not counted as expense. All tests must pass.
```

**P4 — Setup and opening balances**

```text
Build a first-run setup wizard (mobile screens, HTMX steps): 1) choose start date; 2) add bank accounts, cash, cards with opening balances; 3) add payment apps and link each to its default bank (PhonePe, GPay, Paytm, BHIM preset); 4) add books (Personal preset; Vinatay Skytech, HolyTrail, Vishnu Wings as suggestions); 5) add people with current dues (owes me / I owe) posted as opening entries; 6) add proxy accounts (e.g. Father's SBI) linked to their owner person. Seed the default expense and income categories exactly as listed in docs/DESIGN.md section Categories. Make setup re-entrant from More > Settings.
```

**P5 — Add entry screen** (Plan first)

```text
Build the Add entry screen as described in docs/DESIGN.md sections Screens and Key user flows 1–5. Type switcher: Spend, Receive, Transfer, Lend/Borrow, Settle. Amount field with simple maths (450+120). Chips for the 6 most used merchants and categories. Choosing a merchant fills payment app, account and category. Choosing a payment app fills the bank, and asks which bank only if the app has several. Optional fields behind "More details": book, person, on behalf of, tags, note, date, mode, UTR, attachments, line items with per-item category. Choosing a proxy account in From shows the owner and explains the two effects before saving. Save and Save and add another. Missing category saves as draft into To review. All saving goes through ledger/services.py only. Must be comfortable one-handed at 375px.
```

**P6 — Entries, search, To review**

```text
Build the Entries tab: day-grouped list with amount, merchant or description, account, app icon and category; infinite scroll with HTMX; search box over description, merchant, person, items and note; filters for account, person, book, category, tag, payment app, mode, merchant, date range and status. Tapping an entry opens detail with all postings shown in plain words (e.g. "SBI −₹619 · Fruits ₹120 · Accessories ₹499"), attachments, audit history, edit and delete (soft delete, 30 days). Build the To review inbox listing drafts with one-tap completion.
```

**P7 — People and statements**

```text
Build the People tab and Person detail per docs/DESIGN.md. List: name, net balance (owes me green / I owe red), oldest due age. Detail: running ledger, expected return dates with overdue badges, partial settlements, actions Lend, Borrow, Settle. Support multiple ledgers per person (needed later for Brajesh). Share statement: generate a clean PDF and a WhatsApp-ready text summary with dated lines and net due. When a repayment arrives for money originally paid from a proxy account, prompt "Settle with <owner>?".
```

**P8 — Home dashboard**

```text
Build the Home tab with the six cards in docs/DESIGN.md section Dashboard: Where my money is, Others owe me, I owe, Due this week, Held for others / invested (placeholder until Phase 2), This month. Add the strip showing To review and Suspense counts when not zero. All numbers come from service-layer query functions in reports/services.py with tests. Each card links to its filtered view. Page must load in under 300 ms with 5,000 entries; add indexes as needed.
```

**P9 — Check balance and Suspense**

```text
Implement reconcile app per docs/DESIGN.md flow 12. On an account page, Check balance: user types the actual balance; show app balance, difference, last verified date, and entries since the last check marked unconfirmed. Options: tick entries as confirmed, edit an entry, add a missing entry inline, or park the difference in a Suspense account with a note. Suspense items show on Home until resolved by reassigning them to a real category or person. Store every BalanceCheck. Tests for zero difference, positive and negative gaps.
```

**P10 — Security and backups**

```text
Harden the app per docs/DESIGN.md section Users, security. Invite-only signup with expiring invite links created by the superuser; each new user gets a fresh isolated workspace with seeded categories. App PIN (4–6 digits) for quick unlock after inactivity timeout; optional TOTP two-factor (django-otp). Field-level encryption for notes and account numbers (show last four only). Private media served only via authenticated views. Audit log for every create, edit and delete. Write a backup script: nightly encrypted pg_dump plus media tarball, 30-day rotation, rsync to an off-server target, and a documented restore test. Add a test proving one workspace can never read another's data through any view.
```

**P11 — PWA and deployment**

```text
Make the app an installable PWA: manifest with icons, theme colour, standalone display; service worker caching the shell; offline Add entry that queues to IndexedDB and syncs using client_uuid so retries never duplicate. Add web push for reminders (VAPID). Then write deployment files for my Ubuntu VPS: gunicorn systemd service, Nginx server block for <subdomain> with Certbot TLS, static and media locations, a deploy.sh (git pull, migrate, collectstatic, restart). Do not touch other sites' Nginx configs. Give me the exact commands to run on the server.
```

### Phase 2 — Money with others

**P12 — Vyom Fund**

```text
Implement Fund accounts per docs/DESIGN.md flow 6. Receive into a fund (not income), pay a third party from a fund with mandatory bill attachment option, record personal use of fund money as a debt to the fund, and put back. Fund screen: received, paid out (list with bills), used personally, should-have-now. Shareable fund statement PDF. Show the fund on the Home Held for others card. Tests with the ₹50,000 / ₹38,000 / ₹5,000 example.
```

**P13 — Vishnu Wings deals** (Plan first)

```text
Implement the deals app per docs/DESIGN.md flows 9 and the lifecycle diagram. Deal (code auto VW-01, counterparty group with channels: company account and Brajesh personal, book, expected_profit optional, status Active / Capital recovered / Closed). Create deal with multiple FundingLines from different accounts, apps and proxy accounts; a proxy funding line records that I owe its owner. Add return: chunk from either channel into any account; allocate capital first, then profit (income Profit > Vishnu Wings), oldest active deal first, with manual override and a "profit only" flag. Auto-move to Capital recovered when capital is back; later chunks become profit; user closes manually. Expected profit comparison: less = still due, more = ask (extra profit / advance for next deal / to return / personal). Prompt to settle a proxy owner once recovered capital covers their line. Tests replaying both worked examples in the design (₹23,000 and ₹26,000 returns).
```

**P14 — Rollover, adjustments, Brajesh**

```text
Add Rollover and Adjustment entries per docs/DESIGN.md flows 10 and 11. Rollover: move an amount from one deal to a new or existing deal with no bank posting, record cash still to return as a pending receivable, and save an Agreement (date, text, proof screenshot, follow-up date). Block saving while any borrowed funding line is undecided; offer settle now, carry into the new deal (funding line moves with its owner), or pay from the cash part. Brajesh: two ledgers (Vishnu Wings deals, Personal); every Brajesh entry asks which, pre-selecting an active deal that fits; Adjustment entries move amounts between ledgers with an agreement note; show a combined net. Tests for the ₹30,000 / ₹25,000 / ₹5,000 rollover with Father's ₹10,000 inside.
```

### Phase 3 — Planning

**P15 — Recurring and reminders**

```text
Implement RecurringTemplate (monthly, weekly, yearly, custom day) for EMI, rent, subscriptions and seva. A scheduled job creates draft entries on due dates and sends web push. Reminders also for expected return dates, overdue loans, FD maturity 7 days ahead and pending rollover cash. Use django-q (or cron management commands) and document the systemd timer.
```

**P16 — Groups and splits**

```text
Implement shared-expense groups per docs/DESIGN.md flow 7: members (people plus me), expenses with payer, equal or custom split, running balances, and a minimum-settlement suggestion. Settling posts to each person's ledger through services.py. Tests for a 4-person trip.
```

**P17 — FDs, assets, budgets**

```text
Implement FixedDeposit (principal, rate, start, maturity, payout type) created by transfer from a bank; maturity posts principal back plus interest income and optional TDS line. Asset register linked to purchase entries with warranty expiry reminders. Optional monthly budgets per category with alerts at 80% and 100%.
```

**P18 — Reports and export**

```text
Build the reports listed in docs/DESIGN.md section Reports with charts (Chart.js) and filters, plus PDF and Excel export. Add a year-end CA pack: income by source and type (salary vs profit), interest, donations with 80G receipts zipped, company books dues.
```

### Phase 4 — Automation and native apps

**P19 — Statement import** (Plan first)

```text
Implement CSV/Excel bank statement import with per-bank ImportProfile (column mapping, date format, debit/credit columns, skip rows), saved after first mapping. Imported lines match existing entries by amount, date window ±2 days and UTR; unmatched lines become drafts in To review. Show a match report before committing. Tests with sample SBI and HDFC formats.
```

**P20 — API for the app**

```text
Add a DRF API under /api/v1 exposing the entry service functions (not raw postings), lists, dashboard, people, deals and sync. Token auth with refresh (simplejwt), device registration, remote sign-out, client_uuid idempotency, OpenAPI schema via drf-spectacular. Tests for auth, workspace isolation and idempotent sync.
```

**P21 — Flutter app** (Plan first; new repo or /mobile folder)

```text
Create a Flutter app consuming /api/v1: login with biometric unlock, quick add with merchant and app chips, entries list, people, home cards, offline queue with sync. Android only: optional bank SMS reading with explicit permission, parsing amount, account and UTR into draft entries. Share-sheet target to attach a payment screenshot to a new draft. Riverpod for state, dio for HTTP, drift for local storage.
```

**P22 — CI: Android and iPhone**

```text
Write GitHub Actions workflows for the Flutter app. android.yml on ubuntu-latest for pushes to main: decode keystore from secrets, flutter build apk and appbundle, upload as release artifacts. ios.yml on macos-latest for tags v*: install certificate and provisioning profile from secrets into a temporary keychain (or fastlane match), flutter build ipa with ExportOptions.plist, upload to TestFlight using the App Store Connect API key. Use the secret names listed in docs/DESIGN.md section Native apps. Add a README section listing each secret and how to create it.
```
