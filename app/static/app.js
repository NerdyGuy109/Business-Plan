"use strict";

// ------------------------------------------------------------------ state
let S = { ingredients: [], items: [], sales: [], purchase_orders: [], units: [], employees: [], shifts: [], revenue_by_date: {} };
const ticket = {};            // item_id -> qty
const procQty = {};           // ingredient_id -> packages override
let editingItem = null;       // { id?, recipe: [{ingredient_id, qty}], image }
let editingIng = null;
let pickerCat = "";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (v, d = 2) => (v < 0 ? "-$" : "$") + Math.abs(v || 0).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const num = (v) => (Math.round((v || 0) * 100) / 100).toLocaleString();
const pct = (v) => ((v || 0) * 100).toFixed(1) + "%";
const me = () => S.me || null;
const target = () => S.settings?.target_food_cost ?? 0.35;
const allergenLine = (list) => list && list.length ? `<div class="allergens">Contains: ${list.map(esc).join(", ")}</div>` : "";
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
  renderSchedule();
  renderReceiving();
  renderSettings();
  renderStock();
  renderImportHistory();
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
    ["Avg ingredient cost", pct(avgCost), `target ${pct(target())}`, avgCost > target() ? "warn" : ""],
    ...(() => {
      const wk = (S.waste || []).filter((w) => w.at.slice(0, 10) >= mondayOf(todayIso()));
      return [["Waste this week", money(wk.reduce((a, w) => a + w.cost, 0)), `${wk.length} entr${wk.length === 1 ? "y" : "ies"} logged`]];
    })(),
    ...(() => {
      const due = openPOs().filter((p) => p.expected <= todayIso());
      const late = due.filter((p) => p.expected < todayIso());
      return [["Deliveries due", due.length, late.length ? `${late.length} overdue` : due.length ? "check in on Receiving" : "none today",
        late.length ? "bad" : due.length ? "warn" : ""]];
    })(),
    ...(() => {
      const W = weekStats(mondayOf(todayIso()));
      const openCount = W.shifts.filter((s) => !s.employee_id).length;
      return [["Labor this week", money(W.labor, 0), W.sales ? `${pct(W.labor / W.sales)} of sales so far` : `${num(W.hours)} scheduled hours`,
        openCount ? "warn" : ""]];
    })(),
  ].map(([l, v, s, c]) => `<div class="kpi ${c || ""}"><div class="kpi-l">${l}</div><div class="kpi-v">${esc(v)}</div><div class="kpi-s">${esc(s)}</div></div>`).join("");

  $("#dash-reorder").innerHTML = reorder.length
    ? `<table class="data compact"><tr><th>Ingredient</th><th>On hand</th><th>Reorder at</th><th>Days left</th><th>Order</th><th>Supplier</th></tr>` +
      reorder.map((i) => `<tr><td>${esc(i.name)}</td><td>${num(i.on_hand)} ${esc(i.unit)}</td><td>${num(i.reorder_point)}</td>
        <td>${i.days_of_cover == null ? "–" : i.days_of_cover.toFixed(1)}${i.days_of_cover != null && i.days_of_cover < i.lead_time_days ? ' <span class="pill bad">< lead time</span>' : ""}</td>
        <td>${i.suggested_packages} × ${esc(i.package_desc || "pkg")}</td><td>${esc(i.supplier)} <span class="hint">(${i.lead_time_days}d)</span></td></tr>`).join("") +
      `</table><button class="primary" onclick="$('#tabs [data-tab=procurement]').click()">Go to procurement →</button>`
    : `<p class="ok-text">Everything is above its reorder point.</p>`;

  const over = active.filter((i) => i.cost_pct > target());
  const changes = S.price_changes || [];
  $("#dash-prices").innerHTML = (changes.length ? `<table class="data compact"><tr><th>When</th><th>Ingredient</th><th>Cost per unit</th><th>Drinks affected</th></tr>` +
    changes.slice(0, 8).map((c) => {
      const up = c.new.unit_cost > c.old.unit_cost;
      const ch = c.old.unit_cost ? c.new.unit_cost / c.old.unit_cost - 1 : 0;
      return `<tr><td>${esc(c.at.slice(0, 10))}<div class="hint">${esc(c.source)}</div></td><td>${esc(c.ingredient)}</td>
        <td>${money(c.old.unit_cost, 3)} → ${money(c.new.unit_cost, 3)}/${esc(c.unit)} <span class="pill ${up ? "bad" : "good"}">${up ? "+" : ""}${pct(ch)}</span></td>
        <td>${c.items.map((i) => {
          const a = i.price ? i.old_cost / i.price : 0, b = i.price ? i.new_cost / i.price : 0;
          return `<div>${esc(i.name)}: ${pct(a)} → <b class="${b > target() ? "bad-text" : ""}">${pct(b)}</b></div>`;
        }).join("") || '<span class="hint">not used in any drink</span>'}</td></tr>`;
    }).join("") + `</table>` : `<p class="hint">No ingredient price changes in the last 30 days.</p>`) +
    (over.length ? `<p class="bad-text">Above your ${pct(target())} food-cost target: ${over.map((i) => `${esc(i.name)} (${pct(i.cost_pct)})`).join(", ")}</p>`
      : `<p class="ok-text">Every drink is within your ${pct(target())} food-cost target.</p>`);

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
        ${allergenLine(it.allergens)}
        <div class="menu-stats">
          <span>Cost ${money(it.cost)}</span><span>Margin ${money(it.margin)}</span>
          <span class="${it.cost_pct > target() ? "bad-text" : ""}">${pct(it.cost_pct)}</span>
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
      <td>${esc(i.package_desc)} <span class="hint">(${num(i.package_qty)} ${esc(i.unit)}${i.yield_pct < 100 ? `, ${num(i.yield_pct)}% usable` : ""})</span>
        ${i.allergens.length ? `<div class="allergens">${i.allergens.map(esc).join(", ")}</div>` : ""}</td>
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
  const allergens = (S.allergen_list || []).filter((a) => it.recipe.some((r) => (ingById(r.ingredient_id)?.allergens || []).includes(a)));
  $("#cost-box").innerHTML = `
    <div><span>Ingredient cost</span><b>${money(cost)}</b></div>
    <div><span>Gross margin</span><b>${money(price - cost)}</b></div>
    <div><span>Cost %</span><b class="${cp > target() ? "bad-text" : ""}">${pct(cp)}</b></div>
    <div><span>Can make now</span><b>${Number.isFinite(can) ? can : "–"}</b></div>
    ${cost ? `<div class="hint">Price for your ${pct(target())} target: ${money(cost / target())} · for 25%: ${money(cost / 0.25)}</div>` : ""}
    <div class="hint">Allergens: <b>${allergens.length ? allergens.map(esc).join(", ") : "none listed"}</b></div>`;
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
const ING_NUM = ["package_qty", "yield_pct", "package_cost", "shipping_cost", "lead_time_days", "shelf_life_days",
  "min_order_packages", "on_hand", "reorder_point", "par_level"];
const ING_TXT = ["name", "category", "unit", "supplier", "supplier_sku", "package_desc", "notes"];

