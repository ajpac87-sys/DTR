// DTR screens. Plain JavaScript, no build step.
// The server checks every permission; hiding a button here is only a
// convenience so people don't see things they can't use.
"use strict";

const S = { token: null, me: null, orgNames: {} };
const $ = (sel) => document.querySelector(sel);
const view = $("#view");

try { S.token = localStorage.getItem("dtr_token"); } catch (e) { /* private mode */ }

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function toast(text) {
  const t = $("#toast");
  t.textContent = text; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 3000);
}

async function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (S.token) headers.Authorization = "Bearer " + S.token;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.json);
  }
  const r = await fetch(path, { ...opts, headers });
  let data = null;
  try { data = await r.json(); } catch (e) { /* empty body */ }
  if (r.status === 401 && path !== "/api/auth/login") { signOut(); }
  if (!r.ok) {
    const d = data && data.detail;
    const err = new Error(typeof d === "string" ? d : "Something went wrong.");
    err.detail = d; throw err;
  }
  return data;
}

function msgBox(kind, title, items) {
  if (!title && !(items && items.length)) return "";
  const list = items && items.length
    ? "<ul>" + items.map((i) => `<li>${esc(i)}</li>`).join("") + "</ul>" : "";
  return `<div class="msg ${kind}">${esc(title || "")}${list}</div>`;
}

function errorHtml(e) {
  if (e.detail && e.detail.errors) {
    return msgBox("bad", "Fix these first:", e.detail.errors) +
           msgBox("warn", "", e.detail.warnings);
  }
  if (Array.isArray(e.detail)) {   // the server's own field validation
    return msgBox("bad", "Check the form:", e.detail.map(
      (d) => `${(d.loc || []).slice(-1)[0]}: ${d.msg}`));
  }
  return msgBox("bad", e.message);
}

const can = (p) => S.me && S.me.can.includes(p);
const role = () => S.me && S.me.user.role;
const fmtNum = (n) => (n == null ? "" : Number(n).toLocaleString());
const fmtDate = (d) => (d ? new Date(d.endsWith("Z") || d.includes("+") ? d : d + "Z")
  .toLocaleString() : "");

// ---------------------------------------------------------------- sign-in

function showLogin(error) {
  $("#top").hidden = true; $("#tabs").hidden = true;
  view.innerHTML = `
    <div class="login card">
      <h1>Sign in to DTR</h1>
      ${error ? msgBox("bad", error) : ""}
      <form id="f">
        <label for="em">Email</label>
        <input id="em" type="email" autocomplete="username" required>
        <label for="pw">Password</label>
        <input id="pw" type="password" autocomplete="current-password" required>
        <p><button class="primary" style="width:100%">Sign in</button></p>
      </form>
    </div>`;
  $("#f").onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      const r = await api("/api/auth/login", { method: "POST",
        json: { email: $("#em").value, password: $("#pw").value } });
      S.token = r.token;
      try { localStorage.setItem("dtr_token", r.token); } catch (e) { /* ok */ }
      await start();
    } catch (e) { showLogin(e.message); }
  };
}

function signOut() {
  S.token = null; S.me = null; S.orgNames = {};
  try { localStorage.removeItem("dtr_token"); } catch (e) { /* ok */ }
  showLogin();
}
$("#signout").onclick = signOut;

// ---------------------------------------------------------------- tabs

const TABS = {
  platform_operator: [["companies", "Companies"], ["units", "Units"]],
  admin: [["units", "Units"], ["people", "People"], ["log", "Change log"]],
  fleet_manager: [["units", "Units"], ["people", "People"]],
  shop_manager: [["units", "Units"], ["people", "People"]],
  mechanic: [["units", "Units"]],
};
const SCREENS = {};

function go(name, arg) {
  document.querySelectorAll("#tabs button").forEach((b) =>
    b.classList.toggle("on", b.dataset.tab === name));
  window.scrollTo(0, 0);
  SCREENS[name](arg).catch((e) => { view.innerHTML = errorHtml(e); });
}

