# DTR

Shop maintenance and parts inventory for trucking fleets. No telematics.
Working name; read `CLAUDE.md` for the full brief and the decisions made.

## What works today

- Apex console: set up a customer company and its first admin.
- Sign-in with roles: mechanic, shop manager, fleet manager, company admin,
  Apex operator. One company never sees another's records.
- Trucks and trailers as separate units: add, edit, mark as left the fleet
  (kept, never deleted), search.
- Fleet list import from a CSV file, checked row by row, all or nothing.
- Change log per company, tamper-evident, viewable by the company admin.

- Work orders: complaint/cause/correction, techs, labor, parts, outside
  work, photos, notes, typed-name sign-off, close, cancel, amendments.
- English, Spanish, Hindi and Urdu (right-to-left).
- A clickable preview with sample data: `python tools/build_preview.py`.

## Coming next (see CLAUDE.md section 11)

DVIR defect to repair certification → parts inventory → PM →
per-unit compliance file with PDF → reports.

## Running it

Railway settings (Variables tab) the app needs:

| Setting | What it is |
|---|---|
| `MONGO_URL` | The MongoDB connection string |
| `JWT_SECRET` | A long random secret, 32+ characters |
| `OPERATOR_EMAIL` / `OPERATOR_PASSWORD` | The first Apex sign-in. Used only while no Apex account exists yet |
| `OPERATOR_NAME` | Optional, shown in the change log |

Railway starts it with the line in `Procfile`.

## Tests

    pip install -r requirements-dev.txt && python -m pytest -q

## Layout

    dtr/main.py           wires the pieces together
    dtr/access.py         roles, permissions and the company wall
    dtr/db.py             the only way company data is read or written
    dtr/auth.py           sign-in tokens
    dtr/changelog.py      the sealed change log
    dtr/passwords.py      password fingerprints
    dtr/i18n.py           the four languages
    dtr/regulatory.py     every regulation the code relies on, with citation
    dtr/accounts.py       sign-in, people, Apex console
    dtr/assets/           trucks, trailers, CSV import
    dtr/workorders/       work orders
    dtr/static/locales/   every word on screen, per language
    dtr/static/           the screens (HTML, CSS, JavaScript)
    tests/                the test suite