function openIng(ing, opts = {}) {
  editingIng = ing ? { ...ing } : {
    id: null, name: opts.name || "", category: "", unit: "oz", supplier: "", supplier_sku: "", package_desc: "",
    package_qty: 1, yield_pct: 100, allergens: [], package_cost: 0, shipping_cost: 0, lead_time_days: 2, shelf_life_days: 7, min_order_packages: 1,
    on_hand: 0, reorder_point: 0, par_level: 0, notes: "",
  };
  editingIng.fromBuilder = !!opts.fromBuilder;
  const f = $("#ing-form");
  [...ING_NUM, ...ING_TXT].forEach((k) => (f.elements[k].value = editingIng[k] ?? ""));
  $("#ing-allergens").innerHTML = (S.allergen_list || []).map((a) => `<label class="check"><input type="checkbox" value="${esc(a)}"
    ${(editingIng.allergens || []).includes(a) ? "checked" : ""}> ${esc(a)}</label>`).join("");
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
  const usable = v("package_qty") * (f.yield_pct.value === "" ? 100 : v("yield_pct")) / 100;
  const uc = usable > 0 ? (v("package_cost") + v("shipping_cost")) / usable : 0;
  $("#ing-unit-cost").innerHTML = `Landed cost: <b>${money(uc, 4)} per usable ${esc(unit)}</b> · ${money(v("package_cost") + v("shipping_cost"))} per package` +
    (usable && usable !== v("package_qty") ? ` · ${num(usable)} ${esc(unit)} usable per package` : "");
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
  body.allergens = $$("#ing-allergens input:checked").map((x) => x.value);
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
      ${it.allergens.length ? `<small class="allergens">${it.allergens.map(esc).join(", ")}</small>` : ""}
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
      const lines = po.lines.map((l) => `${l.received && l.received !== l.packages ? `${l.received}/` : ""}${l.packages} × ${esc(ingById(l.ingredient_id)?.name || l.ingredient_id)}`).join(", ");
      const open = po.status === "open" || po.status === "partial";
      return `<tr><td>${esc(po.id)}</td><td>${esc(po.supplier)}</td><td>${esc(po.created)}</td><td>${esc(po.received || po.expected)}</td>
        <td>${lines}</td><td class="r">${money(total)}</td><td>${poStatusPill(po)}</td>
        <td>${open ? `<button class="primary small" data-recv="${esc(po.id)}">Receive…</button>` : ""}
          ${po.status === "open" ? `<button class="ghost small" data-cancel="${esc(po.id)}">Cancel</button>` : ""}</td></tr>`;
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
    if (recv) return openReceiving(recv);
    if (cancel && confirm(`Cancel ${cancel}?`)) { await api("POST", `/api/purchase-orders/${cancel}/cancel`); }
  } catch (err) { toast(err.message, true); }
});

// ---------------------------------------------------------------- schedule
const pad2 = (n) => String(n).padStart(2, "0");
const isoOf = (dt) => `${dt.getFullYear()}-${pad2(dt.getMonth() + 1)}-${pad2(dt.getDate())}`;
const addDays = (iso, n) => { const [y, m, d] = iso.split("-").map(Number); return isoOf(new Date(y, m - 1, d + n)); };
const mondayOf = (iso) => { const [y, m, d] = iso.split("-").map(Number); return addDays(iso, -((new Date(y, m - 1, d).getDay() + 6) % 7)); };
const todayIso = () => isoOf(new Date());
const dayLabel = (iso, opts) => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d).toLocaleDateString(undefined, opts); };
const toMin = (t) => { const [h, m] = t.split(":").map(Number); return h * 60 + m; };
const clock = (t) => {
  const [h, m] = t.split(":").map(Number);
  return `${h % 12 || 12}${m ? ":" + pad2(m) : ""}${h < 12 ? "a" : "p"}`;
};
const SHIFT_PRESETS = [["Open", "06:30", "14:30"], ["Mid", "10:00", "16:00"], ["Close", "13:00", "20:00"]];
let weekStart = mondayOf(todayIso());
let editingShift = null;
let editingEmp = null;
const empById = (id) => S.employees.find((e) => e.id === id);

function weekStats(start) {
  const days = [0, 1, 2, 3, 4, 5, 6].map((i) => addDays(start, i));
  const shifts = S.shifts.filter((s) => s.date >= days[0] && s.date <= days[6]);
  const cost = (s) => s.hours * (empById(s.employee_id)?.hourly_rate || 0);
  const sales = days.reduce((a, d) => a + (S.revenue_by_date[d] || 0), 0);
  const labor = shifts.reduce((a, s) => a + cost(s), 0);
  return { days, shifts, cost, sales, labor, hours: shifts.reduce((a, s) => a + s.hours, 0) };
}

// Shifts that overlap another shift of the same person.
function conflicts(shifts) {
  const bad = new Set();
  const span = (s) => { const a = toMin(s.start); let b = toMin(s.end); if (b <= a) b += 1440; return [a, b]; };
  for (const a of shifts) for (const b of shifts) {
    if (a === b || !a.employee_id || a.employee_id !== b.employee_id || a.date !== b.date) continue;
    const [as, ae] = span(a), [bs, be] = span(b);
    if (as < be && bs < ae) bad.add(a.id);
  }
  return bad;
}

function renderSchedule() {
  const W = weekStats(weekStart);
  const { days, shifts } = W;
  $("#wk-label").textContent = `${dayLabel(days[0], { month: "short", day: "numeric" })} – ${dayLabel(days[6], { month: "short", day: "numeric", year: "numeric" })}`;
  $("#roles").innerHTML = unique([...S.employees.map((e) => e.role), ...S.shifts.map((s) => s.role)]).map((r) => `<option value="${esc(r)}">`).join("");

  const showFormer = $("#show-former").checked;
  const staff = S.employees.filter((e) => e.active || showFormer || shifts.some((s) => s.employee_id === e.id));
  const clash = conflicts(shifts);
  const open = shifts.filter((s) => !s.employee_id);
  const warnings = [];
  const today = todayIso();

  const chip = (s) => {
    const emp = empById(s.employee_id);
    return `<div class="shift ${emp ? "" : "open"} ${clash.has(s.id) ? "conflict" : ""}" draggable="true" data-id="${esc(s.id)}"
      style="--c:${esc(emp?.color || "var(--warn)")}" title="${esc(s.notes || "")}">
      <b>${clock(s.start)}–${clock(s.end)}</b><span>${esc(s.role || "")}${s.role ? " · " : ""}${num(s.hours)}h</span>
      ${s.notes ? `<i>${esc(s.notes)}</i>` : ""}</div>`;
  };
  const row = (emp) => {
    const mine = shifts.filter((s) => (s.employee_id || null) === (emp ? emp.id : null));
    const hours = mine.reduce((a, s) => a + s.hours, 0);
    const over = emp && emp.max_hours > 0 && hours > emp.max_hours;
    if (over) warnings.push(`${emp.name} is scheduled ${num(hours)}h, over their ${num(emp.max_hours)}h maximum.`);
    const head = emp
      ? `<th class="emp" data-emp="${esc(emp.id)}" style="--c:${esc(emp.color)}"><span class="dot"></span><b>${esc(emp.name)}</b>
          ${emp.active ? "" : '<span class="pill">former</span>'}
          <div class="hint">${esc(emp.role)} · ${money(emp.hourly_rate)}/h</div>
          <div class="hint ${over ? "bad-text" : ""}">${num(hours)} / ${num(emp.max_hours)}h · ${money(hours * emp.hourly_rate, 0)}</div></th>`
      : `<th class="emp open-row"><b>Open shifts</b><div class="hint">${open.length ? `${open.length} to fill` : "none"}</div></th>`;
    return `<tr>${head}${days.map((d) => `<td class="cell ${d === today ? "today" : ""}" data-emp="${emp ? esc(emp.id) : ""}" data-date="${d}">
      ${mine.filter((s) => s.date === d).sort((a, b) => a.start.localeCompare(b.start)).map(chip).join("")}</td>`).join("")}</tr>`;
  };

  const perDay = days.map((d) => {
    const ds = shifts.filter((s) => s.date === d);
    const labor = ds.reduce((a, s) => a + W.cost(s), 0);
    const sales = S.revenue_by_date[d] || 0;
    return { hours: ds.reduce((a, s) => a + s.hours, 0), people: new Set(ds.filter((s) => s.employee_id).map((s) => s.employee_id)).size, labor, sales };
  });
  const body = row(null) + staff.map(row).join("");
  $("#sched").innerHTML = `<thead><tr><th class="emp">Team</th>${days.map((d) => `<th class="${d === today ? "today" : ""}">
      ${dayLabel(d, { weekday: "short" })}<div class="hint">${dayLabel(d, { month: "short", day: "numeric" })}</div></th>`).join("")}</tr></thead>
    <tbody>${body}</tbody>
    <tfoot>
      <tr><th class="emp">Staff hours</th>${perDay.map((p) => `<td>${num(p.hours)}h <span class="hint">· ${p.people} people</span></td>`).join("")}</tr>
      <tr><th class="emp">Labor cost</th>${perDay.map((p) => `<td>${money(p.labor, 0)}</td>`).join("")}</tr>
      <tr><th class="emp">Sales recorded</th>${perDay.map((p) => `<td>${p.sales ? money(p.sales, 0) : "–"}${p.sales ? ` <span class="hint">· labor ${pct(p.labor / p.sales)}</span>` : ""}</td>`).join("")}</tr>
    </tfoot>`;

  if (clash.size) warnings.push(`${clash.size} shifts overlap another shift for the same person (outlined in red).`);
  if (open.length) warnings.push(`${open.length} open shift${open.length === 1 ? "" : "s"} still need${open.length === 1 ? "s" : ""} someone.`);
  $("#sched-warnings").innerHTML = warnings.map((w) => `<div class="warn-line">${esc(w)}</div>`).join("");
  $("#sched-kpis").innerHTML = [
    ["Scheduled hours", num(W.hours) + "h", `${new Set(shifts.filter((s) => s.employee_id).map((s) => s.employee_id)).size} people`],
    ["Labor cost", money(W.labor, 0), "hours × hourly rate"],
    ["Sales recorded", money(W.sales, 0), "this week so far"],
    ["Labor % of sales", W.sales ? pct(W.labor / W.sales) : "–", W.sales ? "scheduled labor ÷ sales" : "no sales yet", W.sales && W.labor / W.sales > 0.35 ? "warn" : ""],
    ["Open shifts", open.length, open.length ? "need someone" : "all covered", open.length ? "warn" : ""],
  ].map(([l, v, s, c]) => `<div class="kpi ${c || ""}"><div class="kpi-l">${l}</div><div class="kpi-v">${esc(v)}</div><div class="kpi-s">${esc(s)}</div></div>`).join("");
}

