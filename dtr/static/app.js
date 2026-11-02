// DTR screens. Plain JavaScript, no build step.
// The server checks every permission; hiding a button here is only a
// convenience so people don't see things they can't use.
// Every word on screen comes from /static/locales/<lang>.json via t().
"use strict";

const S = { token: null, me: null, orgNames: {}, meta: null, lang: "en",
            dict: {}, en: {}, current: null };
const $ = (sel) => document.querySelector(sel);
const view = $("#view");
const LANGS = { en: "English", es: "Español", hi: "हिन्दी", ur: "اردو" };
const RTL = ["ur"];

const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ok */ } },
  del(k) { try { localStorage.removeItem(k); } catch (e) { /* ok */ } },
};
S.token = store.get("dtr_token");

// ---------------------------------------------------------------- words

function t(key, params) {
  let s = S.dict[key] ?? S.en[key] ?? key;
  if (params) for (const [k, v] of Object.entries(params)) s = s.split("{" + k + "}").join(v);
  return s;
}

async function loadLang(lang) {
  if (!LANGS[lang]) lang = "en";
  const get = async (l) => {
    if (window.DTR_LOCALES) return window.DTR_LOCALES[l] || {};
    const r = await fetch(`/static/locales/${l}.json`);
    return r.ok ? r.json() : {};
  };
  if (!Object.keys(S.en).length) S.en = await get("en");
  S.dict = lang === "en" ? S.en : await get(lang);
  S.lang = lang;
  store.set("dtr_lang", lang);
  document.documentElement.lang = lang;
  document.documentElement.dir = RTL.includes(lang) ? "rtl" : "ltr";
  $("#signout").textContent = t("app.sign_out");
}

function guessLang() {
  const saved = store.get("dtr_lang");
  if (saved && LANGS[saved]) return saved;
  const nav = (navigator.language || "en").slice(0, 2).toLowerCase();
  return LANGS[nav] ? nav : "en";
}

function langPicker(id) {
  return `<select id="${id}" class="lang" aria-label="${esc(t("app.language"))}">${
    Object.entries(LANGS).map(([k, v]) =>
      `<option value="${k}" ${k === S.lang ? "selected" : ""}>${v}</option>`).join("")}</select>`;
}

function wirePicker(id, after) {
  $("#" + id).onchange = async (ev) => {
    await loadLang(ev.target.value);
    if (S.token && S.me) {
      api("/api/me", { method: "PATCH", json: { language: S.lang } }).catch(() => {});
    }
    after();
  };
}

// ---------------------------------------------------------------- helpers

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function toast(text) {
  const el = $("#toast");
  el.textContent = text; el.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (el.hidden = true), 3200);
}

async function api(path, opts = {}) {
  const headers = { "X-Lang": S.lang, ...(opts.headers || {}) };
  if (S.token) headers.Authorization = "Bearer " + S.token;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.json);
  }
  const r = await (window.DTR_FETCH || fetch)(path, { ...opts, headers });
  if (opts.raw) {
    if (!r.ok) throw new Error(t("app.something_wrong"));
    return r;
  }
  let data = null;
  try { data = await r.json(); } catch (e) { /* empty body */ }
  if (r.status === 401 && path !== "/api/auth/login") { signOut(); }
  if (!r.ok) {
    const d = data && data.detail;
    const err = new Error(typeof d === "string" ? d : t("app.something_wrong"));
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
    return msgBox("bad", t("app.fix_first"), e.detail.errors) +
           msgBox("warn", "", e.detail.warnings);
  }
  return msgBox("bad", e.message);
}

const can = (p) => S.me && S.me.can.includes(p);
const role = () => S.me && S.me.user.role;
const num = (n) => (n == null ? "" : Number(n).toLocaleString(S.lang));
const money = (n) => new Intl.NumberFormat(S.lang, { style: "currency", currency: "USD" })
  .format(n || 0);
const when = (d) => {
  if (!d) return "";
  const s = String(d);
  const dt = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z");
  return dt.toLocaleString(S.lang, { dateStyle: "medium", timeStyle: "short" });
};
const day = (d) => (d ? new Date(d + "T12:00:00").toLocaleDateString(S.lang,
  { dateStyle: "medium" }) : "");
const val = (id) => { const el = $("#" + id); return el ? el.value.trim() || null : null; };
const options = (list, prefix, sel, blank) =>
  (blank ? `<option value="">${esc(t("app.choose"))}</option>` : "") +
  list.map((k) => `<option value="${esc(k)}" ${k === sel ? "selected" : ""}>${
    esc(t(prefix + k))}</option>`).join("");

// ---------------------------------------------------------------- sign-in

function showLogin(error) {
  $("#top").hidden = true; $("#tabs").hidden = true;
  view.innerHTML = `
    <div class="login card">
      <div class="row"><h1 class="grow">${esc(t("login.title"))}</h1>${langPicker("lp")}</div>
      ${window.DTR_PREVIEW ? msgBox("warn", t("app.preview_banner")) : ""}
      ${error ? msgBox("bad", error) : ""}
      <form id="f">
        <label for="em">${esc(t("login.email"))}</label>
        <input id="em" type="email" autocomplete="username" required dir="ltr">
        <label for="pw">${esc(t("login.password"))}</label>
        <input id="pw" type="password" autocomplete="current-password" required dir="ltr">
        <p><button class="primary wide">${esc(t("login.button"))}</button></p>
      </form>
      ${window.DTR_PREVIEW ? window.DTR_PREVIEW.loginHelp() : ""}
    </div>`;
  wirePicker("lp", () => showLogin(error));
  if (window.DTR_PREVIEW) window.DTR_PREVIEW.wireLogin();
  $("#f").onsubmit = async (ev) => {
    ev.preventDefault();
    await signIn($("#em").value, $("#pw").value);
  };
}

async function signIn(email, password) {
  try {
    const r = await api("/api/auth/login", { method: "POST", json: { email, password } });
    S.token = r.token;
    store.set("dtr_token", r.token);
    // The language picked on the sign-in screen wins, and is saved to the
    // person so it follows them to any phone.
    if (r.user.language !== S.lang) {
      await api("/api/me", { method: "PATCH", json: { language: S.lang } }).catch(() => {});
    }
    await start();
  } catch (e) { showLogin(e.message); }
}

