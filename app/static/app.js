"use strict";

// ------------------------------------------------------------------ state
let S = { ingredients: [], items: [], sales: [], purchase_orders: [], units: [] };
const ticket = {};            // item_id -> qty
const procQty = {};           // ingredient_id -> packages override
let editingItem = null;       // { id?, recipe: [{ingredient_id, qty}], image }
let editingIng = null;
let pickerCat = "";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (v, d = 2) => (v < 0 ? "-$" : "$") + Math.abs(v || 0).toFixed(d);
const num = (v) => (Math.round((v || 0) * 100) / 100).toLocaleString();
const pct = (v) => ((v || 0) * 100).toFixed(1) + "%";
const ingById = (id) => S.ingredients.find((i) => i.id === id);
const itemById = (id) => S.items.find((i) => i.id === id);
const unique = (arr) => [...new Set(arr.filter(Boolean))].sort();

function toast(msg, bad = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show" + (bad ? " bad" : "");
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.className = ""), 3500);
}

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ error: res.statusText }));
  if (!res.ok) throw new Error(data.error || res.statusText);
  if (data.state) { S = data.state; render(); }
  (data.warnings || []).forEach((w) => toast(w, true));
  return data;
}

const readFile = (file) => new Promise((ok, fail) => {
  const r = new FileReader();
  r.onload = () => ok(r.result);
  r.onerror = fail;
  r.readAsDataURL(file);
});

function thumb(item, cls = "thumb") {
  return item.image
    ? `<img class="${cls}" src="/images/${encodeURIComponent(item.image)}" alt="">`
    : `<div class="${cls} emoji">${esc(item.emoji || "🥤")}</div>`;
}