$("#wk-prev").addEventListener("click", () => { weekStart = addDays(weekStart, -7); renderSchedule(); });
$("#wk-next").addEventListener("click", () => { weekStart = addDays(weekStart, 7); renderSchedule(); });
$("#wk-today").addEventListener("click", () => { weekStart = mondayOf(todayIso()); renderSchedule(); });
$("#show-former").addEventListener("change", renderSchedule);
$("#wk-copy").addEventListener("click", async () => {
  const have = weekStats(weekStart).shifts.length;
  const prev = weekStats(addDays(weekStart, -7)).shifts.length;
  if (!prev) return toast("Last week has no shifts to copy", true);
  if (!confirm(have ? `This week already has ${have} shifts. Add last week's ${prev} shifts as well?` : `Copy last week's ${prev} shifts into this week?`)) return;
  try {
    const res = await api("POST", "/api/shifts/copy-week", { from: addDays(weekStart, -7), to: weekStart });
    toast(`Copied ${res.copied} shifts`);
  } catch (err) { toast(err.message, true); }
});

// drag & drop: move a shift, or copy it with Ctrl / Alt held
$("#sched").addEventListener("dragstart", (e) => {
  const chip = e.target.closest(".shift");
  if (!chip) return;
  e.dataTransfer.setData("text/plain", chip.dataset.id);
  e.dataTransfer.effectAllowed = "copyMove";
  chip.classList.add("dragging");
});
$("#sched").addEventListener("dragend", () => $$(".dragging, .cell.over").forEach((x) => x.classList.remove("dragging", "over")));
$("#sched").addEventListener("dragover", (e) => {
  const cell = e.target.closest(".cell");
  if (!cell) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = e.ctrlKey || e.altKey ? "copy" : "move";
  $$(".cell.over").forEach((x) => x !== cell && x.classList.remove("over"));
  cell.classList.add("over");
});
$("#sched").addEventListener("drop", async (e) => {
  const cell = e.target.closest(".cell");
  if (!cell) return;
  e.preventDefault();
  cell.classList.remove("over");
  const shift = S.shifts.find((s) => s.id === e.dataTransfer.getData("text/plain"));
  if (!shift) return;
  const target = { employee_id: cell.dataset.emp || null, date: cell.dataset.date };
  const copy = e.ctrlKey || e.altKey;
  if (!copy && target.date === shift.date && target.employee_id === (shift.employee_id || null)) return;
  const body = { ...shift, ...target };
  try {
    if (copy) { delete body.id; await api("POST", "/api/shifts", body); }
    else await api("PUT", `/api/shifts/${shift.id}`, body);
    const who = empById(target.employee_id)?.name || "open shifts";
    toast(`${copy ? "Copied" : "Moved"} to ${who}, ${dayLabel(target.date, { weekday: "short", month: "short", day: "numeric" })}`);
  } catch (err) { toast(err.message, true); }
});
$("#sched").addEventListener("click", (e) => {
  const chip = e.target.closest(".shift");
  if (chip) return openShift(S.shifts.find((s) => s.id === chip.dataset.id));
  const cell = e.target.closest(".cell");
  if (cell) return openShift(null, { employee_id: cell.dataset.emp || null, date: cell.dataset.date });
  const head = e.target.closest("th[data-emp]");
  if (head) openEmp(empById(head.dataset.emp));
});

function openShift(shift, defaults = {}) {
  const emp = empById(defaults.employee_id);
  editingShift = shift ? { ...shift } : {
    id: null, employee_id: defaults.employee_id || null, date: defaults.date || weekStart,
    start: SHIFT_PRESETS[0][1], end: SHIFT_PRESETS[0][2], role: emp?.role || "", notes: "",
  };
  const f = $("#shift-form");
  $("#shift-emp").innerHTML = `<option value="">— Open shift (unassigned) —</option>` +
    S.employees.filter((e) => e.active || e.id === editingShift.employee_id)
      .map((e) => `<option value="${esc(e.id)}">${esc(e.name)} (${esc(e.role)})</option>`).join("");
  ["employee_id", "date", "start", "end", "role", "notes"].forEach((k) => (f.elements[k].value = editingShift[k] || ""));
  $("#shift-title").textContent = shift ? "Edit shift" : "New shift";
  $("#shift-delete").hidden = !shift;
  $("#shift-presets").innerHTML = SHIFT_PRESETS.map(([n, a, b]) => `<button type="button" class="chip" data-a="${a}" data-b="${b}">${n} ${clock(a)}–${clock(b)}</button>`).join("");
  updateShiftCalc();
  $("#shift-dialog").showModal();
}
function updateShiftCalc() {
  const f = $("#shift-form").elements;
  if (!f.start.value || !f.end.value) return ($("#shift-calc").textContent = "");
  const hours = ((toMin(f.end.value) - toMin(f.start.value) + 1440) % 1440) / 60;
  const emp = empById(f.employee_id.value);
  const others = S.shifts.filter((s) => s.employee_id && s.employee_id === f.employee_id.value && s.id !== editingShift.id &&
    s.date >= mondayOf(f.date.value || weekStart) && s.date <= addDays(mondayOf(f.date.value || weekStart), 6));
  const week = others.reduce((a, s) => a + s.hours, 0) + hours;
  $("#shift-calc").innerHTML = `${num(hours)} hours` + (emp ? ` · ${money(hours * emp.hourly_rate)} labor ·
    <span class="${emp.max_hours && week > emp.max_hours ? "bad-text" : ""}">${num(week)} of ${num(emp.max_hours)}h that week</span>` : "");
}
$("#shift-form").addEventListener("input", updateShiftCalc);
$("#shift-emp").addEventListener("change", () => {
  const emp = empById($("#shift-emp").value);
  if (emp && !$("#shift-form").elements.role.value) $("#shift-form").elements.role.value = emp.role;
});
$("#shift-presets").addEventListener("click", (e) => {
  const b = e.target.closest("[data-a]");
  if (!b) return;
  const f = $("#shift-form").elements;
  f.start.value = b.dataset.a;
  f.end.value = b.dataset.b;
  updateShiftCalc();
});
$("#shift-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target.elements;
  const body = { id: editingShift.id };
  ["employee_id", "date", "start", "end", "role", "notes"].forEach((k) => (body[k] = f[k].value));
  try {
    await api(body.id ? "PUT" : "POST", body.id ? `/api/shifts/${body.id}` : "/api/shifts", body);
    $("#shift-dialog").close();
    weekStart = mondayOf(body.date);
    renderSchedule();
    toast("Shift saved");
  } catch (err) { toast(err.message, true); }
});
$("#shift-delete").addEventListener("click", async () => {
  try { await api("DELETE", `/api/shifts/${editingShift.id}`); $("#shift-dialog").close(); toast("Shift deleted"); }
  catch (err) { toast(err.message, true); }
});