function signOut() {
  S.token = null; S.me = null; S.orgNames = {}; S.meta = null;
  store.del("dtr_token");
  showLogin();
}
$("#signout").onclick = signOut;

// ---------------------------------------------------------------- tabs

const TABS = {
  platform_operator: ["companies", "units"],
  admin: ["workorders", "units", "people", "log"],
  fleet_manager: ["workorders", "units", "people"],
  shop_manager: ["workorders", "units", "people"],
  mechanic: ["workorders", "units"],
};
const SCREENS = {};

function go(name, arg) {
  S.current = [name, arg];
  document.querySelectorAll("#tabs button").forEach((b) =>
    b.classList.toggle("on", b.dataset.tab === name));
  window.scrollTo(0, 0);
  SCREENS[name](arg).catch((e) => { view.innerHTML = errorHtml(e); });
}

function drawChrome() {
  $("#org-name").textContent = S.me.org ? S.me.org.name : t("app.apex_console");
  $("#hdr-lang").innerHTML = langPicker("hl");
  wirePicker("hl", () => { drawChrome(); go(...S.current); });
  const tabs = TABS[role()] || [];
  const nav = $("#tabs");
  nav.innerHTML = tabs.map((k) => `<button data-tab="${k}">${esc(t("tab." + k))}</button>`).join("");
  nav.hidden = tabs.length < 2;
  nav.querySelectorAll("button").forEach((b) => (b.onclick = () => go(b.dataset.tab)));
}

async function start() {
  if (!S.token) return showLogin();
  try { S.me = await api("/api/me"); } catch (e) { return; }
  if (S.me.user.language && S.me.user.language !== S.lang) await loadLang(S.me.user.language);
  $("#top").hidden = false;
  if (role() === "platform_operator") {
    const r = await api("/api/operator/orgs");
    r.orgs.forEach((o) => (S.orgNames[o.org_id] = o.name));
  } else {
    S.meta = await api("/api/workorders/meta");
  }
  drawChrome();
  go((TABS[role()] || ["units"])[0]);
}

// ---------------------------------------------------------------- work orders

const PRIORITY_CLASS = { urgent: "p-urgent", high: "p-high", normal: "", low: "" };

SCREENS.workorders = async (state = {}) => {
  const filter = state.filter || (role() === "mechanic" ? "mine" : "active");
  const q = filter === "mine" ? "view=active&mine=true" : `view=${filter}`;
  const r = await api(`/api/workorders?${q}`);
  const chips = ["mine", "active", "complete", "closed", "cancelled"];
  view.innerHTML = `
    <div class="row"><h1 class="grow">${esc(t("wo.title"))}</h1>
      ${S.meta.may.create ? `<button class="primary" id="new">${esc(t("wo.new"))}</button>` : ""}</div>
    <div class="chips">${chips.map((c) => `<button data-f="${c}" class="${c === filter ? "on" : ""}">${
      esc(t("wo.filter." + c))}</button>`).join("")}</div>
    ${r.work_orders.map(woRow).join("") || `<div class="card muted">${esc(t("wo.none"))}</div>`}`;
  view.querySelectorAll("[data-f]").forEach((b) =>
    (b.onclick = () => go("workorders", { filter: b.dataset.f })));
  view.querySelectorAll("[data-wo]").forEach((b) =>
    (b.onclick = () => SCREENS.wo(b.dataset.wo)));
  if (S.meta.may.create) $("#new").onclick = () => SCREENS.newWo();
};

function woRow(w) {
  const techs = (w.assigned || []).map((a) => a.name).join(", ") || t("wo.unassigned");
  return `<button class="card list-item" data-wo="${esc(w.work_order_id)}">
    <span class="grow">
      <span class="row tight"><b>${esc(t("wo.number", { n: String(w.number).padStart(4, "0") }))}</b>
        <span class="pill">${esc(t("wo.unit_line", { unit: w.unit_number }))}</span>
        <span class="pill ${PRIORITY_CLASS[w.priority] || ""}">${esc(t("priority." + w.priority))}</span>
        <span class="pill st-${esc(w.status)}">${esc(t("status." + w.status))}</span></span>
      <span class="clip">${esc(w.complaint)}</span>
      <span class="muted">${esc(t("category." + w.category))} · ${esc(techs)}</span>
    </span><span class="muted chev">›</span></button>`;
}

SCREENS.newWo = async (preset = {}) => {
  const units = (await api("/api/assets")).units;
  const m = S.meta;
  view.innerHTML = `
    <button class="link" id="back">‹ ${esc(t("wo.title"))}</button>
    <h1>${esc(t("wo.new_title"))}</h1><div id="out"></div>
    <form id="f" class="card">
      <label for="asset_id">${esc(t("field.asset_id"))}</label>
      <select id="asset_id" required><option value="">${esc(t("app.choose"))}</option>${
        units.map((u) => `<option value="${esc(u.asset_id)}" ${u.asset_id === preset.asset_id ? "selected" : ""}>${
          esc(u.unit_number)} · ${esc(t("type." + u.asset_type))}${u.make ? " · " + esc(u.make) : ""}</option>`).join("")}</select>
      <label for="complaint">${esc(t("field.complaint"))} — ${esc(t("wo.complaint_help"))}</label>
      <textarea id="complaint" rows="3" required></textarea>
      <div class="two">
        <div><label for="priority">${esc(t("field.priority"))}</label>
          <select id="priority">${options(m.priorities, "priority.", "normal")}</select></div>
        <div><label for="category">${esc(t("field.category"))}</label>
          <select id="category">${options(m.categories, "category.", "other")}</select></div>
      </div>
      <label for="source">${esc(t("field.source"))}</label>
      <select id="source">${options(m.sources, "source.", "manual")}</select>
      <label for="source_ref">${esc(t("field.source_ref"))}</label><input id="source_ref">
      <div class="two">
        <div><label for="odometer">${esc(t("field.odometer"))}</label><input id="odometer" inputmode="numeric" dir="ltr"></div>
        <div><label for="engine_hours">${esc(t("field.engine_hours"))}</label><input id="engine_hours" inputmode="decimal" dir="ltr"></div>
      </div>
      <p><button class="primary wide">${esc(t("wo.create"))}</button></p>
    </form>`;
  $("#back").onclick = () => go("workorders");
  $("#f").onsubmit = async (ev) => {
    ev.preventDefault();
    const body = {};
    ["asset_id", "complaint", "priority", "category", "source", "source_ref",
     "odometer", "engine_hours"].forEach((k) => { const v = val(k); if (v !== null) body[k] = v; });
    try {
      const wo = await api("/api/workorders", { method: "POST", json: body });
      toast(t("wo.created")); SCREENS.wo(wo.work_order_id);
    } catch (e) { $("#out").innerHTML = errorHtml(e); window.scrollTo(0, 0); }
  };
};

