// DTR preview: a pretend server that runs inside the page.
//
// It answers the same addresses the real server does, with sample data held
// in memory, so the real screens (app.js) can be clicked through without a
// backend. It follows the main rules (who may do what, sign-off by typed
// name, signed jobs corrected by amendment) but it is NOT the real server:
// the real rules and their tests live in dtr/. Nothing here is saved; reload
// the page and it starts over.
"use strict";
(function () {
  const L = () => window.DTR_LOCALES;
  let lang = "en";
  const tx = (key, p = {}) => {
    let s = (L()[lang] || {})[key] || L().en[key] || key;
    for (const [k, v] of Object.entries(p)) s = s.split("{" + k + "}").join(v);
    return s;
  };
  const now = () => new Date().toISOString();
  const ago = (h) => new Date(Date.now() - h * 3600e3).toISOString();
  const id = () => Math.random().toString(16).slice(2) + Date.now().toString(16);
  const today = () => new Date().toISOString().slice(0, 10);
  const daysAgo = (d) => new Date(Date.now() - d * 864e5).toISOString().slice(0, 10);

  // ---------------------------------------------------------- sample world
  const ORG = { org_id: "org_demo", name: "Demo Fleet Co (sample)" };
  const PEOPLE = [
    { user_id: "u_admin", name: "Maria Lopez", email: "maria@demo.example", role: "admin" },
    { user_id: "u_lead", name: "Luis Ortega", email: "luis@demo.example", role: "shop_manager" },
    { user_id: "u_jose", name: "José Ramírez", email: "jose@demo.example", role: "mechanic" },
    { user_id: "u_harp", name: "Harpreet Singh", email: "harpreet@demo.example", role: "mechanic" },
    { user_id: "u_imran", name: "Imran Khan", email: "imran@demo.example", role: "mechanic" },
    { user_id: "u_fran", name: "Fran Lee", email: "fran@demo.example", role: "fleet_manager" },
  ].map((p) => ({ ...p, org_id: ORG.org_id, active: true, language: null }));
  const OPS = { user_id: "u_ops", name: "Apex", email: "ops@apex.example", role: "platform_operator",
                org_id: null, active: true, language: null };
  const USERS = [...PEOPLE, OPS];
  const P = Object.fromEntries(USERS.map((u) => [u.user_id, u]));

  const unit = (n, type, vin, year, make, model, plate, odo, extra = {}) => ({
    asset_id: "a_" + n.replace(/\W/g, ""), org_id: ORG.org_id, asset_type: type, unit_number: n,
    unit_number_key: n.toUpperCase(), vin, model_year: year, make, model, plate, plate_state: plate ? "CA" : null,
    owned_by_carrier: true, furnished_by: null, odometer: odo, engine_hours: null,
    odometer_at: odo != null ? ago(30) : null, odometer_by: odo != null ? "Maria Lopez" : null,
    notes: null, status: "active", retired_at: null, created_at: ago(400), ...extra });
  const UNITS = [
    unit("101", "power_unit", "1M8GDM9AXKP042788", 2019, "Freightliner", "Cascadia", "8ABC123", 412870),
    unit("102", "power_unit", "1XKYD49X7KJ123456", 2020, "Kenworth", "T680", "8XYZ789", 301550),
    unit("105", "power_unit", "3AKJHHDR5LSLA1234", 2021, "Freightliner", "Cascadia", "9DEF456", 188020),
    unit("108", "power_unit", "1XPBD49X1MD765432", 2022, "Peterbilt", "579", "9GHI321", 96400),
    unit("T-7", "trailer", "1UYVS2538KU123456", 2018, "Utility", "3000R reefer", "4AB1234", null,
         { engine_hours: 11240, engine_hours_at: ago(30), engine_hours_by: "Maria Lopez" }),
    unit("T-8", "trailer", "1JJV532D8KL123456", 2019, "Wabash", "DuraPlate", "4AB5678", null),
    unit("T-12", "trailer", null, 2011, "Great Dane", "Flatbed", "4CD9012", null,
         { owned_by_carrier: false, furnished_by: "Penske Leasing" }),
  ];
  const U = (n) => UNITS.find((u) => u.unit_number === n);

  let woNo = 0;
  const WOS = [];
  const line = (by, at, data) => ({ line_id: id(), at, by: by.user_id, by_name: by.name, ...data });
  const job = (unitNo, data, extra = {}) => {
    const u = U(unitNo);
    const by = P[data.by || "u_fran"];
    const w = {
      work_order_id: "wo_" + (++woNo), org_id: ORG.org_id, number: woNo, asset_id: u.asset_id,
      unit_number: u.unit_number, asset_type: u.asset_type, complaint: data.complaint, cause: null,
      correction: null, priority: data.priority || "normal", category: data.category || "other",
      source: data.source || "manual", source_ref: data.source_ref || null, odometer: data.odometer ?? null,
      engine_hours: null, status: "open", assigned: [], labor: [], parts: [], vendor: [], notes: [],
      photos: [], amendments: [], history: [{ at: ago(data.age || 5), by: by.user_id, by_name: by.name, from: null, to: "open" }],
      signoff: null, closed: null, cancelled: null, created_at: ago(data.age || 5),
      created_by: by.user_id, created_name: by.name, updated_at: ago(1), ...extra };
    WOS.push(w);
    return w;
  };
  const step = (w, to, who, hAgo) => { w.history.push({ at: ago(hAgo), by: who.user_id, by_name: who.name, from: w.status, to }); w.status = to; };
  const tech = (uid) => ({ user_id: uid, name: P[uid].name });

  // A spread of jobs across the ladder.
  let w = job("101", { complaint: "Driver reports left rear brake light out", priority: "high",
    category: "lighting", source: "dvir_defect", age: 6 });
  w.assigned = [tech("u_jose")];
  step(w, "in_progress", P.u_jose, 4);
  w.labor.push(line(P.u_jose, ago(3), { user_id: "u_jose", name: "José Ramírez", hours: 0.5, date: today(), note: "Diagnóstico" }));

  w = job("102", { complaint: "Air leak at driver side brake chamber, audible with brakes applied",
    priority: "urgent", category: "brakes", source: "roadside", source_ref: "CA-RI-55120", age: 20, by: "u_lead" });
  w.assigned = [tech("u_harp")];
  step(w, "in_progress", P.u_harp, 18); step(w, "waiting_parts", P.u_harp, 16);
  w.cause = "Cracked type 30/30 spring brake chamber diaphragm";
  w.labor.push(line(P.u_harp, ago(17), { user_id: "u_harp", name: "Harpreet Singh", hours: 1.25, date: daysAgo(1), note: "Leak check, pulled chamber" }));
  w.parts.push(line(P.u_harp, ago(16), { part_number: "3030-SBC", description: "Spring brake chamber 30/30", qty: 1, unit_cost: 89.5 }));
  w.notes.push(line(P.u_lead, ago(15), { text: "Chamber on order from FleetPride, ETA tomorrow AM" }));

  w = job("T-7", { complaint: "Reefer unit not holding temp, alarm code 63", priority: "high",
    category: "refrigeration", age: 3 });

  w = job("105", { complaint: "PM-A service due", priority: "normal", category: "pm_service",
    source: "pm", odometer: 188020, age: 30, by: "u_lead" });
  w.assigned = [tech("u_imran")];
  step(w, "in_progress", P.u_imran, 28);
  w.cause = "Scheduled service"; w.correction = "Changed oil and filters, greased chassis, checked brakes and tires. All within spec.";
  w.labor.push(line(P.u_imran, ago(27), { user_id: "u_imran", name: "Imran Khan", hours: 2.5, date: daysAgo(1), note: null }));
  w.parts.push(line(P.u_imran, ago(27), { part_number: "LF14000NN", description: "Oil filter", qty: 1, unit_cost: 38.2 }));
  w.parts.push(line(P.u_imran, ago(27), { part_number: "15W40", description: "Engine oil, gal", qty: 11, unit_cost: 14.5 }));
  w.signoff = { user_id: "u_imran", name: "Imran Khan", role: "mechanic", typed_name: "Imran Khan", at: ago(26),
    statement: "I did or supervised the work on this job, and it is complete as described in the correction above.", statement_lang: "en" };
  step(w, "complete", P.u_imran, 26);

  w = job("108", { complaint: "Steer tire worn on outer edge", priority: "normal", category: "tires_wheels", age: 80 });
  w.assigned = [tech("u_jose")];
  step(w, "in_progress", P.u_jose, 78);
  w.cause = "Toe out of spec"; w.correction = "Replaced RF steer tire, sent out for alignment";
  w.labor.push(line(P.u_jose, ago(77), { user_id: "u_jose", name: "José Ramírez", hours: 1, date: daysAgo(3), note: null }));
  w.vendor.push(line(P.u_lead, ago(70), { vendor: "Valley Alignment", invoice_number: "VA-20931", description: "3-axle alignment", amount: 245 }));
  w.signoff = { user_id: "u_jose", name: "José Ramírez", role: "mechanic", typed_name: "José Ramírez", at: ago(69),
    statement: "Yo realicé o supervisé el trabajo de esta orden, y está completo tal como se describe en la corrección de arriba.", statement_lang: "es" };
  step(w, "complete", P.u_jose, 69);
  w.closed = { user_id: "u_lead", name: "Luis Ortega", at: ago(60) };
  step(w, "closed", P.u_lead, 60);

  const LOG = [];
  const log = (who, action) => LOG.push({ seq: LOG.length + 1, org_id: ORG.org_id, at: now(),
    actor_user_id: who.user_id, actor_name: who.name, actor_role: who.role, action, before: null, after: null });
  [["u_ops", "org.created"], ["u_ops", "user.created"], ["u_admin", "units.imported"],
   ["u_lead", "wo.created"], ["u_imran", "wo.signed"], ["u_lead", "wo.closed"]]
    .forEach(([u, a]) => log(P[u], a));

  // ---------------------------------------------------------- plumbing
  let me = null;
  const PERMS = { admin: ["edit_units", "import_units", "manage_people", "read_audit"],
    fleet_manager: ["edit_units", "import_units", "manage_people"], shop_manager: ["edit_units", "manage_people"],
    mechanic: [], platform_operator: [] };
  const GRANT = { admin: ["mechanic", "shop_manager", "fleet_manager", "admin"], fleet_manager: ["fleet_manager"],
    shop_manager: ["mechanic", "shop_manager"], mechanic: [], platform_operator: [] };
  const LEADS = ["shop_manager", "admin"], TECHS = ["mechanic", "shop_manager", "admin"];
  const STAFF = ["mechanic", "shop_manager", "fleet_manager", "admin"];
  const ACTIVE = ["open", "in_progress", "waiting_parts"], SIGNED = ["complete", "closed"];

  class Stop { constructor(status, detail) { this.status = status; this.detail = detail; } }
  const stop = (status, key, p) => { throw new Stop(status, tx(key, p)); };
  const stopMany = (errors) => { throw new Stop(400, { errors }); };
  const reply = (status, body) => ({ ok: status < 400, status,
    json: async () => body, blob: async () => body });
  const totals = (w) => {
    const live = (l) => l.filter((x) => !x.voided);
    const parts = live(w.parts).reduce((s, l) => s + (l.qty || 0) * (l.unit_cost || 0), 0);
    const vendor = live(w.vendor).reduce((s, l) => s + (l.amount || 0), 0);
    return { labor_hours: live(w.labor).reduce((s, l) => s + (l.hours || 0), 0),
      parts_cost: parts, vendor_cost: vendor, cost_without_labor: parts + vendor };
  };
  const out = (w) => ({ ...JSON.parse(JSON.stringify(w)), totals: totals(w) });
  const mustBe = (ok, key = "err.not_allowed") => { if (!ok) stop(403, key); };
  const numOr = (v, field, max, allowZero = true) => {
    if (v === null || v === undefined || v === "") return [null, null];
    const n = Number(String(v).replace(/,/g, ""));
    if (Number.isNaN(n)) return [null, tx("err.not_a_number", { field: tx("field." + field) })];
    if (n < 0 || (!allowZero && n === 0)) return [null, tx("err.must_be_positive", { field: tx("field." + field) })];
    if (max && n > max) return [null, tx("err.too_large", { field: tx("field." + field), max })];
    return [n, null];
  };
  const stamp = () => ({ line_id: id(), at: now(), by: me.user_id, by_name: me.name });
  const norm = (s) => (s || "").trim().replace(/\s+/g, " ").toLocaleLowerCase();
  const pub = (u) => ({ user_id: u.user_id, name: u.name, email: u.email, role: u.role,
    org_id: u.org_id, active: u.active, language: u.language || "en" });

  // Sign-in: any password works in the preview; the quick buttons fill it in.
  const routes = [];
  const on = (method, pattern, fn) => routes.push([method, new RegExp("^" + pattern + "$"), fn]);

  on("POST", "/api/auth/login", (b) => {
    const u = USERS.find((x) => x.email === (b.email || "").toLowerCase());
    if (!u) stop(401, "err.bad_login");
    me = u;
    return { token: "preview-" + u.user_id, user: pub(u), org: u.org_id ? ORG : null };
  });
  on("GET", "/api/me", () => { if (!me) stop(401, "err.sign_in_first"); return { user: pub(me), org: me.org_id ? ORG : null, can: PERMS[me.role] }; });
  on("PATCH", "/api/me", (b) => { me.language = b.language; return { language: b.language }; });

  // --- units
  on("GET", "/api/assets", (b, q) => {
    let rows = UNITS.filter((u) => u.status === (q.get("status") || "active"));
    if (q.get("type")) rows = rows.filter((u) => u.asset_type === q.get("type"));
    const n = (q.get("q") || "").trim().toUpperCase();
    if (n) rows = rows.filter((u) => u.unit_number_key.includes(n) || (u.vin || "").includes(n) || (u.plate || "").includes(n));
    return { units: rows };
  });
  on("GET", "/api/assets/([^/]+)", (b, q, [aid]) => {
    const u = UNITS.find((x) => x.asset_id === aid);
    if (!u) stop(404, "err.no_such_unit");
    return u;
  });
  const unitFrom = (b, old = {}) => {
    const errors = [];
    const v = { ...old, ...b };
    if (!["power_unit", "trailer"].includes(v.asset_type)) errors.push(tx("unit.err.type_required"));
    if (!(v.unit_number || "").trim()) errors.push(tx("unit.err.number_required"));
    const key = (v.unit_number || "").trim().toUpperCase();
    if (key && UNITS.some((u) => u.unit_number_key === key && u.asset_id !== old.asset_id))
      errors.push(tx("unit.err.exists", { unit: v.unit_number }));
    if (!v.owned_by_carrier && !(v.furnished_by || "").trim()) errors.push(tx("unit.err.furnished_by_required"));
    if (errors.length) stopMany(errors);
    return { ...v, unit_number: v.unit_number.trim(), unit_number_key: key,
      vin: v.vin ? v.vin.toUpperCase().replace(/[\s-]/g, "") : null,
      model_year: v.model_year ? Number(v.model_year) : null,
      odometer: v.odometer != null && v.odometer !== "" ? Number(v.odometer) : null,
      engine_hours: v.engine_hours != null && v.engine_hours !== "" ? Number(v.engine_hours) : null };
  };
  on("POST", "/api/assets", (b) => {
    mustBe(PERMS[me.role].includes("edit_units"), "err.role_cannot_edit_units");
    const u = { ...unitFrom(b), asset_id: "a_" + id(), org_id: ORG.org_id, status: "active", created_at: now() };
    if (u.odometer != null) { u.odometer_at = now(); u.odometer_by = me.name; }
    UNITS.push(u); log(me, "unit.created");
    return { unit: u, warnings: [] };
  });
  on("PATCH", "/api/assets/([^/]+)", (b, q, [aid]) => {
    mustBe(PERMS[me.role].includes("edit_units"), "err.role_cannot_edit_units");
    const i = UNITS.findIndex((x) => x.asset_id === aid);
    const old = UNITS[i];
    const u = unitFrom(b, old);
    if (u.odometer !== old.odometer) { u.odometer_at = now(); u.odometer_by = me.name; }
    UNITS[i] = u; log(me, "unit.edited");
    return { unit: u, warnings: [] };
  });
  on("POST", "/api/assets/([^/]+)/retire", (b, q, [aid]) => {
    mustBe(PERMS[me.role].includes("edit_units"), "err.role_cannot_edit_units");
    if (!(b.reason || "").trim()) stop(400, "err.retire_reason_required");
    const u = UNITS.find((x) => x.asset_id === aid);
    Object.assign(u, { status: "retired", retired_at: now(), retired_reason: b.reason.trim() });
    log(me, "unit.retired");
    return { unit: u };
  });
  on("POST", "/api/assets/import", () => stop(400, "app.preview_banner"));

  // --- people
  on("GET", "/api/users", () => ({ users: PEOPLE.map(pub),
    may_add: PERMS[me.role].includes("manage_people") ? GRANT[me.role] : [] }));
  on("POST", "/api/users", (b) => {
    mustBe(PERMS[me.role].includes("manage_people") && GRANT[me.role].includes(b.role));
    if ((b.password || "").length < 8) stop(400, "err.password_short");
    if (USERS.some((u) => u.email === (b.email || "").toLowerCase())) stop(409, "err.email_taken");
    const u = { user_id: "u_" + id(), name: b.name.trim(), email: b.email.toLowerCase(), role: b.role,
      org_id: ORG.org_id, active: true, language: b.language };
    PEOPLE.push(u); USERS.push(u); P[u.user_id] = u; log(me, "user.created");
    return pub(u);
  });

  // --- log and console
  on("GET", "/api/audit", () => { mustBe(me.role === "admin", "err.admin_only_log"); return { entries: [...LOG].reverse() }; });
  on("GET", "/api/audit/verify", () => ({ ok: true, entries: LOG.length }));
  on("GET", "/api/operator/orgs", () => { mustBe(me.role === "platform_operator", "err.operator_only");
    return { orgs: [{ ...ORG, units: UNITS.filter((u) => u.status === "active").length, people: PEOPLE.length }] }; });
  on("POST", "/api/operator/orgs", () => stop(400, "app.preview_banner"));

  // --- work orders
  on("GET", "/api/workorders/meta", () => ({
    statuses: ["open", "in_progress", "waiting_parts", "complete", "closed", "cancelled"],
    priorities: ["urgent", "high", "normal", "low"],
    categories: ["engine", "brakes", "tires_wheels", "electrical", "lighting", "suspension_steering", "drivetrain",
      "cooling", "fuel", "exhaust_aftertreatment", "hvac", "body_frame", "coupling", "refrigeration", "pm_service",
      "inspection", "other"],
    sources: ["manual", "dvir_defect", "pm", "breakdown", "roadside", "inspection"],
    techs: PEOPLE.filter((p) => ["mechanic", "shop_manager"].includes(p.role)).map((p) => ({ user_id: p.user_id, name: p.name, role: p.role })),
    may: { create: STAFF.includes(me.role), work: TECHS.includes(me.role), lead: LEADS.includes(me.role), note: STAFF.includes(me.role) } }));
  const RANK = { urgent: 0, high: 1, normal: 2, low: 3 };
  on("GET", "/api/workorders", (b, q) => {
    const view = q.get("view") || "active";
    let rows = WOS.filter((w) => view === "all" || (view === "active" ? ACTIVE.includes(w.status) : w.status === view));
    if (q.get("mine") === "true") rows = rows.filter((w) => w.assigned.some((a) => a.user_id === me.user_id) || w.labor.some((l) => l.user_id === me.user_id));
    if (q.get("asset_id")) rows = rows.filter((w) => w.asset_id === q.get("asset_id"));
    rows.sort(view === "active" ? (a, c) => RANK[a.priority] - RANK[c.priority] || a.number - c.number : (a, c) => c.number - a.number);
    return { work_orders: rows.map(out) };
  });
  const get = (wid) => { const w = WOS.find((x) => x.work_order_id === wid); if (!w) stop(404, "wo.err.not_found"); return w; };
  on("GET", "/api/workorders/([^/]+)", (b, q, [wid]) => out(get(wid)));
  on("POST", "/api/workorders", (b) => {
    mustBe(STAFF.includes(me.role));
    const u = UNITS.find((x) => x.asset_id === b.asset_id);
    const errors = [];
    if (!u) errors.push(tx("wo.err.need_unit"));
    if (!(b.complaint || "").trim()) errors.push(tx("wo.err.need_complaint"));
    if (errors.length) stopMany(errors);
    const w = job(u.unit_number, { ...b, complaint: b.complaint.trim(), by: me.user_id, age: 0 });
    log(me, "wo.created");
    return out(w);
  });
  on("PATCH", "/api/workorders/([^/]+)", (b, q, [wid]) => {
    const w = get(wid);
    mustBe(TECHS.includes(me.role));
    if (!ACTIVE.includes(w.status)) stop(400, "wo.err.signed_use_amend");
    if ("complaint" in b && !(b.complaint || "").trim()) stopMany([tx("wo.err.need_complaint")]);
    for (const f of ["complaint", "cause", "correction", "priority", "category"]) if (f in b) w[f] = b[f] || null;
    for (const f of ["odometer", "engine_hours"]) if (f in b) w[f] = b[f] == null ? null : Number(b[f]);
    log(me, "wo.edited");
    return out(w);
  });
  const MOVES = { open: ["in_progress", "waiting_parts"], in_progress: ["open", "waiting_parts"], waiting_parts: ["open", "in_progress"] };
  on("POST", "/api/workorders/([^/]+)/status", (b, q, [wid]) => {
    const w = get(wid); mustBe(TECHS.includes(me.role));
    if (!(MOVES[w.status] || []).includes(b.status)) stop(400, "wo.err.bad_move");
    step(w, b.status, me, 0); log(me, "wo.status"); return out(w);
  });
  on("POST", "/api/workorders/([^/]+)/assign", (b, q, [wid]) => {
    const w = get(wid); mustBe(LEADS.includes(me.role));
    w.assigned = b.user_ids.map(tech); log(me, "wo.assigned"); return out(w);
  });
  const amendOk = (w, reason) => {
    if (w.status === "cancelled") stop(400, "wo.err.cancelled");
    if (SIGNED.includes(w.status)) {
      mustBe(LEADS.includes(me.role) || (w.signoff && w.signoff.user_id === me.user_id), "wo.err.cannot_amend");
      if (!(reason || "").trim()) stop(400, "wo.err.need_reason");
      return { amended: true, reason: reason.trim() };
    }
    return {};
  };
  on("POST", "/api/workorders/([^/]+)/labor", (b, q, [wid]) => {
    const w = get(wid); mustBe(TECHS.includes(me.role));
    const extra = amendOk(w, b.reason);
    let who = { user_id: me.user_id, name: me.name };
    if (b.user_id && b.user_id !== me.user_id) { mustBe(LEADS.includes(me.role), "wo.err.own_labor_only"); who = tech(b.user_id); }
    const [hours, e] = numOr(b.hours, "hours", 24, false);
    if (e || hours == null) stopMany([e || tx("err.required", { field: tx("field.hours") })]);
    w.labor.push({ ...stamp(), ...who, hours, date: b.date || today(), note: b.note || null, ...extra });
    log(me, "wo.labor"); return out(w);
  });
  on("POST", "/api/workorders/([^/]+)/parts", (b, q, [wid]) => {
    const w = get(wid); mustBe(TECHS.includes(me.role));
    const extra = amendOk(w, b.reason);
    const errors = [];
    if (!b.part_number && !b.description) errors.push(tx("err.part_needs_name"));
    const [qty, e1] = numOr(b.qty, "qty", 100000, false); if (e1 || qty == null) errors.push(e1 || tx("err.required", { field: tx("field.qty") }));
    const [cost, e2] = numOr(b.unit_cost, "unit_cost", 1e6); if (e2) errors.push(e2);
    if (errors.length) stopMany(errors);
    w.parts.push({ ...stamp(), part_number: b.part_number, description: b.description, qty, unit_cost: cost, ...extra });
    log(me, "wo.part"); return out(w);
  });
  on("POST", "/api/workorders/([^/]+)/vendor", (b, q, [wid]) => {
    const w = get(wid); mustBe(TECHS.includes(me.role));
    const extra = amendOk(w, b.reason);
    if (!(b.vendor || "").trim()) stopMany([tx("err.required", { field: tx("field.vendor") })]);
    const [amount, e] = numOr(b.amount, "amount", 1e7); if (e) stopMany([e]);
    w.vendor.push({ ...stamp(), vendor: b.vendor, invoice_number: b.invoice_number, description: b.description, amount, ...extra });
    log(me, "wo.vendor"); return out(w);
  });
  on("POST", "/api/workorders/([^/]+)/void", (b, q, [wid]) => {
    const w = get(wid); mustBe(TECHS.includes(me.role));
    if (!(b.reason || "").trim()) stop(400, "wo.err.need_reason");
    if (SIGNED.includes(w.status)) mustBe(LEADS.includes(me.role) || (w.signoff && w.signoff.user_id === me.user_id), "wo.err.cannot_amend");
    const l = (w[b.kind] || []).find((x) => x.line_id === b.line_id && !x.voided);
    if (!l) stop(404, "wo.err.no_line");
    if (!LEADS.includes(me.role) && l.by !== me.user_id) stop(403, "wo.err.own_lines_only");
    Object.assign(l, { voided: true, void_reason: b.reason.trim(), voided_by: me.name, voided_at: now() });
    log(me, "wo.void"); return out(w);
  });
  on("POST", "/api/workorders/([^/]+)/notes", (b, q, [wid]) => {
    const w = get(wid); mustBe(STAFF.includes(me.role));
    if (!(b.text || "").trim()) stopMany([tx("err.required", { field: tx("field.note") })]);
    w.notes.push({ ...stamp(), text: b.text.trim() }); log(me, "wo.note"); return out(w);
  });
  const PHOTOS = {};
  on("POST", "/api/workorders/([^/]+)/photos", (b, q, [wid]) => {
    const w = get(wid); mustBe(STAFF.includes(me.role));
    const pid = id(); PHOTOS[pid] = b.get("file");
    w.photos.push({ ...stamp(), photo_id: pid, caption: b.get("caption") || null }); log(me, "wo.photo"); return out(w);
  });
  on("GET", "/api/workorders/([^/]+)/photos/([^/]+)", (b, q, [, pid]) => PHOTOS[pid]);
  on("POST", "/api/workorders/([^/]+)/complete", (b, q, [wid]) => {
    const w = get(wid);
    const errors = [];
    if (!ACTIVE.includes(w.status)) errors.push(tx("wo.err.not_open"));
    const worked = w.assigned.some((a) => a.user_id === me.user_id) || w.labor.some((l) => l.user_id === me.user_id && !l.voided);
    if (!(LEADS.includes(me.role) || (me.role === "mechanic" && worked))) errors.push(tx("wo.err.cannot_sign"));
    if (!w.correction) errors.push(tx("wo.err.need_correction"));
    if (!b.typed_name || norm(b.typed_name) !== norm(me.name)) errors.push(tx("wo.err.name_mismatch", { name: me.name }));
    if (errors.length) stopMany(errors);
    w.signoff = { user_id: me.user_id, name: me.name, role: me.role, typed_name: b.typed_name.trim(), at: now(),
      statement: tx("wo.signoff.statement"), statement_lang: lang };
    step(w, "complete", me, 0); log(me, "wo.signed");
    const warnings = [];
    if (!w.labor.some((l) => !l.voided)) warnings.push(tx("wo.warn.no_labor"));
    if (!w.cause) warnings.push(tx("wo.warn.no_cause"));
    return { ...out(w), warnings };
  });
  on("POST", "/api/workorders/([^/]+)/close", (b, q, [wid]) => {
    const w = get(wid); mustBe(LEADS.includes(me.role));
    if (w.status !== "complete") stop(400, "wo.err.close_needs_complete");
    w.closed = { user_id: me.user_id, name: me.name, at: now() }; step(w, "closed", me, 0); log(me, "wo.closed"); return out(w);
  });
  on("POST", "/api/workorders/([^/]+)/cancel", (b, q, [wid]) => {
    const w = get(wid); mustBe(LEADS.includes(me.role));
    if (!(b.reason || "").trim()) stop(400, "wo.err.need_reason");
    if (!ACTIVE.includes(w.status)) stop(400, "wo.err.not_open");
    w.cancelled = { user_id: me.user_id, name: me.name, at: now(), reason: b.reason.trim() };
    step(w, "cancelled", me, 0); log(me, "wo.cancelled"); return out(w);
  });
  on("POST", "/api/workorders/([^/]+)/amend", (b, q, [wid]) => {
    const w = get(wid);
    if (!SIGNED.includes(w.status)) stop(400, "wo.err.amend_needs_signed");
    mustBe(LEADS.includes(me.role) || (w.signoff && w.signoff.user_id === me.user_id), "wo.err.cannot_amend");
    if (!(b.reason || "").trim()) stop(400, "wo.err.need_reason");
    let v = (b.value || "").trim() || null;
    if (["odometer", "engine_hours"].includes(b.field) && v !== null) v = Number(v);
    if (w[b.field] === v) stop(400, "wo.err.no_change");
    w.amendments.push({ ...stamp(), field: b.field, before: w[b.field], after: v, reason: b.reason.trim() });
    w[b.field] = v; log(me, "wo.amended"); return out(w);
  });

  // ---------------------------------------------------------- the fetch stand-in
  window.DTR_FETCH = async (path, opts = {}) => {
    const url = new URL(path, "https://preview.local");
    const method = (opts.method || "GET").toUpperCase();
    lang = (opts.headers && opts.headers["X-Lang"]) || "en";
    let body = {};
    if (opts.body instanceof FormData) body = opts.body;
    else if (opts.body) body = JSON.parse(opts.body);
    for (const [m, re, fn] of routes) {
      const hit = method === m && url.pathname.match(re);
      if (!hit) continue;
      try { return reply(200, await fn(body, url.searchParams, hit.slice(1))); }
      catch (e) {
        if (e instanceof Stop) return reply(e.status, { detail: e.detail });
        console.error(e); return reply(500, { detail: "Preview error" });
      }
    }
    return reply(404, { detail: "Not in preview" });
  };

  // Quick sign-in buttons for each role.
  const QUICK = [["u_jose", "mechanic"], ["u_harp", "mechanic"], ["u_lead", "shop_manager"],
                 ["u_fran", "fleet_manager"], ["u_admin", "admin"], ["u_ops", "platform_operator"]];
  window.DTR_PREVIEW = {
    loginHelp: () => `<div class="quick">
      ${QUICK.map(([u, r]) => `<button type="button" class="secondary wide" data-quick="${u}">
        <b>${P[u].name}</b> · ${(L()[document.documentElement.lang] || L().en)["role." + r]}</button>`).join("")}</div>`,
    wireLogin: () => document.querySelectorAll("[data-quick]").forEach((b) => (b.onclick = () => {
      document.querySelector("#em").value = P[b.dataset.quick].email;
      document.querySelector("#pw").value = "preview";
      document.querySelector("#f").requestSubmit();
    })),
  };
})();