function openEmp(emp) {
  editingEmp = emp ? { ...emp } : { id: null, name: "", role: "", hourly_rate: 15, max_hours: 40, phone: "", email: "", color: "", active: true };
  const f = $("#emp-form");
  ["name", "role", "hourly_rate", "max_hours", "phone", "email"].forEach((k) => (f.elements[k].value = editingEmp[k] ?? ""));
  f.elements.color.value = editingEmp.color || "#3e7cb1";
  f.elements.active.checked = !!editingEmp.active;
  $("#emp-title").textContent = emp ? `Edit ${emp.name}` : "New employee";
  $("#emp-remove").hidden = !emp || !emp.active;
  const upcoming = emp ? S.shifts.filter((s) => s.employee_id === emp.id && s.date >= todayIso()) : [];
  $("#emp-summary").textContent = emp ? `${upcoming.length} upcoming shift${upcoming.length === 1 ? "" : "s"}.` : "";
  $("#emp-dialog").showModal();
}
$("#new-emp").addEventListener("click", () => openEmp(null));
$("#emp-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target.elements;
  const body = { id: editingEmp.id, active: f.active.checked };
  ["name", "role", "hourly_rate", "max_hours", "phone", "email", "color"].forEach((k) => (body[k] = f[k].value));
  if (!editingEmp.id && !editingEmp.color && body.color === "#3e7cb1") body.color = "";  // let the server pick a colour
  try {
    await api(body.id ? "PUT" : "POST", body.id ? `/api/employees/${body.id}` : "/api/employees", body);
    $("#emp-dialog").close();
    toast(`Saved ${body.name}`);
  } catch (err) { toast(err.message, true); }
});
$("#emp-remove").addEventListener("click", async () => {
  const upcoming = S.shifts.filter((s) => s.employee_id === editingEmp.id && s.date >= todayIso()).length;
  if (!confirm(`Remove ${editingEmp.name} from the roster?` + (upcoming ? ` Their ${upcoming} upcoming shifts become open shifts.` : "") +
    " Past shifts are kept for labor history.")) return;
  try {
    const res = await api("DELETE", `/api/employees/${editingEmp.id}`);
    $("#emp-dialog").close();
    toast(`${editingEmp.name} removed` + (res.opened_shifts ? ` — ${res.opened_shifts} shifts are now open` : ""));
  } catch (err) { toast(err.message, true); }
});

// --------------------------------------------------------------- receiving
let recvPO = null;      // id of the order being checked in
let recvDraft = null;   // what the staff member has entered so far
const nowLocal = () => { const d = new Date(); return `${isoOf(d)}T${pad2(d.getHours())}:${pad2(d.getMinutes())}`; };
const daysBetween = (a, b) => Math.round((Date.parse(b) - Date.parse(a)) / 864e5);
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const openPOs = () => S.purchase_orders.filter((p) => p.status === "open" || p.status === "partial");

function poStatusPill(po) {
  if (po.status === "partial") return `<span class="pill warn">partly received</span>`;
  if (po.status === "received") return `<span class="pill ${po.short ? "warn" : "good"}">received${po.short ? " (short)" : ""}</span>`;
  if (po.status === "open") return `<span class="pill warn">open</span>`;
  return `<span class="pill">${esc(po.status)}</span>`;
}
function dueBadge(po) {
  const d = daysBetween(todayIso(), po.expected);
  if (d < 0) return `<span class="pill bad">${-d} day${d === -1 ? "" : "s"} late</span>`;
  if (d === 0) return `<span class="pill warn">due today</span>`;
  return `<span class="pill">due in ${d} day${d === 1 ? "" : "s"}</span>`;
}

function openReceiving(poId) {
  $('#tabs [data-tab="receiving"]').click();
  selectPO(poId);
}

function selectPO(poId) {
  const po = S.purchase_orders.find((p) => p.id === poId);
  recvPO = po ? po.id : null;
  recvDraft = po && {
    received_by: "", received_at: nowLocal(), reference: "", package_damaged: false, wrong_items: false, notes: "", close_short: false,
    lines: Object.fromEntries(po.lines.filter((l) => l.outstanding > 0).map((l) => [l.ingredient_id, { ok: false, good: 0, damaged: 0, note: "", invoice_cost: null }])),
  };
  renderReceiving();
}

function renderReceiving() {
  const q = $("#recv-search").value.toLowerCase();
  const list = openPOs().filter((p) => !q || `${p.id} ${p.supplier}`.toLowerCase().includes(q))
    .sort((a, b) => a.expected.localeCompare(b.expected));
  $("#recv-list").innerHTML = list.map((po) => {
    const left = po.lines.reduce((a, l) => a + l.outstanding, 0);
    return `<button class="recv-card ${po.id === recvPO ? "on" : ""}" data-po="${esc(po.id)}">
      <div class="rc-top"><b>${esc(po.id)}</b>${dueBadge(po)}</div>
      <div>${esc(po.supplier)}</div>
      <div class="hint">${plural(po.lines.filter((l) => l.outstanding).length, "item")} · ${plural(left, "package")} expected
        ${po.status === "partial" ? " · partly received" : ""}${po.delays.length ? " · delay logged" : ""}</div></button>`;
  }).join("") || `<p class="hint">No deliveries expected.</p>`;
  if (recvPO && !openPOs().some((p) => p.id === recvPO)) { recvPO = null; recvDraft = null; }
  renderRecvPanel();
  renderRecvLog();
}