SCREENS.wo = async (id) => {
  S.current = ["wo", id];
  const w = await api(`/api/workorders/${id}`);
  const m = S.meta || { may: {}, techs: [] };
  const active = ["open", "in_progress", "waiting_parts"].includes(w.status);
  const signed = ["complete", "closed"].includes(w.status);
  const me = S.me.user;
  const isSigner = w.signoff && w.signoff.user_id === me.user_id;
  const mayAmend = signed && (m.may.lead || isSigner);
  const mayLines = (active && m.may.work) || mayAmend;
  const no = String(w.number).padStart(4, "0");

  const textBlock = (f) => `<div class="field"><div class="lbl">${esc(t("field." + f))}</div>
    <div class="${w[f] ? "pre" : "muted"}">${esc(w[f] || t("wo.not_entered"))}</div></div>`;

  const lineList = (kind, render) => (w[kind] || []).map((l) => `
    <div class="line ${l.voided ? "voided" : ""}">
      <div class="grow">${render(l)}
        <div class="muted small">${esc(t("app.by_at", { name: l.by_name, when: when(l.at) }))}</div>
        ${l.amended ? `<div class="small warn-text">${esc(t("wo.amended_line", { reason: l.reason }))}</div>` : ""}
        ${l.voided ? `<div class="small bad-text">${esc(t("wo.voided", { reason: l.void_reason, name: l.voided_by }))}</div>` : ""}
      </div>
      ${!l.voided && mayLines && (m.may.lead || l.by === me.user_id)
        ? `<button class="link small" data-void="${kind}:${esc(l.line_id)}">${esc(t("wo.void"))}</button>` : ""}
    </div>`).join("") || `<div class="muted">${esc(t("app.none"))}</div>`;

  const reasonField = signed ? `<label for="REASON">${esc(t("wo.reason_signed"))}</label><input id="REASON" required>` : "";
  const rf = (id) => reasonField.split("REASON").join(id);

  view.innerHTML = `
    <button class="link" id="back">‹ ${esc(t("wo.title"))}</button>
    <div class="row"><h1 class="grow">${esc(t("wo.number", { n: no }))}</h1>
      <span class="pill st-${esc(w.status)}">${esc(t("status." + w.status))}</span></div>
    <div class="row tight" style="margin-bottom:8px">
      <button class="pill linkish" id="unit">${esc(t("wo.unit_line", { unit: w.unit_number }))} · ${esc(t("type." + w.asset_type))}</button>
      <span class="pill ${PRIORITY_CLASS[w.priority] || ""}">${esc(t("priority." + w.priority))}</span>
      <span class="pill">${esc(t("category." + w.category))}</span>
      <span class="pill">${esc(t("source." + w.source))}${w.source_ref ? " · " + esc(w.source_ref) : ""}</span>
    </div>
    <p class="muted small">${esc(t("wo.opened_by", { name: w.created_name, when: when(w.created_at) }))}</p>
    <div id="out"></div>

    <h2>${esc(t("wo.section.job"))}</h2>
    <div class="card">
      ${textBlock("complaint")}${textBlock("cause")}${textBlock("correction")}
      ${w.odometer != null || w.engine_hours != null ? `<div class="muted small">${
        w.odometer != null ? esc(t("field.odometer")) + ": " + num(w.odometer) : ""}${
        w.engine_hours != null ? " · " + esc(t("field.engine_hours")) + ": " + num(w.engine_hours) : ""}</div>` : ""}
      ${active && m.may.work ? `<p><button class="secondary" id="edit">${esc(t("wo.edit_job"))}</button></p>` : ""}
      <div id="editbox"></div>
    </div>

    ${active && m.may.work ? `<h2>${esc(t("wo.section.status"))}</h2><div class="row">${
      ({ open: ["in_progress", "waiting_parts"], in_progress: ["waiting_parts", "open"],
         waiting_parts: ["in_progress", "open"] }[w.status] || []).map((s) =>
        `<button class="secondary" data-move="${s}">${esc(t("wo.move." + s))}</button>`).join("")}</div>` : ""}

    <h2>${esc(t("wo.section.techs"))}</h2>
    <div class="card">
      <div>${esc((w.assigned || []).map((a) => a.name).join(", ") || t("wo.unassigned"))}</div>
      ${active && m.may.lead ? `<div class="checks">${m.techs.map((p) => `<label class="check"><input type="checkbox" value="${esc(p.user_id)}" ${
        (w.assigned || []).some((a) => a.user_id === p.user_id) ? "checked" : ""}> ${esc(p.name)}</label>`).join("")}</div>
        <button class="secondary" id="assign">${esc(t("wo.assign"))}</button>` : ""}
    </div>

    <h2>${esc(t("wo.section.labor"))} <span class="muted small">${esc(t("wo.total_hours", { n: num(w.totals.labor_hours) }))}</span></h2>
    <div class="card">
      ${lineList("labor", (l) => `<b>${esc(l.name)}</b> · ${esc(t("wo.hours_value", { n: num(l.hours) }))} · ${esc(day(l.date))}${
        l.note ? `<div>${esc(l.note)}</div>` : ""}`)}
      ${mayLines ? `<details><summary>${esc(t("wo.add_labor"))}</summary>
        <form id="fl">
          ${m.may.lead && m.techs.length ? `<label for="l_user">${esc(t("field.tech"))}</label>
            <select id="l_user">${m.techs.map((p) => `<option value="${esc(p.user_id)}" ${p.user_id === me.user_id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select>` : ""}
          <div class="two"><div><label for="l_hours">${esc(t("field.hours"))}</label><input id="l_hours" inputmode="decimal" required dir="ltr"></div>
          <div><label for="l_date">${esc(t("field.date"))}</label><input id="l_date" type="date" value="${new Date().toISOString().slice(0, 10)}"></div></div>
          <label for="l_note">${esc(t("field.note"))}</label><input id="l_note">
          ${rf("l_reason")}
          <p><button class="primary">${esc(t("wo.add_labor"))}</button></p></form></details>` : ""}
    </div>

    <h2>${esc(t("wo.section.parts"))} <span class="muted small">${esc(t("wo.parts_total", { amount: money(w.totals.parts_cost) }))}</span></h2>
    <div class="card">
      ${lineList("parts", (l) => `<b>${esc(l.part_number || "")}</b> ${esc(l.description || "")} · ${esc(t("field.qty"))} ${num(l.qty)}${
        l.unit_cost != null ? " × " + money(l.unit_cost) : ""}`)}
      ${mayLines ? `<details><summary>${esc(t("wo.add_part"))}</summary>
        <form id="fp">
          <div class="two"><div><label for="p_pn">${esc(t("field.part_number"))}</label><input id="p_pn" dir="ltr"></div>
          <div><label for="p_qty">${esc(t("field.qty"))}</label><input id="p_qty" inputmode="decimal" required dir="ltr"></div></div>
          <label for="p_desc">${esc(t("field.description"))}</label><input id="p_desc">
          <label for="p_cost">${esc(t("field.unit_cost"))}</label><input id="p_cost" inputmode="decimal" dir="ltr">
          ${rf("p_reason")}
          <p><button class="primary">${esc(t("wo.add_part"))}</button></p></form></details>` : ""}
    </div>

    <h2>${esc(t("wo.section.vendor"))} <span class="muted small">${esc(t("wo.vendor_total", { amount: money(w.totals.vendor_cost) }))}</span></h2>
    <div class="card">
      ${lineList("vendor", (l) => `<b>${esc(l.vendor)}</b>${l.invoice_number ? " · " + esc(l.invoice_number) : ""}${
        l.amount != null ? " · " + money(l.amount) : ""}${l.description ? `<div>${esc(l.description)}</div>` : ""}`)}
      ${mayLines ? `<details><summary>${esc(t("wo.add_vendor"))}</summary>
        <form id="fv">
          <label for="v_vendor">${esc(t("field.vendor"))}</label><input id="v_vendor" required>
          <div class="two"><div><label for="v_inv">${esc(t("field.invoice_number"))}</label><input id="v_inv" dir="ltr"></div>
          <div><label for="v_amt">${esc(t("field.amount"))}</label><input id="v_amt" inputmode="decimal" dir="ltr"></div></div>
          <label for="v_desc">${esc(t("field.description"))}</label><input id="v_desc">
          ${rf("v_reason")}
          <p><button class="primary">${esc(t("wo.add_vendor"))}</button></p></form></details>` : ""}
    </div>

    <h2>${esc(t("wo.section.photos"))}</h2>
    <div class="card">
      <div class="photos">${(w.photos || []).map((p) => `<figure><img data-photo="${esc(p.photo_id)}" alt="${esc(p.caption || "")}">
        ${p.caption ? `<figcaption>${esc(p.caption)}</figcaption>` : ""}</figure>`).join("") || `<span class="muted">${esc(t("app.none"))}</span>`}</div>
      ${m.may.note && w.status !== "cancelled" ? `<label class="secondary filebtn">${esc(t("wo.add_photo"))}
        <input type="file" id="photo" accept="image/*" capture="environment" hidden></label>` : ""}
    </div>

    <h2>${esc(t("wo.section.notes"))}</h2>
    <div class="card">
      ${(w.notes || []).map((n) => `<div class="line"><div class="grow"><div class="pre">${esc(n.text)}</div>
        <div class="muted small">${esc(t("app.by_at", { name: n.by_name, when: when(n.at) }))}</div></div></div>`).join("") ||
        `<div class="muted">${esc(t("app.none"))}</div>`}
      ${m.may.note ? `<form id="fn" class="row" style="margin-top:8px"><input id="n_text" class="grow" required>
        <button class="secondary">${esc(t("wo.add_note"))}</button></form>` : ""}
    </div>

    <h2>${esc(t("wo.section.signoff"))}</h2>
    <div class="card">
      ${w.signoff ? `<div class="msg ok">${esc(t("wo.signed_by", { name: w.signoff.name, when: when(w.signoff.at) }))}
          <div class="small">“${esc(w.signoff.statement)}”</div></div>` : ""}
      ${w.closed ? `<div class="msg ok">${esc(t("wo.closed_by", { name: w.closed.name, when: when(w.closed.at) }))}</div>` : ""}
      ${w.cancelled ? `<div class="msg bad">${esc(t("wo.cancelled_by", { name: w.cancelled.name, when: when(w.cancelled.at), reason: w.cancelled.reason }))}</div>` : ""}
      ${active && m.may.work ? `
        <p><b>${esc(t("wo.signoff_statement_title"))}</b></p>
        <blockquote>${esc(t("wo.signoff.statement"))}</blockquote>
        <label for="s_name">${esc(t("wo.signoff_type_name", { name: me.name }))}</label>
        <input id="s_name" autocomplete="off" autocapitalize="words" spellcheck="false">
        <p><button class="primary wide" id="sign">${esc(t("wo.sign"))}</button></p>` : ""}
      ${w.status === "complete" && m.may.lead ? `<p><button class="primary wide" id="close">${esc(t("wo.close"))}</button></p>` : ""}
      ${active && m.may.lead ? `<details><summary>${esc(t("wo.cancel_job"))}</summary>
        <p class="muted small">${esc(t("wo.cancel_help"))}</p>
        <label for="c_reason">${esc(t("wo.cancel_reason"))}</label><input id="c_reason">
        <p><button class="secondary" id="cancel">${esc(t("wo.cancel_job"))}</button></p></details>` : ""}
    </div>

    ${(w.amendments || []).length || mayAmend ? `<h2>${esc(t("wo.section.amendments"))}</h2><div class="card">
      ${(w.amendments || []).map((a) => `<div class="line"><div class="grow small">${esc(t("wo.amendment_line", {
        field: t("field." + a.field), before: a.before ?? "", after: a.after ?? "", reason: a.reason,
        name: a.by_name, when: when(a.at) }))}</div></div>`).join("")}
      ${mayAmend ? `<details><summary>${esc(t("wo.amend_title"))}</summary>
        <p class="muted small">${esc(t("wo.amend_help"))}</p>
        <label for="a_field">${esc(t("wo.amend_field"))}</label>
        <select id="a_field">${["complaint", "cause", "correction", "odometer", "engine_hours"].map((f) =>
          `<option value="${f}">${esc(t("field." + f))}</option>`).join("")}</select>
        <label for="a_value">${esc(t("wo.amend_value"))}</label><textarea id="a_value" rows="2"></textarea>
        <label for="a_reason">${esc(t("field.reason"))}</label><input id="a_reason">
        <p><button class="secondary" id="amend">${esc(t("wo.amend"))}</button></p></details>` : ""}
    </div>` : ""}

    <h2>${esc(t("wo.section.history"))}</h2>
    <div class="card small">${(w.history || []).map((h) => `<div>${esc(t("wo.history_line", {
      to: t("status." + h.to), name: h.by_name, when: when(h.at) }))}</div>`).join("")}</div>`;

  // --- wiring
  const reload = () => SCREENS.wo(id);
  const act = async (path, body, okMsg) => {
    try {
      const r = await api(`/api/workorders/${id}/${path}`, { method: "POST", json: body });
      if (okMsg) toast(r.warnings && r.warnings.length ? okMsg + " " + r.warnings.join(" ") : okMsg);
      reload();
    } catch (e) { $("#out").innerHTML = errorHtml(e); window.scrollTo(0, 0); }
  };
  $("#back").onclick = () => go("workorders");
  $("#unit").onclick = () => SCREENS.unit(w.asset_id);
  view.querySelectorAll("[data-move]").forEach((b) =>
    (b.onclick = () => act("status", { status: b.dataset.move })));
  if ($("#assign")) $("#assign").onclick = () => act("assign", { user_ids:
    [...view.querySelectorAll(".checks input:checked")].map((c) => c.value) }, t("wo.assigned_saved"));
  if ($("#fl")) $("#fl").onsubmit = (ev) => { ev.preventDefault(); act("labor", {
    user_id: val("l_user") || undefined, hours: val("l_hours"), date: val("l_date"),
    note: val("l_note"), reason: val("l_reason") }); };
  if ($("#fp")) $("#fp").onsubmit = (ev) => { ev.preventDefault(); act("parts", {
    part_number: val("p_pn"), description: val("p_desc"), qty: val("p_qty"),
    unit_cost: val("p_cost"), reason: val("p_reason") }); };
  if ($("#fv")) $("#fv").onsubmit = (ev) => { ev.preventDefault(); act("vendor", {
    vendor: val("v_vendor"), invoice_number: val("v_inv"), amount: val("v_amt"),
    description: val("v_desc"), reason: val("v_reason") }); };
  if ($("#fn")) $("#fn").onsubmit = (ev) => { ev.preventDefault(); act("notes", { text: val("n_text") }); };
  // Voiding asks for the reason right on the line, not in a pop-up.
  view.querySelectorAll("[data-void]").forEach((b) => (b.onclick = () => {
    const [kind, line_id] = b.dataset.void.split(":");
    const box = document.createElement("form");
    box.className = "voidbox";
    box.innerHTML = `<label for="vr_${line_id}">${esc(t("wo.void_reason"))}</label>
      <div class="row"><input id="vr_${line_id}" class="grow" required>
      <button class="secondary">${esc(t("wo.void"))}</button></div>`;
    b.closest(".line").after(box);
    b.remove();
    box.querySelector("input").focus();
    box.onsubmit = (ev) => { ev.preventDefault();
      act("void", { kind, line_id, reason: box.querySelector("input").value }); };
  }));
  if ($("#sign")) $("#sign").onclick = () => act("complete", { typed_name: $("#s_name").value }, t("wo.signed_ok"));
  if ($("#close")) $("#close").onclick = () => act("close", {}, t("wo.closed_ok"));
  if ($("#cancel")) $("#cancel").onclick = () =>
    act("cancel", { reason: $("#c_reason").value }, t("wo.cancelled_ok"));
  if ($("#amend")) $("#amend").onclick = () => act("amend", { field: $("#a_field").value,
    value: $("#a_value").value, reason: $("#a_reason").value }, t("wo.amended_ok"));
  if ($("#edit")) $("#edit").onclick = () => {
    $("#edit").hidden = true;
    $("#editbox").innerHTML = `<form id="fe">
      ${["complaint", "cause", "correction"].map((f) => `<label for="e_${f}">${esc(t("field." + f))}</label>
        <textarea id="e_${f}" rows="3">${esc(w[f] || "")}</textarea>`).join("")}
      <div class="two"><div><label for="e_priority">${esc(t("field.priority"))}</label>
        <select id="e_priority">${options(m.priorities, "priority.", w.priority)}</select></div>
        <div><label for="e_category">${esc(t("field.category"))}</label>
        <select id="e_category">${options(m.categories, "category.", w.category)}</select></div></div>
      <div class="two"><div><label for="e_odometer">${esc(t("field.odometer"))}</label>
        <input id="e_odometer" value="${esc(w.odometer ?? "")}" inputmode="numeric" dir="ltr"></div>
        <div><label for="e_engine_hours">${esc(t("field.engine_hours"))}</label>
        <input id="e_engine_hours" value="${esc(w.engine_hours ?? "")}" inputmode="decimal" dir="ltr"></div></div>
      <p class="row"><button class="primary">${esc(t("app.save"))}</button>
        <button type="button" class="secondary" id="e_cancel">${esc(t("app.cancel"))}</button></p></form>`;
    $("#e_cancel").onclick = reload;
    $("#fe").onsubmit = async (ev) => {
      ev.preventDefault();
      const body = {};
      ["complaint", "cause", "correction", "priority", "category", "odometer", "engine_hours"]
        .forEach((f) => (body[f] = val("e_" + f)));
      try {
        await api(`/api/workorders/${id}`, { method: "PATCH", json: body });
        toast(t("app.saved")); reload();
      } catch (e) { $("#out").innerHTML = errorHtml(e); window.scrollTo(0, 0); }
    };
  };
  if ($("#photo")) $("#photo").onchange = async (ev) => {
    const file = ev.target.files[0];
    if (!file) return;
    toast(t("wo.uploading"));
    try {
      const blob = await shrink(file);
      const fd = new FormData();
      fd.append("file", blob, "photo.jpg");
      fd.append("caption", "");
      await api(`/api/workorders/${id}/photos`, { method: "POST", body: fd });
      toast(t("wo.photo_added")); reload();
    } catch (e) { $("#out").innerHTML = errorHtml(e); }
  };
  view.querySelectorAll("img[data-photo]").forEach(async (img) => {
    try {
      const r = await api(`/api/workorders/${id}/photos/${img.dataset.photo}`, { raw: true });
      img.src = URL.createObjectURL(await r.blob());
    } catch (e) { /* leave blank */ }
  });
};

// Phone photos are big. Shrink to 1600 px on the long side as JPEG.
async function shrink(file) {
  const img = await new Promise((ok, bad) => {
    const i = new Image(); i.onload = () => ok(i); i.onerror = bad;
    i.src = URL.createObjectURL(file);
  });
  const scale = Math.min(1, 1600 / Math.max(img.width, img.height));
  const c = document.createElement("canvas");
  c.width = Math.round(img.width * scale); c.height = Math.round(img.height * scale);
  c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
  return new Promise((ok) => c.toBlob(ok, "image/jpeg", 0.82));
}

// ---------------------------------------------------------------- units

SCREENS.units = async (state = {}) => {
  const q = state.q || "", type = state.type || "", status = state.status || "active";
  const r = await api(`/api/assets?q=${encodeURIComponent(q)}&type=${type}&status=${status}`);
  const edit = can("edit_units"), imp = can("import_units");
  view.innerHTML = `
    <div class="row"><h1 class="grow">${esc(t("units.title"))}</h1>
      ${imp ? `<button class="secondary" id="imp">${esc(t("units.import"))}</button>` : ""}
      ${edit ? `<button class="primary" id="add">${esc(t("units.add"))}</button>` : ""}
    </div>
    <div class="row" style="margin-bottom:10px">
      <input id="q" class="grow" placeholder="${esc(t("units.search"))}" value="${esc(q)}">
      <select id="type" class="auto">
        <option value="">${esc(t("units.all"))}</option>
        <option value="power_unit" ${type === "power_unit" ? "selected" : ""}>${esc(t("units.power_units"))}</option>
        <option value="trailer" ${type === "trailer" ? "selected" : ""}>${esc(t("units.trailers"))}</option>
      </select>
      <select id="status" class="auto">
        <option value="active">${esc(t("units.in_fleet"))}</option>
        <option value="retired" ${status === "retired" ? "selected" : ""}>${esc(t("units.left_fleet"))}</option>
      </select>
    </div>
    <p class="muted">${esc(t("units.count", { n: num(r.units.length) }))}</p>
    <div id="list">${r.units.map(unitRow).join("") ||
      `<div class="card muted">${esc(t("units.none"))} ${imp ? esc(t("units.none_import")) : ""}</div>`}</div>`;
  const reload = () => go("units", { q: $("#q").value, type: $("#type").value, status: $("#status").value });
  let tm; $("#q").oninput = () => { clearTimeout(tm); tm = setTimeout(reload, 350); };
  $("#type").onchange = reload; $("#status").onchange = reload;
  if (edit) $("#add").onclick = () => SCREENS.unitForm();
  if (imp) $("#imp").onclick = () => SCREENS.importUnits();
  view.querySelectorAll("[data-id]").forEach((b) => (b.onclick = () => SCREENS.unit(b.dataset.id)));
};

function unitRow(u) {
  const sub = [u.model_year, u.make, u.model].filter(Boolean).join(" ");
  const org = S.orgNames[u.org_id] ? ` · ${esc(S.orgNames[u.org_id])}` : "";
  return `<button class="card list-item" data-id="${esc(u.asset_id)}">
    <span class="grow"><span class="big">${esc(u.unit_number)}</span>
      <span class="pill">${esc(t("type." + u.asset_type))}</span><br>
      <span class="muted">${esc(sub) || esc(t("units.no_make_year"))}${org}</span></span>
    <span class="muted chev">›</span></button>`;
}

SCREENS.unit = async (id) => {
  S.current = ["unit", id];
  const u = await api(`/api/assets/${id}`);
  const edit = can("edit_units") && u.status === "active";
  const rows = [
    [t("field.asset_type"), esc(t("type." + u.asset_type))],
    [t("field.vin"), `<span dir="ltr">${esc(u.vin || t("units.vin_missing"))}</span>`],
    [t("field.model_year"), esc(u.model_year)], [t("field.make"), esc(u.make)],
    [t("field.model"), esc(u.model)],
    [t("field.plate"), esc([u.plate, u.plate_state].filter(Boolean).join(" "))],
    [t("field.owner"), esc(u.owned_by_carrier ? t("units.company_owned")
      : t("units.furnished_by", { name: u.furnished_by }))],
    [t("field.odometer"), u.odometer != null ? esc(t("units.odometer_value",
      { n: num(u.odometer), name: u.odometer_by, when: when(u.odometer_at) })) : ""],
    [t("field.engine_hours"), u.engine_hours != null ? esc(t("units.hours_value",
      { n: num(u.engine_hours), name: u.engine_hours_by, when: when(u.engine_hours_at) })) : ""],
    [t("field.notes"), esc(u.notes)],
  ];
  if (S.orgNames[u.org_id]) rows.unshift([t("units.company"), esc(S.orgNames[u.org_id])]);
  if (u.status === "retired") rows.push([t("units.left_on"), esc(`${when(u.retired_at)}: ${u.retired_reason}`)]);
  const jobs = role() === "platform_operator" ? null
    : (await api(`/api/workorders?view=all&asset_id=${id}`)).work_orders;
  view.innerHTML = `
    <button class="link" id="back">‹ ${esc(t("units.title"))}</button>
    <div class="row"><h1 class="grow">${esc(t("units.unit", { unit: u.unit_number }))}</h1>
      ${edit ? `<button class="secondary" id="ed">${esc(t("units.edit"))}</button>` : ""}</div>
    <div class="card"><dl>${rows.filter((r) => r[1]).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl></div>
    ${jobs ? `<div class="row"><h2 class="grow">${esc(t("units.work_history"))}</h2>
      ${S.meta && S.meta.may.create && u.status === "active" ? `<button class="secondary" id="nwo">${esc(t("wo.new"))}</button>` : ""}</div>
      ${jobs.map(woRow).join("") || `<div class="card muted">${esc(t("wo.none"))}</div>`}` : ""}
    ${edit ? `<h2>${esc(t("units.leaving_title"))}</h2>
      <div class="card"><p class="muted">${esc(t("units.leaving_help"))}</p>
      <label for="why">${esc(t("field.reason"))}</label><input id="why" placeholder="${esc(t("units.leaving_placeholder"))}">
      <p><button class="secondary" id="ret">${esc(t("units.leaving_button"))}</button></p></div>` : ""}`;
  $("#back").onclick = () => go("units");
  view.querySelectorAll("[data-wo]").forEach((b) => (b.onclick = () => SCREENS.wo(b.dataset.wo)));
  if ($("#nwo")) $("#nwo").onclick = () => SCREENS.newWo({ asset_id: id });
  if (edit) {
    $("#ed").onclick = () => SCREENS.unitForm(u);
    $("#ret").onclick = async () => {
      const reason = $("#why").value.trim();
      if (!reason) return toast(t("units.reason_first"));
      try {
        await api(`/api/assets/${id}/retire`, { method: "POST", json: { reason } });
        toast(t("units.marked_left")); go("units");
      } catch (e) { toast(e.message); }
    };
  }
};

SCREENS.unitForm = async (u) => {
  const v = u || { asset_type: "", owned_by_carrier: true };
  const f = (id, label, value, attrs = "") =>
    `<div><label for="${id}">${esc(label)}</label><input id="${id}" value="${esc(value ?? "")}" ${attrs}></div>`;
  view.innerHTML = `
    <button class="link" id="back">‹ ${esc(u ? t("units.unit", { unit: u.unit_number }) : t("units.title"))}</button>
    <h1>${esc(u ? t("units.edit_title", { unit: u.unit_number }) : t("units.add_title"))}</h1>
    <div id="out"></div>
    <form id="f" class="card">
      <label for="asset_type">${esc(t("field.asset_type"))}</label>
      <select id="asset_type" required>
        <option value="">${esc(t("app.choose"))}</option>
        <option value="power_unit" ${v.asset_type === "power_unit" ? "selected" : ""}>${esc(t("type.power_unit_long"))}</option>
        <option value="trailer" ${v.asset_type === "trailer" ? "selected" : ""}>${esc(t("type.trailer"))}</option>
      </select>
      ${f("unit_number", t("field.unit_number"), v.unit_number, 'required maxlength=30 dir="ltr"')}
      ${f("vin", t("field.vin"), v.vin, 'autocapitalize="characters" maxlength=24 dir="ltr"')}
      <div class="two">${f("model_year", t("field.model_year"), v.model_year, 'inputmode="numeric" dir="ltr"')}
        ${f("make", t("field.make"), v.make)}</div>
      ${f("model", t("field.model"), v.model)}
      <div class="two">${f("plate", t("field.plate"), v.plate, 'autocapitalize="characters" dir="ltr"')}
        ${f("plate_state", t("field.plate_state"), v.plate_state, 'maxlength=3 autocapitalize="characters" dir="ltr"')}</div>
      <label for="owned">${esc(t("field.owner"))}</label>
      <select id="owned">
        <option value="yes">${esc(t("units.owned_by_company"))}</option>
        <option value="no" ${v.owned_by_carrier ? "" : "selected"}>${esc(t("units.owned_by_other"))}</option>
      </select>
      <div id="fb" ${v.owned_by_carrier ? "hidden" : ""}>${f("furnished_by", t("field.furnished_by"), v.furnished_by)}</div>
      <div class="two">${f("odometer", t("units.odometer_miles"), v.odometer, 'inputmode="numeric" dir="ltr"')}
        ${f("engine_hours", t("field.engine_hours"), v.engine_hours, 'inputmode="decimal" dir="ltr"')}</div>
      <label for="notes">${esc(t("field.notes"))}</label><textarea id="notes" rows="2">${esc(v.notes || "")}</textarea>
      <p><button class="primary wide">${esc(u ? t("units.save_changes") : t("units.add"))}</button></p>
    </form>`;
  $("#back").onclick = () => (u ? SCREENS.unit(u.asset_id) : go("units"));
  $("#owned").onchange = () => ($("#fb").hidden = $("#owned").value === "yes");
  $("#f").onsubmit = async (ev) => {
    ev.preventDefault();
    const body = {};
    ["asset_type", "unit_number", "vin", "model_year", "make", "model", "plate",
     "plate_state", "odometer", "engine_hours", "notes"].forEach((k) => (body[k] = val(k)));
    body.owned_by_carrier = $("#owned").value === "yes";
    body.furnished_by = body.owned_by_carrier ? null : val("furnished_by");
    try {
      const r = u
        ? await api(`/api/assets/${u.asset_id}`, { method: "PATCH", json: body })
        : await api("/api/assets", { method: "POST", json: body });
      const w = r.warnings && r.warnings.length ? " " + t("app.check_these") + " " + r.warnings.join(" ") : "";
      toast((u ? t("app.saved") : t("units.added")) + w);
      SCREENS.unit(r.unit.asset_id);
    } catch (e) { $("#out").innerHTML = errorHtml(e); window.scrollTo(0, 0); }
  };
};

SCREENS.importUnits = async () => {
  view.innerHTML = `
    <button class="link" id="back">‹ ${esc(t("units.title"))}</button>
    <h1>${esc(t("import.title"))}</h1>
    <div class="card">
      <p>${esc(t("import.help"))}</p>
      <p class="muted">${esc(t("import.nothing_saved_until"))}</p>
      <input type="file" id="file" accept=".csv,text/csv">
      <p><button class="primary" id="chk" disabled>${esc(t("import.check"))}</button></p>
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
        r.ok ? t("import.ready", { n: r.count, p: r.power_units, t: r.trailers })
             : t("import.cant_load"), r.problems);
      if (r.ignored_columns && r.ignored_columns.length)
        html += msgBox("warn", t("import.ignored", { cols: r.ignored_columns.join(", ") }));
      if (bad.length) html += `<h2>${esc(t("import.rows_to_fix"))}</h2>` + bad.map((x) =>
        `<div class="card"><b>${esc(t("import.row", { n: x.row }))}</b> ${esc(x.unit_number || "")}${msgBox("bad", "", x.errors)}</div>`).join("");
      if (warn.length) html += `<h2>${esc(t("import.rows_to_look"))}</h2>` + warn.map((x) =>
        `<div class="card"><b>${esc(t("import.row", { n: x.row }))}</b> ${esc(x.unit_number || "")}${msgBox("warn", "", x.warnings)}</div>`).join("");
      if (r.ok) html += `<p><button class="primary wide" id="go">${esc(t("import.load", { n: r.count }))}</button></p>`;
      $("#out").innerHTML = html;
      if (r.ok) $("#go").onclick = async () => {
        $("#go").disabled = true;
        try {
          const done = await send(true);
          if (done.saved) { toast(t("import.loaded", { n: done.saved })); go("units"); }
          else { $("#out").innerHTML = msgBox("bad", t("import.nothing_saved"), done.problems); }
        } catch (e) { $("#out").innerHTML = errorHtml(e); }
      };
    } catch (e) { $("#out").innerHTML = errorHtml(e); }
  };
};