// ------------------------------------------------------------------ tabs
$$("#tabs button").forEach((b) => b.addEventListener("click", () => {
  $$("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + b.dataset.tab));
  location.hash = b.dataset.tab;
}));
if (location.hash) $(`#tabs button[data-tab="${location.hash.slice(1)}"]`)?.click();

// ------------------------------------------------------------------ render
function render() {
  renderLists();
  renderDashboard();
  renderMenu();
  renderIngredients();
  renderSell();
  renderProcurement();
  if ($("#item-dialog").open) renderBuilder();
}

function renderLists() {
  const fill = (sel, values) => ($(sel).innerHTML = values.map((v) => `<option value="${esc(v)}">`).join(""));
  fill("#item-categories", unique(S.items.map((i) => i.category)));
  fill("#ing-categories", unique(S.ingredients.map((i) => i.category)));
  fill("#suppliers", unique(S.ingredients.map((i) => i.supplier)));
  const opts = (sel, values) => {
    const cur = $(sel).value;
    $(sel).innerHTML = `<option value="">All categories</option>` + values.map((v) => `<option>${esc(v)}</option>`).join("");
    $(sel).value = values.includes(cur) ? cur : "";
  };
  opts("#menu-category", unique(S.items.map((i) => i.category)));
  opts("#ing-category", unique(S.ingredients.map((i) => i.category)));
  $("#unit-select").innerHTML = S.units.map((u) => `<option>${esc(u)}</option>`).join("");
}

function limiting(item) {
  let worst = null;
  for (const line of item.recipe) {
    const ing = ingById(line.ingredient_id);
    if (!ing || line.qty <= 0) continue;
    const n = Math.floor(Math.max(ing.on_hand, 0) / line.qty);
    if (!worst || n < worst.n) worst = { n, ing };
  }
  return worst;
}

function renderDashboard() {
  const reorder = S.ingredients.filter((i) => i.status === "reorder");
  const value = S.ingredients.reduce((a, i) => a + i.stock_value, 0);
  const active = S.items.filter((i) => i.active);
  const out = active.filter((i) => i.can_make === 0);
  const orderCost = reorder.reduce((a, i) => a + i.suggested_packages * (i.package_cost + i.shipping_cost), 0);
  const avgCost = active.length ? active.reduce((a, i) => a + i.cost_pct, 0) / active.length : 0;
  $("#kpis").innerHTML = [
    ["Menu items", active.length, `${S.items.length - active.length} inactive`],
    ["Ingredients", S.ingredients.length, `${unique(S.ingredients.map((i) => i.supplier)).length} suppliers`],
    ["Need reorder", reorder.length, money(orderCost) + " suggested", reorder.length ? "warn" : ""],
    ["Items out of stock", out.length, out.map((i) => i.name).join(", ") || "all available", out.length ? "bad" : ""],
    ["Stock value", money(value), "at landed cost"],
    ["Avg ingredient cost", pct(avgCost), "of menu price"],
  ].map(([l, v, s, c]) => `<div class="kpi ${c || ""}"><div class="kpi-l">${l}</div><div class="kpi-v">${esc(v)}</div><div class="kpi-s">${esc(s)}</div></div>`).join("");

  $("#dash-reorder").innerHTML = reorder.length
    ? `<table class="data compact"><tr><th>Ingredient</th><th>On hand</th><th>Reorder at</th><th>Days left</th><th>Order</th><th>Supplier</th></tr>` +
      reorder.map((i) => `<tr><td>${esc(i.name)}</td><td>${num(i.on_hand)} ${esc(i.unit)}</td><td>${num(i.reorder_point)}</td>
        <td>${i.days_of_cover == null ? "–" : i.days_of_cover.toFixed(1)}${i.days_of_cover != null && i.days_of_cover < i.lead_time_days ? ' <span class="pill bad">< lead time</span>' : ""}</td>
        <td>${i.suggested_packages} × ${esc(i.package_desc || "pkg")}</td><td>${esc(i.supplier)} <span class="hint">(${i.lead_time_days}d)</span></td></tr>`).join("") +
      `</table><button class="primary" onclick="$('#tabs [data-tab=procurement]').click()">Go to procurement →</button>`
    : `<p class="ok-text">Everything is above its reorder point.</p>`;

  $("#dash-availability").innerHTML = `<table class="data compact"><tr><th></th><th>Item</th><th>Can make</th><th>Limited by</th></tr>` +
    active.map((it) => ({ it, lim: limiting(it) })).sort((a, b) => a.it.can_make - b.it.can_make)
      .map(({ it, lim }) => `<tr><td>${thumb(it, "mini")}</td><td>${esc(it.name)}</td>
        <td><span class="pill ${it.can_make === 0 ? "bad" : it.can_make < 20 ? "warn" : "good"}">${it.can_make}</span></td>
        <td>${lim ? esc(lim.ing.name) : "–"}</td></tr>`).join("") + `</table>`;
}

function renderMenu() {
  const q = $("#menu-search").value.toLowerCase();
  const cat = $("#menu-category").value;
  const list = S.items.filter((i) => (!cat || i.category === cat) &&
    (!q || (i.name + " " + i.description + " " + i.recipe.map((r) => ingById(r.ingredient_id)?.name).join(" ")).toLowerCase().includes(q)));
  $("#menu-grid").innerHTML = list.map((it) => `
    <article class="menu-card ${it.active ? "" : "inactive"}" data-id="${esc(it.id)}">
      ${thumb(it, "card-img")}
      <div class="menu-body">
        <div class="menu-top"><h3>${esc(it.name)}</h3><span class="price">${money(it.price)}</span></div>
        <div class="hint">${esc(it.category)}${it.size ? " · " + esc(it.size) : ""}${it.active ? "" : " · inactive"}</div>
        <p>${esc(it.description)}</p>
        <div class="chips">${it.recipe.map((r) => `<span class="chip">${esc(ingById(r.ingredient_id)?.name)}</span>`).join("")}</div>
        <div class="menu-stats">
          <span>Cost ${money(it.cost)}</span><span>Margin ${money(it.margin)}</span>
          <span class="${it.cost_pct > 0.35 ? "bad-text" : ""}">${pct(it.cost_pct)}</span>
          <span class="pill ${it.can_make === 0 ? "bad" : it.can_make < 20 ? "warn" : "good"}">can make ${it.can_make}</span>
        </div>
      </div>
    </article>`).join("") || `<p class="hint">No menu items match.</p>`;
}
$("#menu-search").addEventListener("input", renderMenu);
$("#menu-category").addEventListener("change", renderMenu);
$("#menu-grid").addEventListener("click", (e) => {
  const card = e.target.closest(".menu-card");
  if (card) openItem(itemById(card.dataset.id));
});
$("#new-item").addEventListener("click", () => openItem(null));

function renderIngredients() {
  const q = $("#ing-search").value.toLowerCase();
  const cat = $("#ing-category").value;
  const low = $("#ing-low").checked;
  const list = S.ingredients.filter((i) => (!cat || i.category === cat) && (!low || i.status === "reorder") &&
    (!q || `${i.name} ${i.supplier} ${i.category} ${i.supplier_sku}`.toLowerCase().includes(q)));
  $("#ing-table").innerHTML = `<thead><tr>
      <th>ID</th><th>Ingredient</th><th>Category</th><th>Supplier</th><th>Package</th><th class="r">Pkg cost</th>
      <th class="r">Ship</th><th class="r">Unit cost</th><th class="r">Lead</th><th class="r">Shelf life</th>
      <th class="r">On hand</th><th class="r">Reorder / Par</th><th class="r">Use / day</th><th>Status</th><th>Used in</th></tr></thead><tbody>` +
    list.map((i) => `<tr data-id="${esc(i.id)}" class="${i.status === "reorder" ? "row-bad" : ""}">
      <td class="hint">${esc(i.id)}</td><td><b>${esc(i.name)}</b></td><td>${esc(i.category)}</td><td>${esc(i.supplier)}</td>
      <td>${esc(i.package_desc)} <span class="hint">(${num(i.package_qty)} ${esc(i.unit)})</span></td>
      <td class="r">${money(i.package_cost)}</td><td class="r">${money(i.shipping_cost)}</td>
      <td class="r">${money(i.unit_cost, 3)}/${esc(i.unit)}</td><td class="r">${i.lead_time_days}d</td>
      <td class="r">${i.shelf_life_days ? i.shelf_life_days + "d" : "–"}</td>
      <td class="r"><b>${num(i.on_hand)}</b> ${esc(i.unit)}${i.on_order ? `<div class="hint">+${num(i.on_order)} on order</div>` : ""}</td>
      <td class="r">${num(i.reorder_point)} / ${num(i.par_level)}</td><td class="r">${num(i.daily_usage)}</td>
      <td>${i.status === "reorder" ? `<span class="pill bad">Reorder ${i.suggested_packages}</span>` : `<span class="pill good">OK</span>`}</td>
      <td title="${esc(i.used_in.map((u) => u.name).join(", "))}">${i.used_in.length} item${i.used_in.length === 1 ? "" : "s"}</td></tr>`).join("") + `</tbody>`;
}
["#ing-search", "#ing-category", "#ing-low"].forEach((s) => $(s).addEventListener("input", renderIngredients));
$("#ing-table").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-id]");
  if (tr) openIng(ingById(tr.dataset.id));
});
$("#new-ing").addEventListener("click", () => openIng(null));