function renderRecvPanel() {
  const po = S.purchase_orders.find((p) => p.id === recvPO);
  if (!po) {
    $("#recv-panel").innerHTML = `<div class="recv-empty"><h2>Check in a delivery</h2><p class="hint">Choose the order on the left that matches the packing slip or invoice.</p></div>`;
    return;
  }
  const staff = S.employees.filter((e) => e.active);
  const rows = po.lines.filter((l) => l.outstanding > 0).map((l) => {
    const ing = ingById(l.ingredient_id) || { name: l.ingredient_id, unit: "", package_qty: 1, usable_per_package: 1, package_desc: "", package_cost: 0 };
    const d = recvDraft.lines[l.ingredient_id];
    return `<tr data-ing="${esc(l.ingredient_id)}">
      <td><b>${esc(ing.name)}</b><div class="hint">${esc(ing.package_desc || "package")} · ${num(ing.package_qty)}${ing.unit === "each" ? "" : " " + esc(ing.unit)} per package</div>
        ${l.received ? `<div class="hint">${l.received} of ${l.packages} already received</div>` : ""}</td>
      <td class="r big">${l.outstanding}</td>
      <td class="c"><input type="checkbox" class="rl-ok" ${d.ok ? "checked" : ""} aria-label="All arrived OK"></td>
      <td><input type="number" min="0" max="${l.outstanding}" step="1" class="rl-good" value="${d.good}"></td>
      <td><input type="number" min="0" step="1" class="rl-dmg" value="${d.damaged}"></td>
      <td><input class="rl-note" placeholder="e.g. lid cracked" value="${esc(d.note)}"></td>
      <td><input type="number" min="0" step="0.01" class="rl-price" placeholder="${num(ing.package_cost)}" value="${d.invoice_cost ?? ""}"
        title="Price per package on the invoice. Leave blank if unchanged (${money(ing.package_cost)})."></td>
      <td class="rl-state"></td></tr>`;
  }).join("");
  $("#recv-panel").innerHTML = `
    <div class="toolbar tight"><h2>${esc(po.id)} · ${esc(po.supplier)}</h2><span class="spacer"></span>${dueBadge(po)}</div>
    <div class="hint">Ordered ${esc(po.created)} · expected ${esc(po.expected)}${po.receipts.length ? ` · ${po.receipts.length} earlier delivery` : ""}</div>
    ${po.delays.map((d) => `<div class="delay-note">Delay logged ${esc(d.at.replace("T", " "))}: ${esc(d.note)}${d.expected !== d.previous_expected ? ` (new date ${esc(d.expected)})` : ""}</div>`).join("")}
    <div class="three recv-fields">
      <label>Received by <select id="rv-by"><option value="">— choose —</option>${staff.map((e) => `<option value="${esc(e.id)}" ${recvDraft.received_by === e.id ? "selected" : ""}>${esc(e.name)}</option>`).join("")}</select></label>
      <label>Date &amp; time received <input type="datetime-local" id="rv-at" value="${esc(recvDraft.received_at)}"></label>
      <label>Tracking / invoice # <input id="rv-ref" value="${esc(recvDraft.reference)}" placeholder="optional"></label>
    </div>
    <button type="button" class="ghost" id="rv-all">&#10003; Everything arrived in good condition</button>
    <div class="table-wrap"><table class="data compact recv-table">
      <tr><th>Item</th><th class="r">Expected (pkgs)</th><th class="c">All OK</th><th>Received OK</th><th>Damaged</th><th>Note</th><th title="Price per package on the invoice, if it changed">Invoice $/pkg</th><th></th></tr>
      ${rows}</table></div>
    <div class="recv-checks">
      <span id="rv-late"></span>
      <label class="check"><input type="checkbox" id="rv-boxdmg" ${recvDraft.package_damaged ? "checked" : ""}> Outer packaging damaged</label>
      <label class="check"><input type="checkbox" id="rv-wrong" ${recvDraft.wrong_items ? "checked" : ""}> Wrong or extra items in the delivery</label>
    </div>
    <label>Delivery notes <textarea id="rv-notes" rows="2" placeholder="Anything the manager should know: driver, condition, who was called…">${esc(recvDraft.notes)}</textarea></label>
    <label class="check" id="rv-close-wrap"><input type="checkbox" id="rv-close" ${recvDraft.close_short ? "checked" : ""}> Nothing else is coming — close this order short</label>
    <div class="calc" id="rv-summary"></div>
    <div class="row-gap"><button class="primary" id="rv-submit">Submit receipt</button></div>
    <details class="delay-box"><summary>Delivery delayed? Log it</summary>
      <div class="two">
        <label>What happened <input id="dl-note" placeholder="e.g. supplier called, truck delayed"></label>
        <label>New expected date <input type="date" id="dl-date" value="${esc(po.expected)}"></label>
      </div>
      <button class="ghost" id="dl-save">Log delay</button>
    </details>`;
  updateRecvSummary();
}

// Row badges, late flag and the stock summary, without re-rendering the inputs being typed in.
function updateRecvSummary() {
  const po = S.purchase_orders.find((p) => p.id === recvPO);
  if (!po) return;
  const adds = [], still = [], prices = [];
  let anyShort = false;
  for (const l of po.lines.filter((x) => x.outstanding > 0)) {
    const d = recvDraft.lines[l.ingredient_id];
    const ing = ingById(l.ingredient_id) || { name: l.ingredient_id, unit: "", usable_per_package: 1, package_cost: 0 };
    const short = l.outstanding - d.good;
    if (short > 0) { anyShort = true; still.push(`${short} × ${ing.name}`); }
    if (d.good) adds.push(`${esc(ing.name)} <b>+${num(d.good * ing.usable_per_package)} ${esc(ing.unit)}</b>`);
    if (d.invoice_cost != null && Math.abs(d.invoice_cost - ing.package_cost) > 1e-9)
      prices.push(`${esc(ing.name)} ${money(ing.package_cost)} → <b>${money(d.invoice_cost)}</b>`);
    const tags = [];
    if (d.good === l.outstanding && !d.damaged) tags.push(`<span class="pill good">OK</span>`);
    if (d.damaged) tags.push(`<span class="pill bad">${d.damaged} damaged</span>`);
    if (short > 0 && (d.good || d.damaged)) tags.push(`<span class="pill warn">${short} not received</span>`);
    const cell = $(`#recv-panel tr[data-ing="${l.ingredient_id}"] .rl-state`);
    if (cell) cell.innerHTML = tags.join(" ");
  }
  const at = recvDraft.received_at ? recvDraft.received_at.slice(0, 10) : todayIso();
  const late = daysBetween(po.expected, at);
  $("#rv-late").innerHTML = late > 0 ? `<span class="pill bad">Arrived ${late} day${late === 1 ? "" : "s"} late</span>` : `<span class="pill good">On time</span>`;
  $("#rv-close-wrap").hidden = !anyShort;
  if (!anyShort) recvDraft.close_short = false;
  $("#rv-summary").innerHTML = (adds.length ? `Adds to stock: ${adds.join(" · ")}` : "Nothing will be added to stock yet.") +
    (anyShort ? `<div class="${recvDraft.close_short ? "bad-text" : ""}">${recvDraft.close_short ? "Closing short — not coming: " : "Still on order afterwards: "}${esc(still.join(", "))}</div>` : "") +
    (prices.length ? `<div>Price update from invoice: ${prices.join(" · ")}</div>` : "") +
    `<div>Order will be marked <b>${!anyShort ? "received" : recvDraft.close_short ? "received (short)" : "partly received"}</b>.</div>`;
}