async function start() {
  if (!S.token) return showLogin();
  try { S.me = await api("/api/me"); } catch (e) { return; }
  $("#top").hidden = false;
  $("#org-name").textContent = S.me.org ? S.me.org.name : "Apex console";
  const tabs = TABS[role()] || [];
  const nav = $("#tabs");
  nav.innerHTML = tabs.map(([k, l]) =>
    `<button data-tab="${k}">${esc(l)}</button>`).join("");
  nav.hidden = tabs.length < 2;
  nav.querySelectorAll("button").forEach((b) => (b.onclick = () => go(b.dataset.tab)));
  if (role() === "platform_operator") {
    const r = await api("/api/operator/orgs");
    r.orgs.forEach((o) => (S.orgNames[o.org_id] = o.name));
  }
  go(tabs[0][0]);
}

// ---------------------------------------------------------------- units

const TYPE_LABEL = { power_unit: "Power unit", trailer: "Trailer" };

SCREENS.units = async (state = {}) => {
  const q = state.q || "", type = state.type || "", status = state.status || "active";
  const r = await api(`/api/assets?q=${encodeURIComponent(q)}&type=${type}&status=${status}`);
  const edit = can("edit_units"), imp = can("import_units");
  view.innerHTML = `
    <div class="row"><h1 class="grow">Units</h1>
      ${imp ? '<button class="secondary" id="imp">Import list</button>' : ""}
      ${edit ? '<button class="primary" id="add">Add unit</button>' : ""}
    </div>
    <div class="row" style="margin-bottom:10px">
      <input id="q" class="grow" placeholder="Search unit, VIN or plate" value="${esc(q)}">
      <select id="type" style="width:auto">
        <option value="">All</option>
        <option value="power_unit" ${type === "power_unit" ? "selected" : ""}>Power units</option>
        <option value="trailer" ${type === "trailer" ? "selected" : ""}>Trailers</option>
      </select>
      <select id="status" style="width:auto">
        <option value="active">In fleet</option>
        <option value="retired" ${status === "retired" ? "selected" : ""}>Left fleet</option>
      </select>
    </div>
    <p class="muted">${r.units.length} unit${r.units.length === 1 ? "" : "s"}</p>
    <div id="list">${r.units.map(unitRow).join("") ||
      `<div class="card muted">No units yet.${imp ? " Use <b>Import list</b> to load the fleet from a spreadsheet." : ""}</div>`}</div>`;
  const reload = () => go("units", { q: $("#q").value, type: $("#type").value,
                                     status: $("#status").value });
  let t; $("#q").oninput = () => { clearTimeout(t); t = setTimeout(reload, 350); };
  $("#type").onchange = reload; $("#status").onchange = reload;
  if (edit) $("#add").onclick = () => SCREENS.unitForm();
  if (imp) $("#imp").onclick = () => SCREENS.importUnits();
  view.querySelectorAll("[data-id]").forEach((b) =>
    (b.onclick = () => SCREENS.unit(b.dataset.id)));
};

function unitRow(u) {
  const sub = [u.model_year, u.make, u.model].filter(Boolean).join(" ");
  const org = S.orgNames[u.org_id] ? ` · ${esc(S.orgNames[u.org_id])}` : "";
  return `<button class="card list-item" data-id="${esc(u.asset_id)}">
    <span class="grow"><span class="big">${esc(u.unit_number)}</span>
      <span class="pill">${esc(TYPE_LABEL[u.asset_type])}</span><br>
      <span class="muted">${esc(sub) || "No make/year"}${org}</span></span>
    <span class="muted">›</span></button>`;
}