// ------------------------------------------------------------ item builder
function openItem(item, duplicate = false) {
  editingItem = item
    ? { ...item, id: duplicate ? null : item.id, recipe: item.recipe.map((r) => ({ ...r })) }
    : { id: null, name: "", category: "", size: "", price: 0, description: "", image: "", emoji: "", active: true, recipe: [] };
  if (duplicate) editingItem.name = item.name + " (copy)";
  const f = $("#item-form");
  for (const k of ["name", "category", "size", "price", "description", "emoji"]) f.elements[k].value = editingItem[k] ?? "";
  f.elements.active.checked = !!editingItem.active;
  $("#item-title").textContent = editingItem.id ? `Edit ${editingItem.name}` : "New menu item";
  $("#item-delete").hidden = !editingItem.id;
  $("#item-duplicate").hidden = !editingItem.id;
  $("#picker-search").value = "";
  pickerCat = "";
  renderBuilder();
  if (!$("#item-dialog").open) $("#item-dialog").showModal();
  f.elements.name.focus();
}

function renderBuilder() {
  const it = editingItem;
  const img = $("#item-image-preview");
  img.src = it.image ? "/images/" + encodeURIComponent(it.image) : "";
  img.hidden = !it.image;
  $("#item-image-placeholder").textContent = it.image ? "" : (it.emoji || "") + " Click or drop a picture";

  // recipe lines
  $("#recipe-lines").innerHTML = it.recipe.length ? it.recipe.map((r, idx) => {
    const ing = ingById(r.ingredient_id) || { name: "?", unit: "", unit_cost: 0 };
    return `<div class="recipe-line" data-idx="${idx}">
      <span class="rl-name">${esc(ing.name)}</span>
      <button type="button" class="step" data-step="-1">−</button>
      <input type="number" step="any" min="0" value="${r.qty}" class="rl-qty">
      <button type="button" class="step" data-step="1">+</button>
      <span class="rl-unit">${esc(ing.unit)}</span>
      <span class="rl-cost">${money(r.qty * ing.unit_cost, 3)}</span>
      <button type="button" class="ghost rl-del" title="Remove">✕</button></div>`;
  }).join("") : `<p class="hint">No ingredients yet — pick some below.</p>`;

  // picker
  const cats = unique(S.ingredients.map((i) => i.category));
  $("#picker-cats").innerHTML = ["", ...cats].map((c) => `<button type="button" class="chip ${c === pickerCat ? "on" : ""}" data-cat="${esc(c)}">${esc(c || "All")}</button>`).join("");
  const q = $("#picker-search").value.toLowerCase();
  const inRecipe = new Set(it.recipe.map((r) => r.ingredient_id));
  $("#picker").innerHTML = S.ingredients
    .filter((i) => (!pickerCat || i.category === pickerCat) && (!q || i.name.toLowerCase().includes(q)))
    .map((i) => `<button type="button" class="pick ${inRecipe.has(i.id) ? "on" : ""} ${i.status === "reorder" ? "low" : ""}" data-id="${esc(i.id)}">
      <b>${esc(i.name)}</b><span>${money(i.unit_cost, 3)}/${esc(i.unit)}</span></button>`).join("");
  updateCostBox();
}