$("#recv-search").addEventListener("input", renderReceiving);
$("#recv-list").addEventListener("click", (e) => {
  const b = e.target.closest("[data-po]");
  if (b) selectPO(b.dataset.po);
});
$("#recv-panel").addEventListener("input", (e) => {
  const t = e.target;
  const row = t.closest("tr[data-ing]");
  if (row) {
    const l = S.purchase_orders.find((p) => p.id === recvPO).lines.find((x) => x.ingredient_id === row.dataset.ing);
    const d = recvDraft.lines[row.dataset.ing];
    if (t.matches(".rl-ok")) {
      d.ok = t.checked;
      d.good = t.checked ? l.outstanding : 0;
      if (t.checked) d.damaged = 0;
      $(".rl-good", row).value = d.good;
      $(".rl-dmg", row).value = d.damaged;
    } else if (t.matches(".rl-good")) {
      d.good = Math.min(Math.max(parseInt(t.value) || 0, 0), l.outstanding);
      d.ok = d.good === l.outstanding && !d.damaged;
      $(".rl-ok", row).checked = d.ok;
    } else if (t.matches(".rl-dmg")) {
      d.damaged = Math.max(parseInt(t.value) || 0, 0);
      d.ok = d.good === l.outstanding && !d.damaged;
      $(".rl-ok", row).checked = d.ok;
    } else if (t.matches(".rl-note")) d.note = t.value;
    else if (t.matches(".rl-price")) d.invoice_cost = t.value === "" ? null : Math.max(parseFloat(t.value) || 0, 0);
  } else {
    const map = { "rv-by": "received_by", "rv-at": "received_at", "rv-ref": "reference", "rv-notes": "notes" };
    if (map[t.id]) recvDraft[map[t.id]] = t.value;
    if (t.id === "rv-boxdmg") recvDraft.package_damaged = t.checked;
    if (t.id === "rv-wrong") recvDraft.wrong_items = t.checked;
    if (t.id === "rv-close") recvDraft.close_short = t.checked;
  }
  updateRecvSummary();
});
$("#recv-panel").addEventListener("click", async (e) => {
  const po = S.purchase_orders.find((p) => p.id === recvPO);
  if (!po) return;
  if (e.target.id === "rv-all") {
    for (const l of po.lines.filter((x) => x.outstanding > 0)) Object.assign(recvDraft.lines[l.ingredient_id], { ok: true, good: l.outstanding, damaged: 0 });
    renderRecvPanel();
  }
  if (e.target.id === "rv-submit") {
    if (S.employees.some((x) => x.active) && !recvDraft.received_by) return toast("Choose who received the delivery", true);
    const lines = Object.entries(recvDraft.lines).map(([ingredient_id, d]) => ({ ingredient_id, good: d.good, damaged: d.damaged, note: d.note, invoice_cost: d.invoice_cost ?? null }));
    if (!lines.some((l) => l.good || l.damaged) && !recvDraft.close_short) return toast("Tick the items that arrived, or log a delay instead", true);
    if (!confirm(`Submit receipt for ${po.id}? Stock will be updated.`)) return;
    try {
      const res = await api("POST", `/api/purchase-orders/${po.id}/receive`, { ...recvDraft, lines });
      const after = S.purchase_orders.find((p) => p.id === po.id);
      toast(after.status === "partial" ? `${po.id} partly received — the rest stays on order` : `${po.id} received — stock updated (${res.receipt.id})`);
      recvPO = null; recvDraft = null;
      renderReceiving();
    } catch (err) { toast(err.message, true); }
  }
  if (e.target.id === "dl-save") {
    try {
      await api("POST", `/api/purchase-orders/${po.id}/delay`, { note: $("#dl-note").value, expected: $("#dl-date").value });
      toast(`Delay logged for ${po.id}`);
    } catch (err) { toast(err.message, true); }
  }
});

function renderRecvLog() {
  const all = S.purchase_orders.flatMap((po) => po.receipts.map((rc) => ({ rc, po })))
    .sort((a, b) => b.rc.received_at.localeCompare(a.rc.received_at) || b.rc.id.localeCompare(a.rc.id)).slice(0, 25);
  $("#recv-log").innerHTML = all.length ? `<table class="data compact"><tr><th>Received</th><th>Order</th><th>By</th><th>Result</th><th>Notes</th></tr>` +
    all.map(({ rc, po }) => {
      const dmg = rc.lines.reduce((a, l) => a + l.damaged, 0);
      const short = rc.lines.reduce((a, l) => a + Math.max(l.expected - l.good, 0), 0);
      const tags = [];
      if (!dmg && !short) tags.push(`<span class="pill good">all OK</span>`);
      if (dmg) tags.push(`<span class="pill bad">${dmg} damaged</span>`);
      if (short) tags.push(`<span class="pill warn">${short} short${rc.closed_short ? ", closed" : ""}</span>`);
      if (rc.late) tags.push(`<span class="pill bad">late</span>`);
      if (rc.package_damaged) tags.push(`<span class="pill bad">box damaged</span>`);
      if (rc.wrong_items) tags.push(`<span class="pill bad">wrong items</span>`);
      const notes = [rc.notes, ...rc.lines.filter((l) => l.note).map((l) => `${ingById(l.ingredient_id)?.name || l.ingredient_id}: ${l.note}`)].filter(Boolean);
      return `<tr><td>${esc(rc.received_at.replace("T", " "))}</td><td>${esc(po.id)} · ${esc(po.supplier)}${rc.reference ? `<div class="hint">${esc(rc.reference)}</div>` : ""}</td>
        <td>${esc(empById(rc.received_by)?.name || "–")}</td><td>${tags.join(" ")}</td><td class="hint">${notes.map(esc).join("<br>")}</td></tr>`;
    }).join("") + `</table>` : `<p class="hint">No deliveries checked in yet.</p>`;
}

// ---------------------------------------------------------- counts & waste
const countDraft = {};          // ingredient_id -> counted value (string as typed)
let wasteKind = "ingredient";
const staffOptions = (sel) => `<option value="">— choose —</option>` +
  S.employees.filter((e) => e.active).map((e) => `<option value="${esc(e.id)}" ${e.id === sel ? "selected" : ""}>${esc(e.name)}</option>`).join("");
const signed = (v, d = 2) => `<span class="${v < -1e-9 ? "neg" : v > 1e-9 ? "pos" : ""}">${v > 1e-9 ? "+" : ""}${(Math.round(v * 10 ** d) / 10 ** d).toLocaleString()}</span>`;
const signedMoney = (v) => `<span class="${v < -0.005 ? "neg" : v > 0.005 ? "pos" : ""}">${v < 0 ? "−" : v > 0 ? "+" : ""}${money(Math.abs(v))}</span>`;

function renderStock() {
  if (!$("#ct-by").value) $("#ct-by").innerHTML = staffOptions(me()?.employee_id || "");
  if (!$("#ws-by").value) $("#ws-by").innerHTML = staffOptions(me()?.employee_id || "");
  if (!$("#ct-at").value) $("#ct-at").value = nowLocal();
  const cats = unique(S.ingredients.map((i) => i.category));
  const cur = $("#ct-category").value;
  $("#ct-category").innerHTML = `<option value="">All categories</option>` + cats.map((c) => `<option ${c === cur ? "selected" : ""}>${esc(c)}</option>`).join("");
  renderCountTable();
  renderWasteForm();
  renderCountReport();
  renderWasteLog();
}

function renderCountTable() {
  const q = $("#ct-search").value.toLowerCase(), cat = $("#ct-category").value;
  const list = S.ingredients.filter((i) => (!cat || i.category === cat) && (!q || i.name.toLowerCase().includes(q)));
  $("#ct-table").innerHTML = `<tr><th>Ingredient</th><th class="r">System says</th><th>Counted</th><th class="r">Variance</th><th class="r">Value</th></tr>` +
    list.map((i) => {
      const v = countDraft[i.id];
      const has = v !== undefined && v !== "";
      const diff = has ? parseFloat(v) - i.on_hand : 0;
      return `<tr data-ing="${esc(i.id)}" class="${has ? "entered" : ""}"><td><b>${esc(i.name)}</b><div class="hint">${esc(i.category)} · 1 pkg = ${num(i.usable_per_package)} ${esc(i.unit)}</div></td>
        <td class="r">${num(i.on_hand)} ${esc(i.unit)}</td>
        <td><input type="number" min="0" step="any" class="ct-in" value="${has ? esc(v) : ""}"> <span class="hint">${esc(i.unit)}</span></td>
        <td class="r ct-var">${has ? signed(diff) : ""}</td><td class="r ct-val">${has ? signedMoney(diff * i.unit_cost) : ""}</td></tr>`;
    }).join("");
  updateCountSummary();
}

function updateCountSummary() {
  const entered = Object.entries(countDraft).filter(([, v]) => v !== "" && v !== undefined);
  const value = entered.reduce((a, [id, v]) => { const i = ingById(id); return a + (i ? (parseFloat(v) - i.on_hand) * i.unit_cost : 0); }, 0);
  $("#ct-summary").innerHTML = entered.length
    ? `${entered.length} item${entered.length === 1 ? "" : "s"} counted · total variance ${signedMoney(value)} at cost`
    : "No counts entered yet.";
  $("#ct-save").textContent = entered.length ? `Save count (${entered.length})` : "Save count";
}