// ---------------------------------------------------------------- people

SCREENS.people = async () => {
  const r = await api("/api/users");
  view.innerHTML = `
    <h1>${esc(t("people.title"))}</h1>
    ${r.users.map((u) => `<div class="card row"><span class="grow"><b>${esc(u.name)}</b><br>
      <span class="muted" dir="ltr">${esc(u.email)}</span></span><span class="pill">${esc(t("role." + u.role))}</span></div>`).join("")}
    ${r.may_add.length ? `<h2>${esc(t("people.add_title"))}</h2><div id="out"></div>
    <form id="f" class="card">
      <label for="n">${esc(t("field.name"))}</label><input id="n" required maxlength="80">
      <label for="e">${esc(t("people.email_help"))}</label><input id="e" type="email" required dir="ltr">
      <label for="r">${esc(t("field.role"))}</label><select id="r">${options(r.may_add, "role.", r.may_add[0])}</select>
      <label for="p">${esc(t("people.password_help"))}</label>
      <input id="p" type="text" required minlength="8" autocomplete="off" dir="ltr">
      <p><button class="primary wide">${esc(t("people.add"))}</button></p>
    </form>` : ""}`;
  if (!r.may_add.length) return;
  $("#f").onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      await api("/api/users", { method: "POST", json: { name: $("#n").value,
        email: $("#e").value, role: $("#r").value, password: $("#p").value, language: S.lang } });
      toast(t("people.added"));
      S.meta = await api("/api/workorders/meta");
      go("people");
    } catch (e) { $("#out").innerHTML = errorHtml(e); }
  };
};