function updateCostBox() {
  const it = editingItem;
  const price = parseFloat($("#item-form").elements.price.value) || 0;
  const cost = it.recipe.reduce((a, r) => a + r.qty * (ingById(r.ingredient_id)?.unit_cost || 0), 0);
  const can = it.recipe.length ? Math.min(...it.recipe.map((r) => {
    const ing = ingById(r.ingredient_id);
    return ing && r.qty > 0 ? Math.floor(Math.max(ing.on_hand, 0) / r.qty) : Infinity;
  })) : 0;
  const cp = price ? cost / price : 0;
  $("#cost-box").innerHTML = `
    <div><span>Ingredient cost</span><b>${money(cost)}</b></div>
    <div><span>Gross margin</span><b>${money(price - cost)}</b></div>
    <div><span>Cost %</span><b class="${cp > 0.35 ? "bad-text" : ""}">${pct(cp)}</b></div>
    <div><span>Can make now</span><b>${Number.isFinite(can) ? can : "–"}</b></div>
    ${price ? `<div class="hint">Price for 30% cost: ${money(cost / 0.3)} · 25%: ${money(cost / 0.25)}</div>` : ""}`;
}

function addToRecipe(ingId) {
  const line = editingItem.recipe.find((r) => r.ingredient_id === ingId);
  if (line) line.qty = +(line.qty + 1).toFixed(4);
  else editingItem.recipe.push({ ingredient_id: ingId, qty: 1 });
  renderBuilder();
}