$("#ct-search").addEventListener("input", renderCountTable);
$("#ct-category").addEventListener("change", renderCountTable);
$("#ct-table").addEventListener("input", (e) => {
  if (!e.target.matches(".ct-in")) return;
  const row = e.target.closest("tr");
  const i = ingById(row.dataset.ing);
  countDraft[i.id] = e.target.value;
  const has = e.target.value !== "";
  const diff = has ? parseFloat(e.target.value) - i.on_hand : 0;
  row.classList.toggle("entered", has);
  $(".ct-var", row).innerHTML = has ? signed(diff) : "";
  $(".ct-val", row).innerHTML = has ? signedMoney(diff * i.unit_cost) : "";
  updateCountSummary();
});
$("#ct-clear").addEventListener("click", () => { Object.keys(countDraft).forEach((k) => delete countDraft[k]); renderCountTable(); });
$("#ct-save").addEventListener("click", async () => {
  const lines = Object.entries(countDraft).filter(([, v]) => v !== "").map(([ingredient_id, counted]) => ({ ingredient_id, counted }));
  if (!lines.length) return toast("Enter at least one count", true);
  if (S.employees.some((e) => e.active) && !$("#ct-by").value) return toast("Choose who did the count", true);
  if (!confirm(`Save ${lines.length} counts? On-hand stock will be set to what you counted.`)) return;
  try {
    const res = await api("POST", "/api/counts", { lines, counted_by: $("#ct-by").value, at: $("#ct-at").value, notes: $("#ct-notes").value });
    Object.keys(countDraft).forEach((k) => delete countDraft[k]);
    $("#ct-notes").value = ""; $("#ct-at").value = nowLocal();
    renderCountTable();
    toast(`Count saved — variance ${money(res.saved.variance_value)}`);
  } catch (err) { toast(err.message, true); }
});

function renderWasteForm() {
  $$("#ws-kind button").forEach((b) => b.classList.toggle("on", b.dataset.k === wasteKind));
  const cur = $("#ws-what").value;
  $("#ws-what-label").firstChild.textContent = wasteKind === "item" ? "Drink " : "Ingredient ";
  $("#ws-what").innerHTML = `<option value="">— choose —</option>` + (wasteKind === "item"
    ? S.items.map((i) => `<option value="${esc(i.id)}">${esc(i.name)}</option>`)
    : S.ingredients.map((i) => `<option value="${esc(i.id)}">${esc(i.name)} (${esc(i.unit)})</option>`)).join("");
  if ([...$("#ws-what").options].some((o) => o.value === cur)) $("#ws-what").value = cur;
  if (!$("#ws-reason").options.length) $("#ws-reason").innerHTML = (S.waste_reasons || []).map((r) => `<option>${esc(r)}</option>`).join("");
  updateWasteCost();
}
function updateWasteCost() {
  const id = $("#ws-what").value, qty = parseFloat($("#ws-qty").value) || 0;
  const thing = wasteKind === "item" ? itemById(id) : ingById(id);
  $("#ws-qty-label").textContent = wasteKind === "item" ? "Drinks" : `Quantity${thing ? ` (${thing.unit})` : ""}`;
  $("#ws-cost").innerHTML = thing && qty ? `Cost of this waste: <b>${money(qty * (wasteKind === "item" ? thing.cost : thing.unit_cost))}</b>` : "Pick what was wasted and how much.";
}
$("#ws-kind").addEventListener("click", (e) => {
  const b = e.target.closest("[data-k]");
  if (!b) return;
  wasteKind = b.dataset.k;
  $("#ws-what").value = "";
  if (wasteKind === "item") $("#ws-reason").value = "remade drink";
  renderWasteForm();
});
["#ws-what", "#ws-qty"].forEach((s) => $(s).addEventListener("input", updateWasteCost));
$("#ws-save").addEventListener("click", async () => {
  const body = { kind: wasteKind, qty: $("#ws-qty").value, reason: $("#ws-reason").value, note: $("#ws-note").value, by: $("#ws-by").value };
  body[wasteKind === "item" ? "item_id" : "ingredient_id"] = $("#ws-what").value;
  try {
    const res = await api("POST", "/api/waste", body);
    $("#ws-qty").value = ""; $("#ws-note").value = "";
    toast(`Logged ${res.saved.name} — ${money(res.saved.cost)}`);
  } catch (err) { toast(err.message, true); }
});

function renderCountReport() {
  const counts = S.counts || [];
  $("#ct-report").innerHTML = counts.length ? counts.map((c) => {
    const lines = [...c.lines].sort((a, b) => a.variance * a.unit_cost - b.variance * b.unit_cost);
    return `<details ${c === counts[0] ? "open" : ""}><summary><b>${esc(c.at.replace("T", " "))}</b> · ${esc(empById(c.counted_by)?.name || "–")} ·
      ${c.lines.length} items · variance ${signedMoney(c.variance_value)}${c.notes ? ` · <span class="hint">${esc(c.notes)}</span>` : ""}</summary>
      <table class="data compact"><tr><th>Ingredient</th><th class="r">Expected</th><th class="r">Counted</th><th class="r">Variance</th><th class="r">Value</th><th class="r">% of usage</th></tr>
      ${lines.map((l) => {
        const ing = ingById(l.ingredient_id) || { name: l.ingredient_id, unit: "" };
        const share = l.theoretical_usage ? -l.variance / l.theoretical_usage : null;
        return `<tr><td>${esc(ing.name)}</td><td class="r">${num(l.expected)} ${esc(ing.unit)}</td><td class="r">${num(l.counted)}</td>
          <td class="r">${signed(l.variance)}</td><td class="r">${signedMoney(l.variance * l.unit_cost)}</td>
          <td class="r">${share === null ? "–" : `<span class="${share > 0.05 ? "neg" : ""}">${share > 0 ? "" : "+"}${pct(Math.abs(share))}${share > 0 ? " missing" : " extra"}</span>`}</td></tr>`;
      }).join("")}</table></details>`;
  }).join("") : `<p class="hint">No counts yet. Count a few high-value items (fruit, protein, cups) weekly to start.</p>`;
}

function renderWasteLog() {
  const all = S.waste || [];
  const weekStartIso = mondayOf(todayIso());
  const week = all.filter((w) => w.at.slice(0, 10) >= weekStartIso);
  const byReason = {};
  week.forEach((w) => (byReason[w.reason] = (byReason[w.reason] || 0) + w.cost));
  const total = week.reduce((a, w) => a + w.cost, 0);
  const max = Math.max(...Object.values(byReason), 0.01);
  $("#ws-summary").innerHTML = week.length
    ? `<div class="kpi-v">${money(total)}</div><div class="hint">${week.length} entries since Monday</div>` +
      Object.entries(byReason).sort((a, b) => b[1] - a[1]).map(([r, v]) =>
        `<div class="bar-row"><span>${esc(r)}</span><div class="bar" style="width:${(v / max) * 100}%"></div><b>${money(v)}</b></div>`).join("")
    : `<p class="hint">Nothing logged this week.</p>`;
  $("#ws-log").innerHTML = all.length ? `<table class="data compact"><tr><th>When</th><th>What</th><th class="r">Qty</th><th>Reason</th><th>By</th><th class="r">Cost</th><th>Note</th><th></th></tr>` +
    all.slice(0, 40).map((w) => `<tr><td>${esc(w.at.replace("T", " "))}</td><td>${esc(w.name)}${w.kind === "item" ? ' <span class="pill">drink</span>' : ""}</td>
      <td class="r">${num(w.qty)} ${esc(w.kind === "item" ? "" : w.unit || "")}</td><td>${esc(w.reason)}</td><td>${esc(empById(w.by)?.name || "–")}</td>
      <td class="r">${money(w.cost)}</td><td class="hint">${esc(w.note)}</td>
      <td><button class="ghost small" data-unwaste="${esc(w.id)}" title="Remove this entry and put the stock back">Remove</button></td></tr>`).join("") + `</table>`
    : `<p class="hint">No waste logged yet.</p>`;
}
$("#ws-log").addEventListener("click", async (e) => {
  const id = e.target.dataset.unwaste;
  if (!id || !confirm("Remove this waste entry and put the stock back?")) return;
  try { await api("DELETE", `/api/waste/${id}`); toast("Waste entry removed"); } catch (err) { toast(err.message, true); }
});

