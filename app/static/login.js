"use strict";
const $ = (s) => document.querySelector(s);

async function post(url, body) {
  const res = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "app" }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

let tempPassword = null;

function showChange(knownCurrent) {
  tempPassword = knownCurrent;
  $("#login-form").hidden = true;
  $("#change-form").hidden = false;
  $("#change-current-label").hidden = !!knownCurrent;  // just typed it: don't ask again
  $(knownCurrent ? "#change-form [name=new]" : "#change-form [name=current]").focus();
}

fetch("/api/setup-needed").then((r) => r.json()).then((d) => {
  if (d.setup) { $("#login-form").hidden = true; $("#setup-form").hidden = false; $("#setup-form [name=name]").focus(); }
  else if (location.hash === "#change") showChange(null);
});

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target.elements;
  try {
    const res = await post("/api/login", { username: f.username.value, password: f.password.value });
    if (res.user.must_change) return showChange(f.password.value);
    location.href = "/";
  } catch (err) { $("#login-error").textContent = err.message; f.password.value = ""; f.password.focus(); }
});

$("#change-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target.elements;
  if (f.new.value !== f.confirm.value) { $("#login-error").textContent = "The new passwords don't match"; return; }
  try {
    await post("/api/me/password", { current: tempPassword ?? f.current.value, new: f.new.value });
    location.href = "/";
  } catch (err) { $("#login-error").textContent = err.message; }
});

$("#setup-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target.elements;
  if (f.password.value !== f.confirm.value) { $("#login-error").textContent = "The passwords don't match"; return; }
  try {
    await post("/api/setup", { name: f.name.value, username: f.username.value, password: f.password.value });
    location.href = "/";
  } catch (err) { $("#login-error").textContent = err.message; }
});