$("#picker").addEventListener("click", (e) => {
  const b = e.target.closest(".pick");
  if (b) addToRecipe(b.dataset.id);
});
$("#picker-cats").addEventListener("click", (e) => {
  const b = e.target.closest("[data-cat]");
  if (b) { pickerCat = b.dataset.cat; renderBuilder(); }
});
$("#picker-search").addEventListener("input", renderBuilder);
$("#picker-search").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    const first = $("#picker .pick");
    if (first) { addToRecipe(first.dataset.id); $("#picker-search").value = ""; renderBuilder(); $("#picker-search").focus(); }
  }
});
$("#recipe-lines").addEventListener("click", (e) => {
  const row = e.target.closest(".recipe-line");
  if (!row) return;
  const line = editingItem.recipe[+row.dataset.idx];
  if (e.target.matches(".rl-del")) editingItem.recipe.splice(+row.dataset.idx, 1);
  else if (e.target.dataset.step) {
    const step = line.qty < 1 || (line.qty === 1 && e.target.dataset.step === "-1") ? 0.25 : 1;
    line.qty = Math.max(0, +(line.qty + step * +e.target.dataset.step).toFixed(4));
  } else return;
  renderBuilder();
});
$("#recipe-lines").addEventListener("input", (e) => {
  if (!e.target.matches(".rl-qty")) return;
  const row = e.target.closest(".recipe-line");
  const line = editingItem.recipe[+row.dataset.idx];
  line.qty = parseFloat(e.target.value) || 0;
  const ing = ingById(line.ingredient_id);
  $(".rl-cost", row).textContent = money(line.qty * (ing?.unit_cost || 0), 3);
  updateCostBox();
});
$("#item-form").elements.price.addEventListener("input", updateCostBox);

// image upload (click or drag & drop)
async function uploadImage(file) {
  if (!file || !file.type.startsWith("image/")) return toast("Please choose an image file", true);
  try {
    const data = await readFile(file);
    const res = await api("POST", "/api/images", { name: $("#item-form").elements.name.value || "item", data });
    editingItem.image = res.image;
    renderBuilder();
  } catch (err) { toast(err.message, true); }
}
const drop = $("#image-drop");
drop.addEventListener("click", () => $("#item-image-file").click());
$("#item-image-file").addEventListener("change", (e) => uploadImage(e.target.files[0]));
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); uploadImage(e.dataTransfer.files[0]); });

$("#item-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target.elements;
  const body = {
    ...editingItem,
    name: f.name.value, category: f.category.value, size: f.size.value, price: f.price.value,
    description: f.description.value, emoji: f.emoji.value, active: f.active.checked,
    recipe: editingItem.recipe.filter((r) => r.qty > 0),
  };
  if (!body.recipe.length && !confirm("This item has no ingredients. Save anyway?")) return;
  try {
    await api(body.id ? "PUT" : "POST", body.id ? `/api/items/${body.id}` : "/api/items", body);
    $("#item-dialog").close();
    toast(`Saved ${body.name}`);
  } catch (err) { toast(err.message, true); }
});
$("#item-delete").addEventListener("click", async () => {
  if (!confirm(`Delete ${editingItem.name} from the menu?`)) return;
  try { await api("DELETE", `/api/items/${editingItem.id}`); $("#item-dialog").close(); toast("Deleted"); }
  catch (err) { toast(err.message, true); }
});
$("#item-duplicate").addEventListener("click", () => openItem({ ...editingItem, ...formItemFields() }, true));
function formItemFields() {
  const f = $("#item-form").elements;
  return { name: f.name.value, category: f.category.value, size: f.size.value, price: +f.price.value,
    description: f.description.value, emoji: f.emoji.value, active: f.active.checked };
}
$("#picker-new").addEventListener("click", () => openIng(null, { name: $("#picker-search").value, fromBuilder: true }));

// ------------------------------------------------------------ ingredient editor
const ING_NUM = ["package_qty", "package_cost", "shipping_cost", "lead_time_days", "shelf_life_days",
  "min_order_packages", "on_hand", "reorder_point", "par_level"];
const ING_TXT = ["name", "category", "unit", "supplier", "supplier_sku", "package_desc", "notes"];

function openIng(ing, opts = {}) {
  editingIng = ing ? { ...ing } : {
    id: null, name: opts.name || "", category: "", unit: "oz", supplier: "", supplier_sku: "", package_desc: "",
    package_qty: 1, package_cost: 0, shipping_cost: 0, lead_time_days: 2, shelf_life_days: 7, min_order_packages: 1,
    on_hand: 0, reorder_point: 0, par_level: 0, notes: "",
  };
  editingIng.fromBuilder = !!opts.fromBuilder;
  const f = $("#ing-form");
  [...ING_NUM, ...ING_TXT].forEach((k) => (f.elements[k].value = editingIng[k] ?? ""));
  $("#ing-title").textContent = editingIng.id ? `Edit ${editingIng.name}` : "New ingredient";
  $("#ing-delete").hidden = !editingIng.id;
  $("#ing-used-in").innerHTML = ing && ing.used_in.length
    ? "Used in: " + ing.used_in.map((u) => `${esc(u.name)} (${num(u.qty)} ${esc(ing.unit)})`).join(", ")
    : ing ? "Not used in any menu item yet." : "";
  updateIngCalc();
  $("#ing-dialog").showModal();
}

