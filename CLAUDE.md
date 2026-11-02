# Project Brief: Shop Maintenance System (telematics-free InMotion)

> Working name: **DTR** (owner's choice, Nov 2, 2026; may change). Do not invent another.
> Written Nov 2, 2026 from the owner's chat with Claude. Read this whole file before doing anything.


## 0. Decisions already made (read first)

- **Nov 2, 2026 — Separate product (option B).** DTR is its own repo and its own
  app, completely separate from InMotion. Owner's words: "maintenance software
  with inventory", "nothing to do with telematics".
- **What carried over from InMotion:** the same building blocks (FastAPI, Motor
  /MongoDB, Pydantic, Railway) and the *rules* InMotion proved out: deny-by-default
  company isolation, password hashing, the hash-chained change log, no
  impersonation, nothing pre-filled. The InMotion `main.py` (UI embedded as a
  string) was deliberately NOT copied; DTR keeps code in small files and the UI
  in real HTML/JS files.
- **Portals:** mechanic, shop manager, fleet manager, plus inventory. Company
  admin and the Apex platform operator as in section 5.8.
- Section 4 (Step Zero) is done. Section 10 item 1 is answered (B).

---

## 1. What this project is (plain summary)

A maintenance and shop-management system for a trucking fleet that **already has telematics (Samsara)** but has **no work order system**. It covers the mechanic side of the house only:

- DVIR defects → repair → mechanic sign-off
- Work orders
- Preventive maintenance (PM) scheduling
- Parts inventory
- An audit-ready maintenance file for every truck and trailer

**No telematics.** No GPS, no ELD, no hours of service, no hardware, no J1939. The fleet keeps Samsara for that.

The goal is to get a foot in the door with a real customer, using as much of the existing InMotion code (`inmotion-v2`) as possible.

---

## 2. Who you are working with

**Owner:** Alfonso Pacheco, Pacheco Industries Limited (parent holding company; owns the software). Apex Fleet Solutions (Pomona, CA) is the operating company; InMotion is a DBA of Apex. ~20 years hands-on heavy-duty truck maintenance. He is the sole decision-maker.

**He is not a developer and has no coding experience.** That shapes how you work:

- **Do the work yourself.** Make code changes directly. Only ask him to act when you genuinely can't (his accounts, approvals on his device), and say why.
- **Explain in plain terms.** Mechanic language is fine; programmer jargon is not. If you must use a technical term, explain it in one sentence.
- **Commands:** when he must run something, give ONE copy-paste line in a code block and say what it does. Combine steps with `&&`. For GitHub/Railway, give exact button names and what he should see next.
- **No guessing. Ever.** Verify the real state (run it, read the logs, list the directory) before saying anything is true. If you can't verify something, say exactly that and why, then go find out. "I think it works" is not acceptable; "I ran the tests, 657/657 pass" is.
- **When troubleshooting**, first check whether the code actually arrived/deployed before assuming the code is wrong.
- **Regulations:** official sources only (eCFR, FMCSA.gov, CA DMV/CHP, official state code). If no official source is found, say so and label any source used as unofficial.
- He works long shifts and sometimes goes out on wildland fire deployments with little computer time. Keep status updates short and easy to pick back up.
- Suggest switching to the Fable 5 model when a task genuinely warrants it (large refactors, codebase-wide audits).

---

## 3. The customer and the market reality

**Pilot fleet:** about 40–50 trucks, runs Samsara, no work order or maintenance-tracking system. (Company name intentionally not in this file.)

**Important finding (verified Nov 2026):** Samsara itself sells maintenance features: DVIRs, work orders, work orders created from DVIR defects, PM scheduling, parts inventory, and purchase orders. MaintainX, UpKeep, Cetaris, Trimble TMT and others also integrate with Samsara to turn DVIR defects into work orders.

So **software alone is not the edge.** The edge is Apex (a real mechanic) setting up and running the maintenance program, with this system as the tool that comes with the service. Build for the shop floor: fast for techs on a phone, built around how a truck shop actually works.

Not yet known: whether the pilot fleet's Samsara plan already includes Samsara's Maintenance features.

---

## 4. STEP ZERO: before writing any code

Do this first and report back to Alfonso in plain language. **Do not start building until he approves a direction.**

1. **Audit `inmotion-v2`.** The last known state (Sept 2026): FastAPI + Motor (async MongoDB) + Pydantic backend, 657-test suite passing, multi-tenant with a `TENANT_SCOPED_COLLECTIONS` list (which includes `dvir_reports`), a regulatory register in `regulatory.py`, deployed on Railway via GitHub. Note: `main.py` was ~367 KB with the whole UI embedded as a string. **This is from memory notes and may be out of date. Verify everything against the actual repo.**
2. **Make an inventory** of what already exists and what's reusable for this project:
   - auth, users, roles, tenant isolation, platform-operator/super-admin console
   - asset model (tractor and trailer as separate assets)
   - DVIR models/routes
   - any work order, PM, parts, or vendor code
   - audit log, demo/live environment separation, go-live gate
   - test suite status (run it and report the real numbers)
3. **List everything telematics-related** that would be switched off or removed (ELD, HOS, GPS, J1939, FleetDataProvider/simulation, hardware).
4. **Recommend one of these, with reasons, and wait for his decision:**
   - **(A) One codebase, modules switched on/off per company.** This project = InMotion with the telematics module turned off for this tenant. *(Claude's earlier recommendation, since InMotion was designed to be telematics-vendor-agnostic.)*
   - **(B) Separate repo**, copied from `inmotion-v2` with telematics stripped out.
   Explain the trade-off in plain terms: (A) means fixes and features help both products and there's only one thing to maintain; (B) is simpler at first but the two copies drift apart over time.

---

## 5. MVP scope

### 5.1 Assets
- Trucks (power units) and trailers as **separate assets**. Never merge them into one permanent record; pairing is temporary and dated.
- Per asset: unit number, VIN, make, model, year, plate, owner if not owned by the carrier (required by 49 CFR 396.3(b)(1)), in-service/out-of-service status, current odometer/engine hours (manually entered in MVP).
- CSV import for the initial fleet list (40–50 units; nobody should type them in one by one).

### 5.2 DVIR: mechanic side
Drivers will most likely keep doing their DVIRs in Samsara. This system handles what happens after a defect is reported:
- Record/import a defect (manual entry in MVP; from Samsara in Phase 2).
- Mechanic reviews it, creates or links a work order.
- Mechanic **certifies** either "repaired" or "repair unnecessary," with name, date, and signature. This is the 49 CFR 396.11(a)(3)(ii) certification.
- Out-of-service flag: a truck with an open safety-affecting defect shows as **not cleared to drive** (396.11(a)(3)(i)).
- **Design problem to flag, not solve alone:** under 396.13, the next driver must review the last DVIR and sign that repairs were certified. If drivers do that in Samsara but the repair certification lives in this system, the driver won't see it unless (a) we write the resolution back to Samsara, or (b) there's a printable/visible certification. Present the options to Alfonso.

### 5.3 Work orders
- Sources: DVIR defect, PM due, breakdown/road call, roadside inspection finding, annual/90-day inspection finding, manual.
- Fields: asset, complaint/cause/correction, priority, category, assigned tech, status (open → in progress → waiting on parts → complete → closed), labor time per tech, parts used (pulled from inventory), outside vendor work and invoice, odometer/hours at service, photos, notes.
- Tech sign-off on completion; closing a WO linked to a DVIR defect produces the repair certification.
- Mobile-friendly first: techs use phones on the shop floor.

### 5.4 Preventive maintenance
- PM schedules per asset or per asset group, due by **miles, engine hours, or days**, whichever comes first.
- "Due soon / overdue" list. One click to create the PM work order.
- Satisfies 396.3(b)(2): "a means to indicate the nature and due date" of inspection and maintenance.
- Annual inspection (396.17) tracked as a due item for every power unit and every trailer.

### 5.5 Parts inventory
- Parts catalog: part number, description, vendor(s), cost, bin location, qty on hand, min/reorder point.
- Parts issued to a work order automatically reduce stock and add cost to the WO.
- Low-stock list. Receiving parts in.
- Purchase orders are nice-to-have, not MVP, unless Alfonso says otherwise.

### 5.6 Compliance file per asset
One screen per truck/trailer showing its full history, exportable as a PDF for an audit:
- maintenance/repair records (396.3)
- DVIR defects + repair certifications (396.11)
- annual inspection reports (396.17 / 396.21)
- roadside inspection reports and their 15-day carrier certification (396.9(d))

Plus a place to store **inspector and brake inspector qualification evidence** per mechanic (396.19(b), 396.25(e)).

### 5.7 Reports (MVP-light)
- Maintenance cost per unit (parts + labor + outside vendor)
- Open work orders, overdue PMs, trucks currently out of service
- Downtime per unit

### 5.8 Roles
Same role model as InMotion: tech / shop lead / fleet manager / company admin (sees all departments) / platform operator (Apex, across all customer fleets). Strict cross-company isolation: one fleet never sees another's data.

---

## 6. Out of scope (do not build)

- GPS, live location, trips, geofences
- ELD, hours of service, driver logs
- J1939 / CAN / hardware gateways / TPMS
- The FleetDataProvider simulation / demo telemetry
- AI camera inspection sessions
- The national maintenance subscription program, tiers, pricing
- Remote vehicle control of any kind

---

## 7. Firm rules carried over from InMotion (do not reopen)

- **Tenant isolation is absolute.** Every new collection must be added to the tenant-scoped list, with a test proving one company can't read another's data.
- **Tractor and trailer stay distinct assets** with dated pairing.
- **No impersonation, anywhere, ever.** Acting as another user fabricates business records.
- **Audit logging:** any data change by the platform operator/super-admin is logged truthfully, attributed to them, in the customer's hash-chained log. Reads/browsing are not logged.
- **Signatures and certifications are never pre-filled.** Never pre-fill a negative finding ("no defect," "repair unnecessary") that a person only has to tap to confirm; that automates a legal attestation.
- **Demo/simulated data never enters the live environment.** The go-live gate defaults OFF; Alfonso turns it on himself. "Erase LIVE data" and "Erase DEMO data" are separate operations.
- **Records must hold up legally**: who did what, when, with timestamps; completed and certified records are corrected by an amendment trail, not silently overwritten.
- Electronic records are allowed under 49 CFR 390.32 (referenced in 396.11(a)(6) and 396.13(d)). Verify 390.32's requirements before relying on them.
- **Regulatory register:** any rule the code depends on (retention periods, due intervals) goes in `regulatory.py` (or its equivalent) with its citation, so it can be reviewed when regulations change.

---

## 8. Regulatory facts this system depends on

Verified against eCFR, 49 CFR Part 396, "up to date as of 10/23/2026." **Part 396 was amended several times in 2026 (Feb 19, Mar 23, Jun 22, Jul 21, Jul 22).** Re-verify before building any rule into code; don't rely on this summary or on general knowledge.

| Rule | What the system must do |
|---|---|
| 396.3(b) | Keep for each vehicle: ID (company number, make, serial number, year; owner if not the carrier), a way to show nature and due date of inspections/maintenance, and a record of inspection, repairs and maintenance with date and nature. *(The current text also says "for 30 consecutive days," added by the July 21, 2026 amendment. Read the actual text and the Federal Register notice 91 FR 45662 to understand what changed before building on it.)* |
| 396.3(c) | Retain those records where the vehicle is housed or maintained for **1 year**, and **6 months** after the vehicle leaves the carrier's control. |
| 396.11(a)(2) | Driver report lists defects; driver signs. No report required if no defect found. |
| 396.11(a)(3) | Carrier repairs safety-affecting defects before the vehicle is operated, and **certifies on the DVIR** "repaired" or "repair unnecessary" before it's operated again. |
| 396.11(a)(4) | Keep the DVIR, the repair certification, and the driver's review certification for **3 months**. |
| 396.13 | Before driving, the driver reviews the last DVIR and signs that repairs were certified. |
| 396.9(d)(3) | Roadside inspection report: carrier certifies violations corrected **within 15 days**; keep a copy **12 months**. |
| 396.17 | Every CMV (each unit in a combination, tractor and trailer separately) passes an Appendix A inspection at least once every **12 months**; documentation on the vehicle. |
| 396.21 | Annual inspection report contents (inspector, carrier, date, vehicle, components and results, certification); keep **14 months** where the vehicle is housed or maintained. |
| 396.19(b) | Keep inspector qualification evidence while they inspect and **1 year** after. |
| 396.25(e) | Keep brake inspector qualification evidence while employed in that role and **1 year** after. |

**California 90-day (BIT) inspections:** relevant in CA but not verified for this brief. Alfonso has a separate inspection-app effort (one intake → CA 90-day, federal annual, or both). Don't build CA rules until verified from official CA sources (CHP / CA DMV / official CA Code of Regulations) and Alfonso decides how this relates to the inspection app.

---

## 9. Samsara integration (Phase 2, after the MVP works on manual entry)

- **Read-only by default**, matching InMotion's rule that telematics is optional, never a dependency, and accessed through a normalization layer.
- What to pull: DVIRs and defects (so defects auto-create work requests), odometer and engine hours (to drive PM due dates), possibly fault codes.
- Samsara's developer changelog shows DVIR and defect endpoints (`GET /fleet/dvirs/history`, `GET /fleet/defects/history`, `PATCH /fleet/defects/{id}` to resolve) and vehicle stats for odometer/engine hours. **Those changelog entries are years old. Verify against Samsara's current API docs before writing any integration code.**
- **Decision for Alfonso:** writing a defect resolution back to Samsara (so the driver sees the certification in the Samsara app, see 5.2) is a write, not a read. It's not vehicle control, but it breaks "read-only." Explain plainly and let him decide.
- The fleet's Samsara admin must create an API token; Alfonso will need to request it. Never store the token in code; use Railway environment variables.

---

## 10. Open decisions (do NOT invent answers; ask Alfonso)

1. One codebase with modules (A) vs separate repo (B). See Step Zero.
2. Product name.
3. Whether the pilot fleet already pays for Samsara Maintenance.
4. How the repair certification reaches the driver for 396.13 (write-back vs printout vs other).
5. Purchase orders in MVP or later.
6. Offline use (poor signal in the shop) in MVP or later.
7. How this relates to the separate CA 90-day / annual inspection app.
8. Pricing and what Apex charges the pilot fleet.
9. Software ownership with the pilot fleet: Pacheco Industries must own the software. Alfonso should have that in writing before the fleet's data goes in.

---

## 11. Build order

1. **Step Zero audit** and decision (section 4).
2. Assets + CSV import.
3. Work orders (manual) + tech sign-off.
4. DVIR defect intake (manual) → WO → repair certification → out-of-service status.
5. Parts inventory tied to work orders.
6. PM schedules + due/overdue list + annual inspection tracking.
7. Compliance file per asset + PDF export.
8. Reports.
9. Samsara read-only integration.

After each step: run the full test suite, report real pass/fail numbers, and tell Alfonso in two or three plain sentences what changed and what he can now click on.

## 12. MVP "done" means

A tech can, on a phone: see today's open work orders, open one, log labor and parts, attach photos, and sign it off. A DVIR defect can go from reported → work order → certified repaired, and the truck shows cleared. PMs come due automatically from mileage/days. Parts stock drops as parts are used. A fleet manager can pull any truck's full maintenance file as a PDF. All of it is isolated to one company, logged, and tested.