SCREENS.unit = async (id) => {
  const u = await api(`/api/assets/${id}`);
  const edit = can("edit_units") && u.status === "active";
  const rows = [
    ["Type", TYPE_LABEL[u.asset_type]], ["VIN", u.vin || "Not entered"],
    ["Year", u.model_year], ["Make", u.make], ["Model", u.model],
    ["Plate", [u.plate, u.plate_state].filter(Boolean).join(" ")],
    ["Owner", u.owned_by_carrier ? "Company-owned" : "Furnished by " + u.furnished_by],
    ["Odometer", u.odometer != null ? `${fmtNum(u.odometer)} mi (${esc(u.odometer_by)}, ${fmtDate(u.odometer_at)})` : ""],
    ["Engine hours", u.engine_hours != null ? `${fmtNum(u.engine_hours)} (${esc(u.engine_hours_by)}, ${fmtDate(u.engine_hours_at)})` : ""],
    ["Notes", u.notes],
  ];
  if (S.orgNames[u.org_id]) rows.unshift(["Company", S.orgNames[u.org_id]]);
  if (u.status === "retired") rows.push(["Left fleet", `${fmtDate(u.retired_at)}: ${u.retired_reason}`]);
  view.innerHTML = `
    <button class="link" id="back">‹ Units</button>
    <div class="row"><h1 class="grow">Unit ${esc(u.unit_number)}</h1>
      ${edit ? '<button class="secondary" id="ed">Edit</button>' : ""}</div>
    <div class="card"><dl>${rows.filter((r) => r[1] !== null && r[1] !== undefined && r[1] !== "")
      .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${k.startsWith("Odo") || k.startsWith("Engine") ? v : esc(v)}</dd>`).join("")}</dl></div>
    ${edit ? `<h2>Leaving the fleet?</h2>
      <div class="card"><p class="muted">Sold, scrapped or returned. The unit and its records are kept, not deleted.</p>
      <label for="why">Reason</label><input id="why" placeholder="e.g. Sold to dealer">
      <p><button class="secondary" id="ret">Mark as left fleet</button></p></div>` : ""}`;
  $("#back").onclick = () => go("units");
  if (edit) {
    $("#ed").onclick = () => SCREENS.unitForm(u);
    $("#ret").onclick = async () => {
      const reason = $("#why").value.trim();
      if (!reason) return toast("Enter a reason first.");
      if (!confirm(`Mark unit ${u.unit_number} as left the fleet?`)) return;
      try {
        await api(`/api/assets/${id}/retire`, { method: "POST", json: { reason } });
        toast("Unit marked as left the fleet."); go("units");
      } catch (e) { toast(e.message); }
    };
  }
};

SCREENS.unitForm = async (u) => {
  const v = u || { asset_type: "", owned_by_carrier: true };
  const f = (id, label, val, attrs = "") =>
    `<div><label for="${id}">${label}</label><input id="${id}" value="${esc(val ?? "")}" ${attrs}></div>`;
  view.innerHTML = `
    <button class="link" id="back">‹ ${u ? "Unit " + esc(u.unit_number) : "Units"}</button>
    <h1>${u ? "Edit unit " + esc(u.unit_number) : "Add a unit"}</h1>
    <div id="out"></div>
    <form id="f" class="card">
      <label for="asset_type">Type</label>
      <select id="asset_type" required>
        <option value="">Choose…</option>
        <option value="power_unit" ${v.asset_type === "power_unit" ? "selected" : ""}>Power unit (truck/tractor)</option>
        <option value="trailer" ${v.asset_type === "trailer" ? "selected" : ""}>Trailer</option>
      </select>
      ${f("unit_number", "Unit number", v.unit_number, "required maxlength=30")}
      ${f("vin", "VIN", v.vin, 'autocapitalize="characters" maxlength=24')}
      <div class="two">${f("model_year", "Year", v.model_year, 'inputmode="numeric"')}
        ${f("make", "Make", v.make)}</div>
      ${f("model", "Model", v.model)}
      <div class="two">${f("plate", "Plate", v.plate, 'autocapitalize="characters"')}
        ${f("plate_state", "Plate state", v.plate_state, 'maxlength=3 autocapitalize="characters"')}</div>
      <label for="owned">Who owns it?</label>
      <select id="owned">
        <option value="yes">The company</option>
        <option value="no" ${v.owned_by_carrier ? "" : "selected"}>Someone else (leased / furnished)</option>
      </select>
      <div id="fb" ${v.owned_by_carrier ? "hidden" : ""}>${f("furnished_by", "Owner's name", v.furnished_by)}</div>
      <div class="two">${f("odometer", "Odometer (miles)", v.odometer, 'inputmode="numeric"')}
        ${f("engine_hours", "Engine hours", v.engine_hours, 'inputmode="decimal"')}</div>
      <label for="notes">Notes</label><textarea id="notes" rows="2">${esc(v.notes || "")}</textarea>
      <p><button class="primary" style="width:100%">${u ? "Save changes" : "Add unit"}</button></p>
    </form>`;
  $("#back").onclick = () => (u ? SCREENS.unit(u.asset_id) : go("units"));
  $("#owned").onchange = () => ($("#fb").hidden = $("#owned").value === "yes");
  $("#f").onsubmit = async (ev) => {
    ev.preventDefault();
    const val = (id) => $("#" + id).value.trim() || null;
    const body = {};
    ["asset_type", "unit_number", "vin", "model_year", "make", "model", "plate",
     "plate_state", "odometer", "engine_hours", "notes"].forEach((k) => (body[k] = val(k)));
    body.owned_by_carrier = $("#owned").value === "yes";
    body.furnished_by = body.owned_by_carrier ? null : val("furnished_by");
    try {
      const r = u
        ? await api(`/api/assets/${u.asset_id}`, { method: "PATCH", json: body })
        : await api("/api/assets", { method: "POST", json: body });
      toast(u ? "Saved." : "Unit added.");
      if (r.warnings && r.warnings.length) toast("Saved. Check: " + r.warnings.join(" "));
      SCREENS.unit(r.unit.asset_id);
    } catch (e) { $("#out").innerHTML = errorHtml(e); window.scrollTo(0, 0); }
  };
};

SCREENS.importUnits = async () => {
  view.innerHTML = `
    <button class="link" id="back">‹ Units</button>
    <h1>Import the fleet list</h1>
    <div class="card">
      <p>Save your fleet spreadsheet as <b>CSV</b> (in Excel: File → Save As → CSV).
      One row per truck or trailer. It needs a <b>Unit</b> column and a <b>Type</b>
      column (truck or trailer). These are read if present: VIN, Year, Make, Model,
      Plate, State, Owner, Odometer, Engine hours, Notes.</p>
      <p class="muted">Nothing is saved until every row checks out.</p>
      <input type="file" id="file" accept=".csv,text/csv">
      <p><button class="primary" id="chk" disabled>Check file</button></p>
    </div>
    <div id="out"></div>`;
  $("#back").onclick = () => go("units");
  $("#file").onchange = () => ($("#chk").disabled = !$("#file").files.length);
  const send = async (commit) => {
    const fd = new FormData(); fd.append("file", $("#file").files[0]);
    return api(`/api/assets/import?commit=${commit}`, { method: "POST", body: fd });
  };
  $("#chk").onclick = async () => {
    try {
      const r = await send(false);
      const bad = r.rows.filter((x) => x.errors.length);
      const warn = r.rows.filter((x) => !x.errors.length && x.warnings.length);
      let html = msgBox(r.ok ? "ok" : "bad",
        r.ok ? `Ready: ${r.count} units (${r.power_units} power units, ${r.trailers} trailers).`
             : "This file can't be loaded yet.", r.problems);
      if (r.ignored_columns && r.ignored_columns.length)
        html += msgBox("warn", "These columns will be ignored: " + r.ignored_columns.join(", "));
      if (bad.length) html += `<h2>Rows to fix</h2>` + bad.map((x) =>
        `<div class="card"><b>Row ${x.row}</b> ${esc(x.unit_number || "")}${msgBox("bad", "", x.errors)}</div>`).join("");
      if (warn.length) html += `<h2>Worth a look (won't stop the import)</h2>` + warn.map((x) =>
        `<div class="card"><b>Row ${x.row}</b> ${esc(x.unit_number || "")}${msgBox("warn", "", x.warnings)}</div>`).join("");
      if (r.ok) html += `<p><button class="primary" id="go" style="width:100%">Load ${r.count} units</button></p>`;
      $("#out").innerHTML = html;
      if (r.ok) $("#go").onclick = async () => {
        $("#go").disabled = true;
        try {
          const done = await send(true);
          if (done.saved) { toast(`${done.saved} units loaded.`); go("units"); }
          else { $("#out").innerHTML = msgBox("bad", "Nothing was saved.", done.problems); }
        } catch (e) { $("#out").innerHTML = errorHtml(e); }
      };
    } catch (e) { $("#out").innerHTML = errorHtml(e); }
  };
};

