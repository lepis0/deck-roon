"use strict";

const $ = (sel) => document.querySelector(sel);
let state = null;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) node.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined) node.append(c);
  return node;
}

let toastTimer;
function toast(message, error = false) {
  const t = $("#toast");
  t.textContent = message;
  t.className = "show" + (error ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = ""), error ? 6000 : 3000);
}

async function api(method, path, body) {
  const r = await fetch(path, {
    method,
    headers: body ? { "content-type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `${r.status}`);
  return data;
}

function savedZone() {
  try { return localStorage.getItem("deck.zone"); } catch { return null; }
}

function rememberZone(id) {
  try { localStorage.setItem("deck.zone", id); } catch { /* private window */ }
}

function renderStatus() {
  $("#round").textContent = state.curated ? state.round_label : "";

  const roon = $("#roon-status");
  roon.className = "chip " + (state.roon.connected ? "ok" : "warn");
  roon.textContent = state.roon.connected ? "Roon" : `Roon: ${state.roon.status.split(":")[0]}`;
  roon.title = state.roon.status;

  const tidal = $("#tidal-status");
  tidal.className = "chip " + (state.tidal.signed_in ? "ok" : "warn");
  tidal.replaceChildren(state.tidal.signed_in
    ? "TIDAL"
    : el("a", { href: "#", onclick: (e) => { e.preventDefault(); $("#tidal-dialog").showModal(); } },
        "Kirjaudu TIDALiin"));

  const select = $("#zone");
  const zonesKey = JSON.stringify(state.roon.zones.map((z) => [z.id, z.name, z.state]));
  if (select.dataset.key === zonesKey) return;
  select.dataset.key = zonesKey;
  const current = select.value || savedZone();
  select.replaceChildren(...state.roon.zones.map((z) =>
    el("option", { value: z.id }, z.name + (z.state === "playing" ? " ♪" : ""))));
  if (!state.roon.zones.length) select.append(el("option", { value: "" }, "ei zoneja"));
  if (current && state.roon.zones.some((z) => z.id === current)) select.value = current;
}

async function withButton(button, fn) {
  button.disabled = true;
  try { await fn(); } catch (e) { toast(e.message, true); } finally { button.disabled = false; }
}

async function play(albumId, action, button) {
  const zone = $("#zone").value;
  if (!zone) return toast("Valitse ensin Roon-zone", true);
  await withButton(button, async () => {
    const r = await api("POST", "/api/play", { zone_id: zone, album_id: albumId, action });
    const verb = { play: "Soitetaan", queue: "Jonossa", next: "Seuraavana" }[action];
    toast(`${verb}: ${r.message}`);
  });
}

async function toggleShelf(album, button) {
  const onShelf = state.shelf.includes(album.id);
  await withButton(button, async () => {
    if (onShelf) {
      await api("DELETE", `/api/shelf/${album.id}`);
      toast("Poistettu hyllystä");
    } else {
      const r = await api("POST", "/api/shelf", { album_id: album.id });
      toast(`Hyllyssä – ${r.message}`);
    }
    await refresh();
  });
}

async function reject(album, button) {
  await withButton(button, async () => {
    await api("POST", "/api/reject", { album_id: album.id });
    toast(`${album.album} poistettu. Seuraava lista välttää tällaisia.`);
    await refresh();
  });
}

function albumCard(album, index) {
  const onShelf = state.shelf.includes(album.id);
  const shelfButton = el("button", { class: onShelf ? "shelved" : "",
    title: "Lisää TIDAL-suosikkeihin, jolloin albumi näkyy Roonin kirjastossa" },
    onShelf ? "✓ Hyllyssä" : "★ Hyllyyn");
  shelfButton.addEventListener("click", () => toggleShelf(album, shelfButton));

  const playButton = el("button", { class: "primary" }, "▶ Soita");
  playButton.addEventListener("click", () => play(album.id, "play", playButton));
  const queueButton = el("button", {}, "+ Jonoon");
  queueButton.addEventListener("click", () => play(album.id, "queue", queueButton));
  const rejectButton = el("button", { class: "reject", title: "Pois listalta; seuraava lista välttää tällaisia" },
    "✕ Ei minulle");
  rejectButton.addEventListener("click", () => reject(album, rejectButton));

  return el("article", { class: "album" + (onShelf ? " on-shelf" : "") },
    album.cover
      ? el("img", { class: "cover", src: album.cover, alt: "", loading: "lazy" })
      : el("div", { class: "cover" }),
    el("div", { class: "meta" },
      el("div", { class: "title" }, el("span", { class: "num" }, String(index + 1)), album.album),
      el("div", { class: "artist" }, album.artist, album.year ? el("span", { class: "year" }, ` · ${album.year}`) : null),
      album.reason ? el("p", { class: "reason" }, album.reason) : null,
      el("div", { class: "actions" }, playButton, queueButton, shelfButton, rejectButton,
        el("a", { href: album.url, target: "_blank", rel: "noopener" }, "TIDAL ↗"))));
}

function renderWeek() {
  const box = $("#albums");
  const albums = state.curated?.albums || [];
  if (!state.curated) {
    box.replaceChildren(el("p", { class: "empty" },
      "Listaa ei ole vielä tehty. Aja palvelimella viikkoajo (deck-curate), niin viikon 20 albumia ilmestyvät tähän."));
  } else if (!albums.length) {
    box.replaceChildren(el("p", { class: "empty" }, "Kaikki tämän viikon albumit on käyty läpi."));
  } else {
    box.replaceChildren(...albums.map(albumCard));
  }
  $("#make-playlist").hidden = !state.curated || !state.tidal.signed_in;
  $("#make-playlist").textContent = state.curated?.playlist_id
    ? "Tee viikon TIDAL-soittolista uudelleen" : "Luo viikon TIDAL-soittolista";
}

function historyRow(album) {
  const tag = album.on_shelf ? el("span", { class: "tag good" }, "hyllyssä")
    : album.rejected ? el("span", { class: "tag bad" }, "ei minulle") : null;
  const button = el("button", {}, "▶");
  button.addEventListener("click", () => play(album.id, "play", button));
  return el("div", { class: "row" },
    el("span", { class: "name" }, `${album.artist} – ${album.album}`, album.year ? ` (${album.year})` : ""),
    tag, button);
}

async function renderHistory() {
  const data = await api("GET", "/api/history");
  const box = $("#history");
  if (!data.rounds.length) {
    box.replaceChildren(el("p", { class: "empty" }, "Ei vielä aiempia listoja."));
    return;
  }
  box.replaceChildren(...data.rounds.map((r) => el("div", { class: "round-block" },
    el("h3", {}, r.label), el("div", { class: "rows" }, r.albums.map(historyRow)))));
}

async function renderShelf() {
  const data = await api("GET", "/api/history");
  const box = $("#shelf");
  if (!data.shelf.length) {
    box.replaceChildren(el("p", { class: "empty" },
      "Hylly on tyhjä. ★ Hyllyyn lisää albumin tänne ja TIDAL-suosikkeihin, ja seuraava lista oppii siitä."));
    return;
  }
  box.replaceChildren(el("div", { class: "rows" }, data.shelf.map((a) => historyRow({ ...a, on_shelf: false }))));
}

async function refresh(statusOnly = false) {
  try {
    state = await api("GET", "/api/state");
  } catch (e) {
    toast(`Palvelin ei vastaa: ${e.message}`, true);
    return;
  }
  renderStatus();
  if (!statusOnly) renderWeek();
}

function showTab(name) {
  for (const b of document.querySelectorAll(".tabs button")) b.classList.toggle("active", b.dataset.tab === name);
  for (const id of ["week", "history", "shelf"]) $("#" + id).hidden = id !== name;
  if (name === "history") renderHistory().catch((e) => toast(e.message, true));
  if (name === "shelf") renderShelf().catch((e) => toast(e.message, true));
}

document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
$("#zone").addEventListener("change", (e) => rememberZone(e.target.value));
$("#make-playlist").addEventListener("click", (e) => withButton(e.target, async () => {
  toast("Luodaan soittolistaa…");
  const r = await api("POST", "/api/playlist");
  toast(r.message);
  await refresh();
}));
$("#tidal-finish").addEventListener("click", async (e) => {
  const url = $("#tidal-url").value.trim();
  if (!url) return;
  e.preventDefault();
  try {
    await api("POST", "/api/tidal/finish", { url });
    $("#tidal-dialog").close();
    toast("TIDAL-kirjautuminen tallennettu");
    await refresh();
  } catch (err) {
    toast(err.message, true);
  }
});

refresh();
// Roon zones and the pairing status change in the background.
setInterval(() => { if (!document.hidden) refresh(true); }, 15000);
