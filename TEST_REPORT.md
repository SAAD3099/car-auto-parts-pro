# AutoParts Pro 4 validation

92 automated tests passed, including existing transaction/security/recovery coverage and new workshop history, multiple vehicles, date/mileage reminders, backdated chronology, cancellation, idempotence, sale linking, ownership checks, stock/returns aggregates and cashier cost privacy.

Upgrade coverage includes reconstructed version-2 migration with existing credentials/car text, restart without duplicate cars, staged old-backup import into an empty destination, and refusal to overwrite an existing shop.

A real Qt WebEngine desktop session completed customer/car creation, oil visit, linked barcode parts sale, later non-oil visit retaining oil history, mileage-due reminder, product cost/stock/sold display, native backup/recovery downloads and password reset/re-login. Eleven screenshots are included in previews. Two native print requests were observed for a parts receipt and service card; print dialogs were canceled without physical output. Python compilation and JavaScript syntax checks passed.

Physical Windows installation/shortcut behavior, real barcode hardware, printers and the Tk import dialog still need target-machine verification. Import logic is automated-tested. Cloud AI uses mocked coverage; no live paid API key was used. This is a source desktop package, not a signed standalone Windows executable.
