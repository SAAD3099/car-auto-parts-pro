# AutoParts Pro — Desktop architecture

## Runtime

`AutoParts Pro.vbs` selects a supported windowed Python interpreter and starts `bootstrap.py` without a console. The graphical first-run installer creates `.desktop-runtime`, installs pinned PySide6 6.10.2 and creates a desktop `.lnk` shortcut targeting the private `pythonw.exe`. Normal future launches use that shortcut directly. `OPEN_AUTOPARTS.pyw` is an alternative first-run launcher.

`desktop.py` owns the Qt application window, icon, native menus, print dialog, save dialogs and lifecycle. A QWebEngineView renders the local interface; there is no Chrome tab or address bar. A loopback ThreadingHTTPServer runs in a daemon thread inside the same process. Closing the desktop window shuts down that service. SQLite records remain in the installation's `data` folder.

The desktop profile persists local theme/cart preferences but not authentication cookies across restarts. Activation uses QLocalServer/QLocalSocket to raise an existing window, with the workspace lock as a fallback when an activation channel cannot be established. The Linux test container lacked Unix-socket support, so that fallback was exercised; Windows activation still needs a target-machine check.

## Desktop files

| File | Responsibility |
|---|---|
| `desktop.py` | Qt window, private local service, native printing/downloads and single-instance activation |
| `bootstrap.py` | Tk first-run progress, hidden dependency installation and desktop runtime launch |
| `AutoParts Pro.vbs` | Hidden, version-probed Windows first-run launcher |
| `OPEN_AUTOPARTS.pyw` | Windowed Python alternative when Windows Script Host is unavailable |
| `CREATE_DESKTOP_ICON.vbs` / `create_shortcut.ps1` | Recreate icon after setup or folder relocation |
| `assets/autoparts.ico` / `.svg` | Original application/taskbar/branding icon |
| `static/style.css` / `app.js` | Carbon Black / Ivory Garage themes and automotive workflows |
| `core.py` / `server.py` | Transaction engine, HTTP routes, role checks, reports and assistant |
| `app_lock.py` / `maintenance.py` | Process lock, integrity checking, backups, restore and password recovery |

The optional `server.py` command remains a developer/debug entry point. It is not the normal desktop launcher. No precompiled signed Windows EXE is included; dependencies are installed graphically on first run.

## Data model

- Products use unique text barcodes. Names/category/unit/prices/costs are stored with current stock and threshold.
- Sales have a header and item snapshots; mutable outstanding balance is reduced by payments and qualifying returns.
- Purchases have header/item unit-cost records; cumulative paid amount is increased by supplier payments.
- Returns reference a sale and original sale lines. A line cannot return more than its sold quantity. Both refund value and refunded tax are cumulatively allocated to avoid penny drift.
- Payments reference exactly one sale or purchase.
- Movements describe stock changes. Audit rows identify application actor/action/detail.
- Store identity is snapshotted onto receipts. Historical receipts survive later name or price edits.
- The audit table is an application audit trail, not cryptographically tamper-proof. A Windows user with database access can edit files outside the app.

## Transaction boundaries

`BEGIN IMMEDIATE` acquires a SQLite write lock before reading inventory or balances. Validation, header/items, inventory change, stock movement and audit insertion commit together. Failure rolls back all writes. Unique request IDs implement retries for sales, purchases, returns and payments.

Weighted average cost is rounded to paisa per selling unit. Gross profit is therefore an operational estimate rather than an accounting valuation method suitable for every business.

## Local security

- Server binds only loopback and validates Host and Origin.
- Mutating routes require JSON and a custom header; no CORS relaxation.
- Passwords are salted PBKDF2-HMAC-SHA256 hashes, 260,000 iterations.
- Session tokens use cryptographic randomness, HttpOnly/SameSite=Strict cookies and an 8-hour expiry.
- Login failure throttling is in-process and resets on restart.
- Role checks occur on the backend; cashier product/sale responses redact purchase costs.
- Browser strings are escaped before HTML insertion. Scripts/styles are same-origin under CSP.
- CSV exports neutralize leading spreadsheet formula markers in text fields.
- The workspace file lock blocks simultaneous app/restore/recovery processes using the same folder.
- Data is not encrypted and loopback HTTP is not HTTPS. Do not expose this server externally.

## Assistant

Offline Insights is a read-only rules engine matching common store questions. It calls the same reporting code used by the dashboard. Cloud AI optionally makes an HTTPS POST to OpenAI Responses with a user-configured model/key. Only the question and aggregate totals are supplied. The model has no execution tools. Responses are rendered as escaped text. A privacy checkbox precedes cloud requests. Network failure leaves all offline workflows available.

## Capacity boundaries

20,000 products in a local workspace; 10,000 rows per import; up to 500 lines per sale/purchase/return. Catalog filtering is client-side. Product tiles show up to 150 matches, product table up to 500 matches, sales/purchase lists the latest 200 matches, stock movements the latest 300 and audit the latest 200. Original records remain in SQLite; sales/catalog CSV exports include all applicable records.

For a large catalog, introduce server-side pagination and indexed search before increasing the limit. Multiple browser tabs on one computer can make requests, but carts are convenience state per user in localStorage, not a coordinated multi-counter system.

## Operating constraints

Use a local disk for the active SQLite database. Copy backups to other media after creation. Do not sync active database/WAL files through OneDrive. Do not share the database across network filesystems. Upgrades require versioned migrations and recovery testing; this delivery includes schema version 3.

## Automotive extension

Product metadata is validated and saved in the same transaction as prices/opening stock. Fitment is a bounded JSON list with make/model/year ranges/engine. Vehicle Finder returns no purchase cost. Original sale lines snapshot part metadata and warranty. Warranty claims reference original sale items, validate expiration and available quantity, and have audited state transitions; they are service records, not financial transactions. An open claim reserves quantity until resolved.

Customer profiles join by customer ID, show current unpaid balance, lifetime net purchases, the latest 200 bills and later payments. Edits preserve the linked ID. Sales can link a structured vehicle and one completed workshop visit. Linking an existing matching receipt snapshots the visit vehicle reference.

Recovery secrets are 128 random bits, displayed once, salted PBKDF2 hashed in users. Reset rotates the code and invalidates all sessions for that user. Username lookup requires the secret and creates no session. Public recovery is capped at 5 attempts in 5 minutes; staff count is capped at 50. Staff resets require admin. Auth HTML is cleared after login to avoid duplicate field IDs.

## Workshop extension (version 4 / schema 3)

`workshop.py` owns structured vehicles and completed/void service visits. Latest visit and latest oil change are computed separately by visit time. Date and recorded-mileage thresholds drive reminders; no messaging is sent. Visit writes are idempotent and audited; stock and finance change only through the existing parts-sale transaction. Sale-to-visit linking validates customer/car ownership atomically. Visit lists return the latest 300 entries.

Version-2 startup snapshots the database before migration. Legacy customer car text is preserved without inferred make/model. `backup_import.py` validates and migrates a staged copy under a workspace lock, refuses populated destinations, and atomically installs only a successful copy. `IMPORT_OLD_BACKUP.vbs` opens the graphical importer. Original backups remain unchanged. Schema-3 backups cannot be restored into the older application.