// ------------------------------------------------------------- sales import
const IMP_FIELDS = [["date", "Date"], ["time", "Time"], ["item", "Item name"], ["size", "Size / variation"], ["qty", "Quantity"], ["type", "Payment / refund type"]];
let imp = null;  // { text, filename, preview, mapping, aliases }

async function previewImport() {
  try {
    const res = await fetch("/api/sales-import/preview", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "app" },
      body: JSON.stringify({ csv: imp.text, mapping: imp.mapping, aliases: imp.aliases }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    imp.preview = data;
    imp.mapping = data.mapping;
    renderImport();
  } catch (err) { toast(err.message, true); }
}

function renderImport() {
  const box = $("#imp-preview");
  if (!imp || !imp.preview) { box.innerHTML = ""; return; }
  const p = imp.preview;
  const opts = (sel) => `<option value="">(none)</option>` + p.headers.map((h) => `<option ${h === sel ? "selected" : ""}>${esc(h)}</option>`).join("");
  const itemOpts = (sel) => `<option value="">— choose a menu item —</option>` +
    S.items.map((i) => `<option value="${esc(i.id)}" ${i.id === sel ? "selected" : ""}>${esc(i.name)}${i.size ? ` (${esc(i.size)})` : ""}</option>`).join("") +
    `<option value="__ignore__" ${sel === "__ignore__" ? "selected" : ""}>Ignore — not a drink (gift card, merch…)</option>`;
  const unmatched = p.groups.filter((g) => !g.item_id).length;
  const drinks = p.groups.filter((g) => g.item_id && g.item_id !== "__ignore__").reduce((a, g) => a + g.qty, 0);
  const skipped = Object.entries(p.skipped).map(([why, n]) => `${n} ${esc(why)}`).join(", ");
  box.innerHTML = `
    <h3>${esc(imp.filename)} <span class="hint">· ${p.rows} rows${p.first ? ` · ${esc(p.first)}${p.last !== p.first ? ` to ${esc(p.last)}` : ""}` : ""}</span></h3>
    ${p.already_imported ? `<div class="warn-line">This exact file was already imported on ${esc(p.already_imported.at.slice(0, 10))} (${esc(p.already_imported.id)}). Importing again would count those sales twice.</div>` : ""}
    <div class="imp-map">${IMP_FIELDS.map(([f, label]) => `<label>${label}${["date", "item", "qty"].includes(f) ? " *" : ""}
      <select data-map="${f}">${opts(p.mapping[f])}</select></label>`).join("")}</div>
    ${p.missing.length ? `<div class="warn-line">Choose the column for: ${p.missing.map(esc).join(", ")}</div>` : `
    <table class="data compact"><tr><th>Name in your till system</th><th class="r">Rows</th><th class="r">Sold</th><th>Counts as</th><th></th></tr>
      ${p.groups.map((g) => `<tr class="${g.item_id ? "" : "row-bad"}"><td><b>${esc(g.pos_name)}</b></td><td class="r">${g.rows}</td><td class="r">${num(g.qty)}</td>
        <td><select data-alias="${esc(g.pos_name)}">${itemOpts(g.item_id)}</select></td>
        <td class="hint">${esc(g.matched_by || (g.item_id ? "" : "needs a match"))}</td></tr>`).join("")}
    </table>
    <div class="calc">${num(drinks)} drinks will be recorded${skipped ? ` · skipped: ${skipped}` : ""}.
      ${unmatched ? `<b class="bad-text">${unmatched} name${unmatched === 1 ? "" : "s"} still need a match or "Ignore".</b>` : "Your matches are remembered for next time."}</div>
    <div class="row-gap">
      <button class="primary" id="imp-go" ${unmatched ? "disabled" : ""}>Import ${num(drinks)} drinks</button>
      <button class="ghost" id="imp-cancel">Cancel</button>
    </div>`}`;
}

function renderImportHistory() {
  const list = S.imports || [];
  $("#imp-history").innerHTML = list.length ? `<table class="data compact"><tr><th>Imported</th><th>File</th><th>Sales dates</th><th class="r">Drinks</th><th>Skipped</th><th></th></tr>` +
    list.map((i) => `<tr class="${i.undone ? "muted" : ""}"><td>${esc(i.at.replace("T", " "))}</td><td>${esc(i.filename || i.id)}</td>
      <td>${esc(i.first || "")}${i.last && i.last !== i.first ? ` to ${esc(i.last)}` : ""}</td><td class="r">${num(i.drinks)}</td>
      <td class="hint">${Object.entries(i.skipped || {}).map(([w, n]) => `${n} ${esc(w)}`).join(", ") || "–"}</td>
      <td>${i.undone ? `<span class="pill">undone</span>` : `<button class="ghost small" data-undo="${esc(i.id)}">Undo</button>`}</td></tr>`).join("") + `</table>`
    : `<p class="hint">No imports yet.</p>`;
}

$("#imp-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  imp = { text: await file.text(), filename: file.name, mapping: null, aliases: {}, preview: null };
  previewImport();
});
$("#imp-preview").addEventListener("change", (e) => {
  if (e.target.dataset.map) {
    imp.mapping = { ...imp.mapping, [e.target.dataset.map]: e.target.value };
    if (!e.target.value) delete imp.mapping[e.target.dataset.map];
    previewImport();
  }
  if (e.target.dataset.alias !== undefined) {
    imp.aliases[e.target.dataset.alias] = e.target.value;
    previewImport();
  }
});
$("#imp-preview").addEventListener("click", async (e) => {
  if (e.target.id === "imp-cancel") { imp = null; $("#imp-file").value = ""; renderImport(); }
  if (e.target.id === "imp-go") {
    const again = imp.preview.already_imported;
    if (again && !confirm("This file was imported before. Import it again anyway? Sales would be counted twice.")) return;
    try {
      const res = await api("POST", "/api/sales-import", { csv: imp.text, mapping: imp.mapping, aliases: imp.aliases, filename: imp.filename, force: !!again });
      toast(`Imported ${num(res.imported.drinks)} drinks — stock updated`);
      imp = null; $("#imp-file").value = ""; renderImport();
    } catch (err) { toast(err.message, true); }
  }
});
$("#imp-history").addEventListener("click", async (e) => {
  const id = e.target.dataset.undo;
  if (!id || !confirm(`Undo import ${id}? Its sales are removed and their ingredients put back in stock.`)) return;
  try { await api("POST", `/api/sales-import/${id}/undo`); toast(`${id} undone`); } catch (err) { toast(err.message, true); }
});

// ---------------------------------------------------------------- settings
function renderSettings() {
  const f = $("#settings-form");
  if (!f.contains(document.activeElement)) {
    f.elements.business_name.value = S.settings?.business_name || "";
    f.elements.target_food_cost.value = +(target() * 100).toFixed(1);
  }
  $(".brand-name").textContent = S.settings?.business_name || "Menu & Inventory";
}
$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target.elements;
  try {
    await api("PUT", "/api/settings", { business_name: f.business_name.value, target_food_cost: f.target_food_cost.value });
    toast("Settings saved");
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