function updateIngCalc() {
  const f = $("#ing-form").elements;
  const v = (k) => parseFloat(f[k].value) || 0;
  const unit = f.unit.value;
  $$("#ing-form .unit-tag").forEach((t) => (t.textContent = `(${unit})`));
  const uc = v("package_qty") > 0 ? (v("package_cost") + v("shipping_cost")) / v("package_qty") : 0;
  $("#ing-unit-cost").innerHTML = `Landed cost: <b>${money(uc, 4)} per ${esc(unit)}</b> · ${money(v("package_cost") + v("shipping_cost"))} per package`;
  const usage = editingIng && editingIng.id ? ingById(editingIng.id)?.daily_usage || 0 : 0;
  const sugg = usage ? usage * v("lead_time_days") * 1.5 : 0;
  $("#ing-reorder-hint").innerHTML = usage
    ? `Recent usage ≈ <b>${num(usage)} ${esc(unit)}/day</b>. Suggested reorder point (lead time × usage × 1.5 safety): <b>${num(sugg)}</b>
       <button type="button" class="ghost small" id="apply-rp">Use it</button>`
    : "Tip: reorder point ≈ daily usage × lead time + safety stock; par level = the level to refill to.";
  $("#apply-rp")?.addEventListener("click", () => { f.reorder_point.value = Math.ceil(sugg); });
}
$("#ing-form").addEventListener("input", updateIngCalc);

$("#ing-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target.elements;
  const body = { id: editingIng.id };
  ING_TXT.forEach((k) => (body[k] = f[k].value));
  ING_NUM.forEach((k) => (body[k] = f[k].value));
  try {
    const res = await api(body.id ? "PUT" : "POST", body.id ? `/api/ingredients/${body.id}` : "/api/ingredients", body);
    $("#ing-dialog").close();
    toast(`Saved ${body.name}`);
    if (editingIng.fromBuilder && $("#item-dialog").open) addToRecipe(res.saved.id);
  } catch (err) { toast(err.message, true); }
});
$("#ing-delete").addEventListener("click", async () => {
  if (!confirm(`Delete ${editingIng.name}?`)) return;
  try { await api("DELETE", `/api/ingredients/${editingIng.id}`); $("#ing-dialog").close(); toast("Deleted"); }
  catch (err) { toast(err.message, true); }
});