// ---------------------------------------------------------------- change log

SCREENS.log = async () => {
  const [r, chk] = await Promise.all([api("/api/audit"), api("/api/audit/verify")]);
  view.innerHTML = `
    <h1>${esc(t("log.title"))}</h1>
    ${chk.ok ? msgBox("ok", t("log.ok", { n: chk.entries }))
             : msgBox("bad", t("log.bad", { seq: chk.at_seq, why: chk.why }))}
    ${r.entries.map((e) => {
      const changed = e.action.endsWith(".edited") || e.action === "wo.amended"
        ? Object.keys(e.after || {}).filter((k) => !/_at$|_by$|_key$|^updated_at$|^reason$/.test(k))
          .map((k) => `${esc(t("field." + k))}: ${esc(e.before ? e.before[k] : "")} → ${esc(e.after[k])}`).join("<br>")
        : "";
      return `<div class="card"><div class="row"><b class="grow">${esc(t("log.action." + e.action))}</b>
        <span class="muted">#${e.seq}</span></div>
        <div class="muted small">${esc(e.actor_name)} (${esc(t("role." + e.actor_role))}) · ${esc(when(e.at))}</div>
        ${changed ? `<div class="muted small">${changed}</div>` : ""}</div>`;
    }).join("")}`;
};

// ---------------------------------------------------------------- Apex console