// ---------------------------------------------------------------- people

const ROLE_LABEL = { mechanic: "Mechanic", shop_manager: "Shop manager",
  fleet_manager: "Fleet manager", admin: "Company admin" };

SCREENS.people = async () => {
  const r = await api("/api/users");
  view.innerHTML = `
    <h1>People</h1>
    ${r.users.map((u) => `<div class="card row"><span class="grow"><b>${esc(u.name)}</b><br>
      <span class="muted">${esc(u.email)}</span></span><span class="pill">${esc(u.role_label)}</span></div>`).join("")}
    ${r.may_add.length ? `<h2>Add a person</h2><div id="out"></div>
    <form id="f" class="card">
      <label for="n">Name</label><input id="n" required maxlength="80">
      <label for="e">Email (they sign in with this)</label><input id="e" type="email" required>
      <label for="r">Role</label><select id="r">${r.may_add.map((k) =>
        `<option value="${k}">${esc(ROLE_LABEL[k])}</option>`).join("")}</select>
      <label for="p">Starting password (8+ characters; give it to them in person)</label>
      <input id="p" type="text" required minlength="8" autocomplete="off">
      <p><button class="primary" style="width:100%">Add person</button></p>
    </form>` : ""}`;
  if (!r.may_add.length) return;
  $("#f").onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      await api("/api/users", { method: "POST", json: { name: $("#n").value,
        email: $("#e").value, role: $("#r").value, password: $("#p").value } });
      toast("Person added."); go("people");
    } catch (e) { $("#out").innerHTML = errorHtml(e); }
  };
};

