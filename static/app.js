const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n, cur = "EUR") => { try { return new Intl.NumberFormat(undefined, { style: "currency", currency: cur }).format(n); } catch { return `${cur} ${Number(n).toFixed(2)}`; } };
const date = (s) => s ? new Date(s).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
const fmtIban = (s) => (s || "").replace(/(.{4})/g, "$1 ").trim();

const STATUS = {
  received: "Received", ready_to_pay: "Ready to pay", needs_verification: "Verify by phone", on_hold: "On hold",
  verified: "Needs 2nd approval", approved: "Approved", paid: "Paid", blocked: "Blocked",
};
const LEVEL = { green: "Low risk", amber: "Check first", red: "High risk" };

let invoices = [], filter = "all";
const me = () => localStorage.getItem("paycheck.me") || "";

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: opts.body instanceof FormData ? {} : { "Content-Type": "application/json" }, ...opts });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : (data.detail?.[0]?.msg || `Error ${res.status}`));
  return data;
}

function toast(msg, error = false) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast" + (error ? " error" : ""); t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 3800);
}

/* ---------- Views ---------- */
function show(view) {
  $$(".view").forEach((v) => (v.hidden = v.id !== `view-${view}`));
  $$("nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  ({ queue: loadQueue, suppliers: loadSuppliers, fraud: loadFraud })[view]?.();
}
window.addEventListener("hashchange", () => show(location.hash.slice(1) || "queue"));

async function loadQueue() {
  const [stats, list] = await Promise.all([api("/api/stats"), api("/api/invoices")]);
  invoices = list;
  $("#kpis").innerHTML = `
    <div class="kpi"><div class="label">Invoices checked</div><div class="value">${stats.checked}</div></div>
    <div class="kpi"><div class="label">Awaiting decision</div><div class="value">${stats.open}</div></div>
    <div class="kpi"><div class="label">Blocked</div><div class="value">${stats.blocked}</div></div>
    <div class="kpi highlight"><div class="label">Money protected</div><div class="value">${money(stats.protected)}</div></div>`;
  renderQueue();
}

function renderQueue() {
  const rows = invoices.filter((i) => {
    if (filter === "all") return true;
    if (filter === "done") return ["paid", "blocked", "approved"].includes(i.status);
    return i.risk_level === filter && !["paid", "blocked", "approved"].includes(i.status);
  });
  $("#queueEmpty").hidden = rows.length > 0;
  $("#queueBody").innerHTML = rows.map((i) => `
    <tr class="clickable" data-id="${i.id}">
      <td class="strong">${esc(i.supplier_name)}</td>
      <td class="mono muted">${esc(i.invoice_number || "-")}</td>
      <td class="num strong">${money(i.amount, i.currency)}</td>
      <td>${i.risk_level ? `<span class="badge ${i.risk_level}">${LEVEL[i.risk_level]} · ${i.risk_score}</span>` : ""}</td>
      <td class="status">${STATUS[i.status] || esc(i.status)}</td>
      <td class="muted">${date(i.received_at)}</td>
    </tr>`).join("");
}

$("#filters").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  filter = b.dataset.f; $$("#filters button").forEach((x) => x.classList.toggle("active", x === b)); renderQueue();
});
$("#queueBody").addEventListener("click", (e) => { const tr = e.target.closest("tr[data-id]"); if (tr) openInvoice(tr.dataset.id); });

async function loadSuppliers() {
  const list = await api("/api/suppliers");
  $("#supplierBody").innerHTML = list.map((s) => `
    <tr><td class="strong">${esc(s.name)}</td><td>${esc(s.country)}</td><td class="mono">@${esc(s.email_domain)}</td>
    <td class="mono">${s.verified_iban ? esc(fmtIban(s.verified_iban)) : '<span class="badge amber">Not verified</span>'}</td>
    <td>${s.verified_phone ? esc(s.verified_phone) : '<span class="badge amber">Missing</span>'}</td><td class="num">${s.invoice_count}</td></tr>`).join("");
  $("#supplierNames").innerHTML = list.map((s) => `<option value="${esc(s.name)}">`).join("");
}

async function loadFraud() {
  const list = await api("/api/fraud-list");
  $("#fraudBody").innerHTML = list.length ? list.map((f) => `
    <tr><td class="mono strong">${esc(fmtIban(f.iban))}</td><td>${esc(f.reason)}</td><td class="muted">${date(f.reported_at)}</td></tr>`).join("")
    : `<tr><td colspan="3" class="empty">No reported accounts yet.</td></tr>`;
}

/* ---------- Invoice drawer ---------- */
function closeDrawer() { $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); $("#scrim").hidden = true; }
$("#scrim").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

async function openInvoice(id) {
  const inv = await api(`/api/invoices/${id}`);
  renderDrawer(inv);
  $("#scrim").hidden = false; $("#drawer").classList.add("open"); $("#drawer").setAttribute("aria-hidden", "false");
}