SCREENS.companies = async () => {
  const r = await api("/api/operator/orgs");
  r.orgs.forEach((o) => (S.orgNames[o.org_id] = o.name));
  view.innerHTML = `
    <h1>${esc(t("console.title"))}</h1>
    ${r.orgs.map((o) => `<div class="card row"><span class="grow"><b>${esc(o.name)}</b><br>
      <span class="muted">${esc(t("console.counts", { units: num(o.units), people: num(o.people) }))}</span></span></div>`).join("") ||
      `<div class="card muted">${esc(t("console.none"))}</div>`}
    <h2>${esc(t("console.new_title"))}</h2><div id="out"></div>
    <form id="f" class="card">
      <label for="cn">${esc(t("field.company_name"))}</label><input id="cn" required>
      <label for="an">${esc(t("field.admin_name"))}</label><input id="an" required>
      <label for="ae">${esc(t("field.admin_email"))}</label><input id="ae" type="email" required dir="ltr">
      <label for="ap">${esc(t("field.admin_password"))}</label>
      <input id="ap" type="text" required minlength="8" autocomplete="off" dir="ltr">
      <p><button class="primary wide">${esc(t("console.create"))}</button></p>
    </form>`;
  $("#f").onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      await api("/api/operator/orgs", { method: "POST", json: {
        company_name: $("#cn").value, admin_name: $("#an").value,
        admin_email: $("#ae").value, admin_password: $("#ap").value } });
      toast(t("console.created")); go("companies");
    } catch (e) { $("#out").innerHTML = errorHtml(e); }
  };
};

loadLang(guessLang()).then(start);