$$("[data-close]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));

// ------------------------------------------------------------------ sell
function renderSell() {
  $("#sell-buttons").innerHTML = S.items.filter((i) => i.active).map((it) => `
    <button class="sell-btn ${it.can_make === 0 ? "out" : ""}" data-id="${esc(it.id)}" ${it.can_make === 0 ? "title='Out of stock'" : ""}>
      ${thumb(it, "mini")}<span>${esc(it.name)}</span><b>${money(it.price)}</b>
      ${ticket[it.id] ? `<i class="badge">${ticket[it.id]}</i>` : ""}</button>`).join("");
  const lines = Object.entries(ticket).filter(([, q]) => q > 0);
  let total = 0;
  const usage = {};
  $("#ticket-lines").innerHTML = lines.length ? lines.map(([id, q]) => {
    const it = itemById(id);
    if (!it) return "";
    total += q * it.price;
    it.recipe.forEach((r) => (usage[r.ingredient_id] = (usage[r.ingredient_id] || 0) + r.qty * q));
    return `<div class="tline"><span>${esc(it.name)}</span><span>
      <button class="step" data-t="${esc(id)}" data-d="-1">−</button> ${q} <button class="step" data-t="${esc(id)}" data-d="1">+</button></span>
      <b>${money(q * it.price)}</b></div>`;
  }).join("") + `<div class="tline total"><span>Total</span><span></span><b>${money(total)}</b></div>` : `<p class="hint">Empty ticket.</p>`;
  $("#ticket-usage").innerHTML = lines.length ? `<details><summary>Ingredients this will use</summary><ul>` +
    Object.entries(usage).map(([id, q]) => {
      const ing = ingById(id);
      const short = ing.on_hand - q < 0;
      return `<li class="${short ? "bad-text" : ""}">${esc(ing.name)}: ${num(q)} ${esc(ing.unit)} <span class="hint">(${num(ing.on_hand)} on hand)</span></li>`;
    }).join("") + `</ul></details>` : "";
  $("#sales-log").innerHTML = `<table class="data compact"><tr><th>When</th><th>Item</th><th class="r">Qty</th><th class="r">Revenue</th></tr>` +
    S.sales.slice(-25).reverse().map((s) => {
      const it = itemById(s.item_id);
      return `<tr><td>${esc(s.date.replace("T", " "))}</td><td>${esc(it?.name || s.item_id)}</td><td class="r">${s.qty}</td><td class="r">${money((it?.price || 0) * s.qty)}</td></tr>`;
    }).join("") + `</table>`;
}
$("#sell-buttons").addEventListener("click", (e) => {
  const b = e.target.closest(".sell-btn");
  if (!b) return;
  ticket[b.dataset.id] = (ticket[b.dataset.id] || 0) + 1;
  renderSell();
});
$("#ticket-lines").addEventListener("click", (e) => {
  const b = e.target.closest("[data-t]");
  if (!b) return;
  ticket[b.dataset.t] = Math.max(0, (ticket[b.dataset.t] || 0) + +b.dataset.d);
  renderSell();
});
$("#ticket-clear").addEventListener("click", () => { Object.keys(ticket).forEach((k) => delete ticket[k]); renderSell(); });
$("#ticket-submit").addEventListener("click", async () => {
  const lines = Object.entries(ticket).filter(([, q]) => q > 0).map(([item_id, qty]) => ({ item_id, qty }));
  if (!lines.length) return toast("Ticket is empty", true);
  try {
    Object.keys(ticket).forEach((k) => delete ticket[k]);
    await api("POST", "/api/sales", { lines });
    toast("Sale recorded — stock updated");
  } catch (err) { toast(err.message, true); }
});

// ------------------------------------------------------------- procurement
function renderProcurement() {
  const bySupplier = {};
  S.ingredients.filter((i) => i.status === "reorder" || procQty[i.id] > 0).forEach((i) => {
    (bySupplier[i.supplier || "(no supplier)"] ||= []).push(i);
  });
  const sups = Object.keys(bySupplier).sort();
  $("#proc-suppliers").innerHTML = sups.length ? sups.map((sup) => {
    const rows = bySupplier[sup];
    let total = 0;
    const body = rows.map((i) => {
      const q = procQty[i.id] ?? i.suggested_packages;
      const line = q * (i.package_cost + i.shipping_cost);
      total += line;
      return `<tr><td><b>${esc(i.name)}</b><div class="hint">${esc(i.supplier_sku)}</div></td>
        <td>${num(i.on_hand)} ${esc(i.unit)}${i.on_order ? `<div class="hint">+${num(i.on_order)} on order</div>` : ""}</td>
        <td>${num(i.reorder_point)} / ${num(i.par_level)}</td><td>${esc(i.package_desc)}</td>
        <td><input type="number" min="0" step="1" class="pq" data-id="${esc(i.id)}" value="${q}"></td>
        <td class="r">${money(i.package_cost + i.shipping_cost)}</td><td class="r">${money(line)}</td>
        <td>${i.lead_time_days}d</td><td>${i.shelf_life_days ? i.shelf_life_days + "d" : "–"}</td></tr>`;
    }).join("");
    return `<div class="card"><div class="toolbar"><h2>${esc(sup)}</h2><span class="spacer"></span>
      <b>${money(total)}</b><button class="primary" data-po="${esc(sup)}">Create purchase order</button></div>
      <table class="data compact"><tr><th>Ingredient</th><th>On hand</th><th>Reorder / Par</th><th>Package</th><th>Packages</th>
      <th class="r">Landed / pkg</th><th class="r">Line</th><th>Lead</th><th>Shelf life</th></tr>${body}</table></div>`;
  }).join("") : `<div class="card"><p class="ok-text">Nothing needs ordering right now.</p></div>`;

  const pos = [...S.purchase_orders].reverse();
  $("#po-list").innerHTML = pos.length ? `<table class="data compact"><tr><th>PO</th><th>Supplier</th><th>Created</th><th>Expected</th>
    <th>Lines</th><th class="r">Total</th><th>Status</th><th></th></tr>` + pos.map((po) => {
      const total = po.lines.reduce((a, l) => a + l.packages * (l.package_cost + l.shipping_cost), 0);
      const lines = po.lines.map((l) => `${l.packages} × ${esc(ingById(l.ingredient_id)?.name || l.ingredient_id)}`).join(", ");
      return `<tr><td>${esc(po.id)}</td><td>${esc(po.supplier)}</td><td>${esc(po.created)}</td><td>${esc(po.received || po.expected)}</td>
        <td>${lines}</td><td class="r">${money(total)}</td><td><span class="pill ${po.status === "open" ? "warn" : po.status === "received" ? "good" : ""}">${esc(po.status)}</span></td>
        <td>${po.status === "open" ? `<button class="primary small" data-recv="${esc(po.id)}">Mark received</button>
          <button class="ghost small" data-cancel="${esc(po.id)}">Cancel</button>` : ""}</td></tr>`;
    }).join("") + `</table>` : `<p class="hint">No purchase orders yet.</p>`;
}
$("#proc-suppliers").addEventListener("input", (e) => {
  if (e.target.matches(".pq")) procQty[e.target.dataset.id] = Math.max(0, parseInt(e.target.value) || 0);
});
$("#proc-suppliers").addEventListener("change", renderProcurement);
$("#proc-suppliers").addEventListener("click", async (e) => {
  const sup = e.target.dataset.po;
  if (sup === undefined) return;
  const lines = S.ingredients.filter((i) => (i.supplier || "(no supplier)") === sup && (i.status === "reorder" || procQty[i.id] > 0))
    .map((i) => ({ ingredient_id: i.id, packages: procQty[i.id] ?? i.suggested_packages }));
  try {
    const res = await api("POST", "/api/purchase-orders", { supplier: sup, lines });
    lines.forEach((l) => delete procQty[l.ingredient_id]);
    renderProcurement();
    toast(`Created ${res.saved.id} for ${sup}`);
  } catch (err) { toast(err.message, true); }
});
$("#po-list").addEventListener("click", async (e) => {
  const { recv, cancel } = e.target.dataset;
  try {
    if (recv) { await api("POST", `/api/purchase-orders/${recv}/receive`); toast(`${recv} received — stock added`); }
    if (cancel && confirm(`Cancel ${cancel}?`)) { await api("POST", `/api/purchase-orders/${cancel}/cancel`); }
  } catch (err) { toast(err.message, true); }
});

// ------------------------------------------------------------------ excel
$("#import-upload").addEventListener("click", async () => {
  const file = $("#import-file").files[0];
  if (!file) return toast("Choose an .xlsx file first", true);
  if (!confirm("Replace ingredients, menu items and recipes with the contents of this workbook?")) return;
  try {
    const res = await api("POST", "/api/import", { data: await readFile(file) });
    toast(`Imported ${res.imported.ingredients} ingredients and ${res.imported.items} menu items`);
  } catch (err) { toast(err.message, true); }
});
$("#import-local").addEventListener("click", async () => {
  if (!confirm("Re-read exports/inventory.xlsx and replace ingredients, menu items and recipes?")) return;
  try {
    const res = await api("POST", "/api/import-local", {});
    toast(`Imported ${res.imported.ingredients} ingredients and ${res.imported.items} menu items`);
  } catch (err) { toast(err.message, true); }
});

// ------------------------------------------------------------------ boot
api("GET", "/api/state").then((s) => { S = s; render(); }).catch((e) => toast(e.message, true));