function headline(inv) {
  if (inv.status === "blocked") return ["Blocked", "This invoice will not be paid. The account was added to the fraud list."];
  if (inv.status === "paid") return ["Paid", "Payment completed after checks."];
  if (inv.status === "approved") return ["Approved", "Cleared for payment."];
  if (inv.status === "verified") return ["Verified by phone, needs a second approver", "High-risk invoices need two different people to sign off."];
  return {
    green: ["Looks safe to pay", "Nothing unusual found."],
    amber: ["Verify before paying", "Call the supplier on the number in your records to confirm."],
    red: ["Do not pay yet", "Strong signs of fraud. Verify by phone and get a second approval, or block it."],
  }[inv.risk_level] || ["Checking…", ""];
}

function renderDrawer(inv) {
  const [h, p] = headline(inv);
  const color = { green: "var(--green)", amber: "#f59e0b", red: "var(--red)" }[inv.risk_level];
  const real = inv.findings.filter((f) => f.check_name !== "ai");
  const aiMain = inv.findings.find((f) => f.check_name === "ai" && f.title.startsWith("AI analyst"));
  const aiFlags = inv.findings.filter((f) => f.check_name === "ai" && f.title === "AI red flag");
  const sup = inv.supplier;

  $("#drawerBody").innerHTML = `
    <div class="d-head">
      <div><div class="muted">${esc(inv.invoice_number || "No invoice number")} · received ${date(inv.received_at)}</div>
      <h2>${esc(inv.supplier_name)}</h2></div>
      <button class="icon-btn" id="closeDrawer" aria-label="Close">✕</button>
    </div>
    <div class="d-amount">${money(inv.amount, inv.currency)}</div>
    <span class="status">${STATUS[inv.status] || esc(inv.status)}</span>

    <div class="score ${inv.risk_level}">
      <div class="ring" style="--p:${inv.risk_score};--c:${color}"><span>${inv.risk_score}</span></div>
      <div><h3>${h}</h3><p>${p}</p></div>
    </div>

    <div class="section-title">AI analyst</div>
    <div class="ai-box">${aiMain ? `<b>${esc(aiMain.title.replace("AI analyst: ", "Recommends: "))}.</b> ${esc(aiMain.detail)}
      ${aiFlags.length ? `<ul>${aiFlags.map((f) => `<li>${esc(f.detail)}</li>`).join("")}</ul>` : ""}`
      : `<span class="muted">${esc(inv.ai_summary || "Not run.")}</span>`}</div>

    <div class="section-title">What we checked</div>
    ${real.map((f) => `<div class="finding"><span class="sev ${f.severity}" title="${f.severity}"></span>
      <div><div class="t">${esc(f.title)}<span class="tag">${esc(f.check_name)}</span></div><div class="d">${esc(f.detail)}</div></div></div>`).join("")}

    <div class="section-title">Payment details</div>
    <dl class="kv">
      <dt>Pay to (invoice)</dt><dd class="mono">${esc(fmtIban(inv.iban) || "-")}</dd>
      <dt>Verified account</dt><dd class="mono">${esc(fmtIban(sup?.verified_iban) || "None on file")}</dd>
      <dt>From</dt><dd>${esc(inv.sender_email || "-")}</dd>
      ${inv.reply_to ? `<dt>Reply-to</dt><dd>${esc(inv.reply_to)}</dd>` : ""}
      <dt>Call-back number</dt><dd>${esc(sup?.verified_phone || "None on file")}</dd>
    </dl>
    ${inv.email_body ? `<div class="section-title">Email</div><div class="email">${esc(inv.email_body)}</div>` : ""}

    <div class="section-title">Audit trail</div>
    <ul class="timeline">${inv.audit.map((a) => `<li><div><b>${esc(a.action.replaceAll("_", " "))}</b> by ${esc(a.actor)}${a.note ? ` · ${esc(a.note)}` : ""}</div><div class="when">${date(a.at)}</div></li>`).join("")}</ul>

    ${actions(inv)}`;

  $("#closeDrawer").onclick = closeDrawer;
  $$("[data-act]", $("#drawerBody")).forEach((b) => (b.onclick = () => act(inv, b.dataset.act, b)));
  const meInput = $("#actor"); if (meInput) meInput.oninput = () => localStorage.setItem("paycheck.me", meInput.value.trim());
}