// ---------------------------------------------------------------- change log

const ACTION_LABEL = { "org.created": "Company set up", "user.created": "Person added",
  "unit.created": "Unit added", "unit.edited": "Unit changed",
  "unit.retired": "Unit left fleet", "units.imported": "Fleet list imported" };

SCREENS.log = async () => {
  const [r, chk] = await Promise.all([api("/api/audit"), api("/api/audit/verify")]);
  view.innerHTML = `
    <h1>Change log</h1>
    ${chk.ok ? msgBox("ok", `Log checks out: ${chk.entries} entries, none altered.`)
             : msgBox("bad", `Log problem at entry ${chk.at_seq}: ${chk.why}`)}
    ${r.entries.map((e) => `<div class="card"><div class="row"><b class="grow">${esc(ACTION_LABEL[e.action] || e.action)}</b>
      <span class="muted">#${e.seq}</span></div>
      <div class="muted">${esc(e.actor_name)} (${esc(e.actor_role.replace("_", " "))}) · ${fmtDate(e.at)}</div>
      ${e.action === "unit.edited" ? `<div class="muted">${Object.keys(e.after || {})
        .filter((k) => !k.endsWith("_at") && !k.endsWith("_by") && k !== "unit_number_key")
        .map((k) => `${esc(k)}: ${esc(e.before[k])} → ${esc(e.after[k])}`).join("<br>")}</div>` : ""}
    </div>`).join("")}`;
};

// ---------------------------------------------------------------- Apex console

SCREENS.companies = async () => {
  const r = await api("/api/operator/orgs");
  r.orgs.forEach((o) => (S.orgNames[o.org_id] = o.name));
  view.innerHTML = `
    <h1>Customer companies</h1>
    ${r.orgs.map((o) => `<div class="card row"><span class="grow"><b>${esc(o.name)}</b><br>
      <span class="muted">${o.units} units · ${o.people} people</span></span></div>`).join("") ||
      '<div class="card muted">No companies yet.</div>'}
    <h2>Set up a new company</h2><div id="out"></div>
    <form id="f" class="card">
      <label for="cn">Company name</label><input id="cn" required>
      <label for="an">Their admin's name</label><input id="an" required>
      <label for="ae">Admin's email</label><input id="ae" type="email" required>
      <label for="ap">Admin's starting password (8+ characters)</label>
      <input id="ap" type="text" required minlength="8" autocomplete="off">
      <p><button class="primary" style="width:100%">Create company</button></p>
    </form>`;
  $("#f").onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      await api("/api/operator/orgs", { method: "POST", json: {
        company_name: $("#cn").value, admin_name: $("#an").value,
        admin_email: $("#ae").value, admin_password: $("#ap").value } });
      toast("Company created."); go("companies");
    } catch (e) { $("#out").innerHTML = errorHtml(e); }
  };
};

start();