function actions(inv) {
  const who = `<input id="actor" placeholder="Your name" value="${esc(me())}" aria-label="Your name">`;
  const block = `<button class="btn danger" data-act="block">Block &amp; report</button>`;
  const recheck = `<button class="btn ghost" data-act="recheck">Re-check</button>`;
  switch (inv.status) {
    case "ready_to_pay": return `<div class="actions">${who}<button class="btn success" data-act="approve">Approve</button>${block}${recheck}</div>`;
    case "needs_verification":
    case "on_hold":
      return `<div class="callout"><b>Call ${esc(inv.supplier?.verified_phone || "the supplier")}</b>. Use the number in your records, never one from this invoice or email. Ask them to confirm the amount and the bank account.</div>
        <div class="actions">${who}<input id="phone" placeholder="Number you called" aria-label="Number you called">
        <button class="btn primary" data-act="verify">Confirmed by phone</button>${block}${recheck}</div>`;
    case "verified": return `<div class="actions">${who}<button class="btn success" data-act="second-approve">Second approval</button>${block}</div>`;
    case "approved": return `<div class="actions">${who}<button class="btn primary" data-act="pay">Mark as paid</button>${block}</div>`;
    default: return "";
  }
}

async function act(inv, action, btn) {
  const actor = ($("#actor")?.value || "").trim();
  if (action !== "recheck" && !actor) { toast("Enter your name first, so the audit trail shows who decided.", true); $("#actor").focus(); return; }
  let note = null;
  if (action === "block") {
    note = prompt("Why are you blocking this invoice? (saved to the audit trail)", "Suspected fraud");
    if (note === null) return;
  }
  btn.disabled = true; const label = btn.innerHTML; btn.innerHTML = `<span class="spinner"></span>`;
  try {
    const path = action === "recheck" ? `/api/invoices/${inv.id}/recheck` : `/api/invoices/${inv.id}/${action}`;
    const body = action === "recheck" ? undefined : JSON.stringify({ actor, note, phone_used: $("#phone")?.value || null });
    const updated = await api(path, { method: "POST", body });
    renderDrawer(updated); loadQueue();
    toast({ approve: "Approved", verify: "Verification recorded", "second-approve": "Second approval recorded", pay: "Marked as paid", block: "Blocked and reported", recheck: "Re-checked" }[action]);
  } catch (e) { toast(e.message, true); btn.disabled = false; btn.innerHTML = label; }
}

/* ---------- New invoice ---------- */
let mode = "manual";
$("#newBtn").onclick = () => { $("#newError").hidden = true; loadSuppliers(); $("#newDialog").showModal(); };
$$(".seg button").forEach((b) => (b.onclick = () => {
  mode = b.dataset.mode; $$(".seg button").forEach((x) => x.classList.toggle("active", x === b));
  $$("#newForm .manual").forEach((el) => (el.hidden = mode !== "manual"));
  $$("#newForm .upload").forEach((el) => (el.hidden = mode !== "upload"));
}));

$("#newForm").addEventListener("submit", async (e) => {
  if (e.submitter?.value === "cancel") return;
  e.preventDefault();
  const f = new FormData(e.target), btn = $("#runCheck"), err = $("#newError");
  err.hidden = true; btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> Checking…`;
  try {
    let inv;
    if (mode === "upload") {
      if (!f.get("file")?.size) throw new Error("Choose a file to upload.");
      const up = new FormData();
      for (const k of ["file", "supplier_name", "sender_email", "reply_to", "email_body"]) if (f.get(k)) up.append(k, f.get(k));
      inv = await api("/api/invoices/upload", { method: "POST", body: up });
    } else {
      const body = Object.fromEntries([...f.entries()].filter(([k, v]) => k !== "file" && v !== ""));
      if (!body.amount) throw new Error("Enter the invoice amount.");
      body.amount = Number(body.amount);
      inv = await api("/api/invoices", { method: "POST", body: JSON.stringify(body) });
    }
    $("#newDialog").close(); e.target.reset(); location.hash = "queue"; await loadQueue(); openInvoice(inv.id);
  } catch (ex) { err.textContent = ex.message; err.hidden = false; }
  finally { btn.disabled = false; btn.textContent = "Run checks"; }
});

/* ---------- New supplier ---------- */
$("#newSupplierBtn").onclick = () => { $("#supplierError").hidden = true; $("#supplierDialog").showModal(); };
$("#supplierForm").addEventListener("submit", async (e) => {
  if (e.submitter?.value === "cancel") return;
  e.preventDefault();
  const body = Object.fromEntries([...new FormData(e.target).entries()].filter(([, v]) => v !== ""));
  try { await api("/api/suppliers", { method: "POST", body: JSON.stringify(body) }); $("#supplierDialog").close(); e.target.reset(); loadSuppliers(); toast("Supplier saved"); }
  catch (ex) { $("#supplierError").textContent = ex.message; $("#supplierError").hidden = false; }
});

/* ---------- Boot ---------- */
api("/api/status").then((s) => {
  const el = $("#aiStatus");
  el.className = "ai-pill " + (s.ai_enabled ? "on" : "off");
  el.textContent = s.ai_enabled ? `AI analyst on · ${s.model}` : "AI analyst off: add an Anthropic API key to enable";
});
show(location.hash.slice(1) || "queue");
