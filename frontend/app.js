// WhyBase UI: state, chat, desk panels, evidence tabs. Plain ES modules, no build step.
import { api, setGraphDownHandler } from "./api.js";
import * as graph from "./graph.js";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

const state = {
  entities: { systems: [], people: [], projects: [], decisions: [] },
  last: null,          // last chat response
  pending: false,
  staleCount: null,
  graphShown: [],      // highlight ids currently on the canvas
};

const SUGGESTIONS = [
  "Why do we use Kafka for the event bus?",
  "Which docs are out of date?",
  "Who knows payments-ledger?",
  "What breaks if we reverse D-002?",
  "What did we use for search on 1 Jan 2026?",
  "Who knows quantum-cache?",
];
const OUTCOMES = {
  answered: { icon: "✓", stamp: "Answered", label: "Answered with path" },
  stale_warning: { icon: "⚠", stamp: "Out of date", label: "Answered — but out of date" },
  no_connection: { icon: "∅", stamp: "Nothing connects", label: "Nothing connects" },
  unknown: { icon: "✕", stamp: "Unknown", label: "Unknown" },
};
const TEAMS = new Set(["Platform", "Payments", "Growth", "Search", "Mobile", "Security"]);

// ---------------------------------------------------------------- tiny DOM helpers

function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const ICONS = {
  doc: "M3 1.5h6l3 3v10H3z M9 1.5v3h3 M5 8h5 M5 10.5h5",
  chat: "M2 3h11v7H7l-3 3v-3H2z",
  ticket: "M1.5 4h12v2.5a1.5 1.5 0 0 0 0 3V12h-12V9.5a1.5 1.5 0 0 0 0-3z M9 4v8",
  adr: "M3 1.5h9v13H3z M5.5 6l1.5 1.5 3-3 M5.5 10.5h4",
};
function icon(kind) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 15 16");
  svg.setAttribute("width", "14");
  svg.setAttribute("height", "14");
  svg.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(ns, "path");
  p.setAttribute("d", ICONS[kind] || ICONS.doc);
  p.setAttribute("fill", "none");
  p.setAttribute("stroke", "#2A2420");
  p.setAttribute("stroke-width", "1.3");
  p.setAttribute("stroke-linejoin", "round");
  svg.append(p);
  return svg;
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}
const today = () => new Date().toISOString().slice(0, 10);
const isDesktop = () => window.matchMedia("(min-width: 1200px)").matches;
const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** "Move the event bus from RabbitMQ to Kafka" -> "Kafka" (the last proper noun), for compact rows. */
function keyword(summary = "") {
  const words = summary.split(/\s+/).slice(1).filter((w) => /^[A-Z]/.test(w));
  return words.length ? words[words.length - 1].replace(/[.,]$/, "") : summary.split(/\s+/).slice(0, 3).join(" ");
}

function kindOf(id) {
  if (/^D-\d+$/.test(id)) return "Decision";
  if (/^S-/.test(id)) return "Source";
  if (state.entities.systems.some((s) => s.name === id)) return "System";
  if (state.entities.people.some((p) => p.name === id)) return "Person";
  if (state.entities.projects.some((p) => p.name === id)) return "Project";
  if (TEAMS.has(id)) return "Team";
  return "System";
}
function statusOf(id, kind) {
  if (kind === "Decision") return state.entities.decisions.find((d) => d.id === id)?.status;
  if (kind === "Person") return state.entities.people.find((p) => p.name === id)?.status;
  return null;
}

/** A coloured entity chip. Clicking it highlights the node in the graph. */
function chip(id, kind = kindOf(id), status = null, { asButton = true, text } = {}) {
  status = status ?? statusOf(id, kind);
  const cls = `chip k-${kind}${status === "superseded" ? " superseded" : ""}${status === "left" ? " left" : ""}`;
  const label = text || id;
  if (!asButton) return h("span", { class: cls }, label);
  return h("button", {
    type: "button", class: cls, title: `${kind}${status ? " · " + status : ""} — show in graph`,
    onclick: (e) => { e.stopPropagation(); focusNodes([id]); },
  }, label);
}
const leftStamp = () => h("span", { class: "left-stamp", title: "Left the company" }, "LEFT");

function toast(message) {
  const t = h("div", { class: "toast" }, message);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), 3500);
}

function listError(list, message, retry) {
  list.replaceChildren(h("li", { class: "list-error" }, h("span", {}, message),
    h("button", { type: "button", class: "btn btn-small", onclick: retry }, "Retry")));
}

// ---------------------------------------------------------------- header

async function loadHealth() {
  try {
    const hres = await api.health();
    setGraphStatus(hres.falkordb === "ok");
    const pill = $("#pill-llm");
    pill.hidden = false;
    const paused = hres.llm === "rate_limited";
    pill.classList.toggle("online", hres.llm === "online");
    pill.classList.toggle("paused", paused);
    pill.textContent = { online: "LLM online", rate_limited: "LLM quota hit · offline" }[hres.llm] || "Offline mode";
    pill.title = hres.llm === "online" ? `Model: ${hres.model}`
      : paused ? `${hres.model} is rate-limited. Retrying in about ${Math.ceil(hres.llm_retry_in / 60)} min; answers use the offline router meanwhile.`
      : "No LLM key set: keyword router + template sentences";
    return hres.falkordb === "ok";
  } catch {
    setGraphStatus(false);
    return false;
  }
}

function setGraphStatus(ok) {
  const pill = $("#pill-graph");
  pill.classList.toggle("ok", ok);
  pill.classList.toggle("down", !ok);
  pill.querySelector(".pill-text").textContent = ok ? "Graph connected" : "Graph down";
  $("#banner").hidden = ok;
}

async function loadStats() {
  try {
    const s = await api.stats();
    const parts = [["people", s.people], ["systems", s.systems], ["sources", s.sources], ["decisions", s.decisions]];
    $("#stats").replaceChildren(...parts.flatMap(([k, v], i) => [i ? " · " : "", h("b", {}, v), ` ${k}`]));
  } catch { /* banner covers it */ }
}

async function loadEntities() {
  try {
    state.entities = await api.entities();
  } catch { return; }
  const author = $("#ingest-author");
  const keep = author.value;
  author.replaceChildren(h("option", { value: "" }, "Detect from message"),
    ...activePeople().map((p) => h("option", { value: p }, p)));
  author.value = keep;
  const tt = $("#tt-system");
  const keepSys = tt.value || "event-bus";
  tt.replaceChildren(...state.entities.systems.map((s) => h("option", { value: s.name }, s.name)));
  tt.value = keepSys;
}
const activePeople = () => state.entities.people.filter((p) => p.status === "active").map((p) => p.name);

function wireReset() {
  const btn = $("#reset-btn"), pop = $("#reset-pop");
  const close = () => { pop.hidden = true; btn.setAttribute("aria-expanded", "false"); };
  btn.addEventListener("click", () => {
    pop.hidden = !pop.hidden;
    btn.setAttribute("aria-expanded", String(!pop.hidden));
    if (!pop.hidden) $("#reset-confirm").focus();
  });
  pop.querySelector("[data-close]").addEventListener("click", close);
  document.addEventListener("click", (e) => { if (!pop.hidden && !e.target.closest(".reset-wrap")) close(); });
  pop.addEventListener("keydown", (e) => { if (e.key === "Escape") { close(); btn.focus(); } });
  $("#reset-confirm").addEventListener("click", async () => {
    close();
    try {
      await api.reset();
      $("#proposal").replaceChildren();
      graph.showGraph({ nodes: [], edges: [] });
      $("#graph-empty").hidden = false;
      $("#drawer").hidden = true;
      await Promise.all([loadStats(), loadEntities(), loadStale(), loadRisk(), reloadLoadBearing()]);
      toast("Graph reset to the original Kettle Labs data.");
    } catch (err) { toast(err.message); }
  });
}

// ---------------------------------------------------------------- views + tabs

function setView(view) {
  $("#layout").dataset.view = view;
  $$("[data-view-btn]").forEach((b) => {
    const on = b.dataset.viewBtn === view;
    if (!b.closest(".tabbar")) b.setAttribute("aria-selected", String(on));
    else if (on) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  if (view === "evidence") requestAnimationFrame(graph.resize);
}

function selectTab(name) {
  ["graph", "path", "trace"].forEach((t) => {
    $(`#tab-${t}`).setAttribute("aria-selected", String(t === name));
    $(`#pane-${t}`).hidden = t !== name;
  });
  if (name === "graph") requestAnimationFrame(graph.resize);
}

function wireTabs() {
  $$("[data-view-btn]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.viewBtn)));
  ["graph", "path", "trace"].forEach((t) => $(`#tab-${t}`).addEventListener("click", () => selectTab(t)));
  $(".tabs").addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
    const tabs = ["graph", "path", "trace"];
    const cur = tabs.findIndex((t) => $(`#tab-${t}`).getAttribute("aria-selected") === "true");
    const next = tabs[(cur + (e.key === "ArrowRight" ? 1 : 2)) % 3];
    selectTab(next);
    $(`#tab-${next}`).focus();
  });
}

// ---------------------------------------------------------------- graph panel

/** Highlight these nodes; fetch the subgraph if they are not all on the canvas. FR-16. */
async function focusNodes(ids, { pulse = [], steps = null } = {}) {
  if (!isDesktop()) setView("evidence");
  selectTab("graph");
  if (steps) renderPaths(steps);
  if (graph.focusIfPresent(ids)) { graph.pulseNodes(pulse); return; }
  await showSubgraph(ids, { pulse });
}

async function showSubgraph(ids, { pulse = [] } = {}) {
  if (!ids.length) return;
  try {
    const data = await api.graph(ids);
    $("#graph-empty").hidden = data.nodes.length > 0;
    state.graphShown = ids;
    graph.showGraph(data, ids, { pulse });
  } catch (err) { toast(err.message); }
}

const PROP_LABELS = [["title", "Title"], ["summary", "Summary"], ["description", "About"], ["role", "Role"],
  ["status", "Status"], ["kind", "Kind"], ["at", "Date"], ["superseded_at", "Superseded"], ["left_at", "Left on"],
  ["reviewed_at", "Reviewed"], ["reviewed_by", "Reviewed by"]];

function openDrawer(node) {
  const drawer = $("#drawer");
  if (!node) { drawer.hidden = true; return; }
  const p = node.props || {};
  const dl = h("dl", {}, PROP_LABELS.filter(([k]) => p[k]).flatMap(([k, label]) =>
    [h("dt", {}, label), h("dd", {}, /_at$|^at$/.test(k) ? fmtDate(p[k]) : String(p[k]))]));
  const actions = h("div", { class: "actions" });
  const add = (label, fn) => actions.append(h("button", { type: "button", class: "btn btn-small", onclick: fn }, label));
  if (node.kind === "System") {
    add("Why?", () => ask(`Why does ${node.id} work the way it does?`));
    add("Who knows?", () => ask(`Who knows ${node.id}?`));
  }
  if (node.kind === "Decision") add("What breaks?", () => ask(`What breaks if we reverse ${node.id}?`));
  let quote = null;
  if (node.kind === "Source" && p.text) {
    quote = h("blockquote", { hidden: true }, p.text);
    add("Open text", (e) => { quote.hidden = !quote.hidden; e.target.textContent = quote.hidden ? "Open text" : "Hide text"; });
  }
  $("#drawer-body").replaceChildren(
    h("h3", {}, node.label),
    h("p", {}, chip(node.kind, node.kind, node.status, { asButton: false, text: node.kind + (node.status ? ` · ${node.status}` : "") })),
    dl, actions, ...(quote ? [quote] : []));
  drawer.hidden = false;
}

function wireGraph() {
  const ok = graph.initGraph($("#cy"), { onSelect: openDrawer });
  if (!ok) $("#graph-empty").textContent = "The graph library didn't load. The Path tab still shows every answer as text.";
  $("#g-fit").addEventListener("click", graph.fit);
  $("#g-zin").addEventListener("click", () => graph.zoom(1.25));
  $("#g-zout").addEventListener("click", () => graph.zoom(0.8));
  $("#g-all").addEventListener("click", async () => {
    try {
      const data = await api.graphAll();
      $("#graph-empty").hidden = true;
      graph.showGraph(data, state.graphShown, { fitAll: true });
    } catch (err) { toast(err.message); }
  });
  $("#drawer-close").addEventListener("click", () => { $("#drawer").hidden = true; });
  let t;
  window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(graph.resize, 150); });
}

// ---------------------------------------------------------------- path + trace tabs

function renderPaths(steps) {
  const body = $("#path-body");
  if (!steps || !steps.length) {
    body.replaceChildren(h("p", { class: "muted" }, "This answer has no path: no traversal ran, or it returned nothing."));
    return;
  }
  body.replaceChildren(...steps.map((path, i) => h("section", {},
    h("p", { class: "path-title" }, `Path ${i + 1}`),
    h("ol", { class: "steps" }, path.flatMap((s, j) => [
      j && s.rel ? h("li", { class: "rel", "aria-label": `${s.dir === "←" ? "pointed to by" : "points to"} ${s.rel}` },
        `${s.dir === "←" ? "↑" : "↓"} ${s.rel.replace(/_/g, " ")}`) : null,
      h("li", { class: "node" }, chip(s.id, s.kind, s.status), s.at ? h("time", { datetime: s.at }, fmtDate(s.at)) : null),
    ])))));
}

function renderTrace(r) {
  const o = OUTCOMES[r.outcome];
  const rows = r.trace.map((t) => h("tr", { class: t.note ? "note" : "" },
    h("td", { class: "mono" }, t.tool),
    h("td", { class: "mono args", title: JSON.stringify(t.args || {}) }, t.note || JSON.stringify(t.args || {})),
    h("td", { class: "mono" }, t.rows ?? ""),
    h("td", { class: "mono" }, t.ms != null ? `${t.ms}` : ""),
    h("td", {}, t.query ? h("button", { type: "button", class: "btn-text", onclick: () => copyCypher(t.query) }, "Copy Cypher") : null)));
  $("#trace-body").replaceChildren(
    h("div", { class: "trace-head" },
      h("span", { class: `stamp ${r.outcome}` }, `${o.icon} ${o.stamp}`),
      h("span", { class: "mono" }, `check: ${r.check}`),
      h("span", { class: "mono muted" }, `mode: ${r.mode}`)),
    rows.length
      ? h("table", { class: "trace-table" },
          h("thead", {}, h("tr", {}, ["tool", "arguments", "rows", "ms", ""].map((c) => h("th", { scope: "col" }, c)))),
          h("tbody", {}, rows))
      : h("p", { class: "muted" }, "No query ran for this question."));
}

async function copyCypher(name) {
  try {
    const text = await api.query(name);
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
    else {
      const ta = h("textarea", { style: "position:fixed;opacity:0" }, text);
      document.body.append(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    toast(`Copied the ${name} query.`);
  } catch (err) { toast(err.message || "Couldn't copy."); }
}

// ---------------------------------------------------------------- chat

function addMessage(el) {
  $("#empty-chat")?.remove();
  $("#messages").append(el);
  el.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "end" });
  return el;
}

function richText(text) {
  // `code` spans only; everything else is plain text.
  return text.split(/(`[^`]+`)/).map((part) => part.startsWith("`") && part.endsWith("`") ? h("code", {}, part.slice(1, -1)) : part);
}

function pathLine(steps) {
  const shown = steps.slice(0, 4);
  return h("div", { class: "pathline", "aria-label": "Path behind this answer" },
    shown.map((path) => h("div", { class: "path" }, path.flatMap((s, j) => [
      j ? h("span", { class: "edge", "aria-hidden": "true" }, s.dir || "→", s.rel ? h("small", {}, s.rel.replace(/_/g, " ")) : null, s.dir || "→") : null,
      chip(s.id, s.kind, s.status),
    ]))),
    steps.length > 4 ? h("span", { class: "more-paths" }, `+${steps.length - 4} more in the Path tab`) : null);
}

function footer(r) {
  const ms = r.trace.reduce((a, t) => a + (t.ms || 0), 0);
  const n = r.tools.filter((t) => t.tool !== "none").length;
  const ran = r.trace.some((t) => !t.tool.startsWith("resolve_") && t.tool !== "llm");
  let check = `check ${r.check}`;
  if (r.check.startsWith("replaced: ")) check = `check replaced the model's sentence (named "${r.check.slice(10)}", not in results)`;
  if (r.outcome === "unknown") check = ran ? "check not needed" : "no traversal ran";
  if (r.outcome === "no_connection") check = "traversal returned 0 rows";
  const fell = r.trace.find((t) => t.tool === "llm");
  const fellText = fell && /rate-limited/.test(fell.note || "") ? " · LLM rate-limited, offline router used" : " · LLM failed, offline router used";
  return h("div", { class: "msg-foot" },
    `${ms.toFixed(1)} ms · ${n} tool${n === 1 ? "" : "s"} · `,
    h("span", { class: r.check.startsWith("replaced") ? "warn" : "" }, check),
    r.mode === "offline" ? " · offline" : "",
    fell ? h("span", { class: "warn", title: fell.note }, fellText) : "");
}

function renderAnswer(r, question) {
  const o = OUTCOMES[r.outcome];
  const card = h("article", { class: "msg-bot", "aria-label": o.label },
    h("span", { class: `stamp ${r.outcome}`, title: o.label }, `${o.icon} ${o.stamp}`),
    h("p", { class: "answer" }, richText(r.answer)));
  if (r.steps.length) card.append(pathLine(r.steps));
  if (r.sources.length) {
    card.append(h("div", { class: "sources", "aria-label": "Sources" }, r.sources.map((s) =>
      h("button", { type: "button", class: "src-chip", title: `${s.id} · ${fmtDate(s.at)} · ${s.author || "unknown author"}`,
        onclick: () => focusNodes([s.id]) }, icon(s.kind), h("span", {}, s.title)))));
  }
  if (r.choices.length) {
    const q = (r.trace.find((t) => t.tool === "resolve_decision") || {}).args?.q || "";
    card.append(h("div", { class: "choices" }, "Did you mean:", r.choices.map((c) =>
      h("button", { type: "button", class: `chip k-Decision${c.status === "superseded" ? " superseded" : ""}`,
        onclick: () => ask(q ? question.replace(new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"), c.id)
                            : `What breaks if we reverse ${c.id}?`) }, c.label))));
  }
  card.append(footer(r));
  return card;
}

function pendingCard() {
  return h("article", { class: "msg-bot pending", "aria-busy": "true" },
    h("div", { class: "skeleton short" }), h("div", { class: "skeleton" }), h("p", {}, "Walking the graph…"));
}

function setComposerBusy(busy) {
  state.pending = busy;
  $("#composer-input").disabled = busy;
  $("#ask-btn").disabled = busy;
}

async function ask(question) {
  question = question.trim();
  if (!question || state.pending) return;
  if (!isDesktop() && $("#layout").dataset.view !== "chat") setView("chat");
  addMessage(h("div", { class: "msg-user" }, question));
  const pending = addMessage(pendingCard());
  setComposerBusy(true);
  try {
    const r = await api.chat(question);
    state.last = r;
    pending.replaceWith(renderAnswer(r, question));
    renderPaths(r.steps);
    renderTrace(r);
    $("#drawer").hidden = true;
    if (r.trace.some((t) => t.tool === "llm")) loadHealth();
    if (r.highlight.length) await showSubgraph(r.highlight);
  } catch (err) {
    const card = h("article", { class: "msg-bot error", role: "alert" },
      h("span", { class: "stamp error" }, "✕ Error"),
      h("p", { class: "answer" }, err.status === 503 ? err.message : "Something went wrong talking to the graph. Try again."),
      h("div", { class: "row-end" }, h("button", { type: "button", class: "btn btn-small",
        onclick: () => { card.remove(); $$(".msg-user").at(-1)?.remove(); ask(question); } }, "Retry")));
    pending.replaceWith(card);
  } finally {
    setComposerBusy(false);
    $("#messages").lastElementChild?.scrollIntoView({ block: "end" });
    if (isDesktop()) $("#composer-input").focus();
  }
}

function autoGrow(ta) {
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight + 2, 5 * 22 + 20) + "px";
}

// ---------------------------------------------------------------- autocomplete

const ac = { items: [], index: 0, token: null };

function allNames() {
  const e = state.entities;
  return [...e.systems.map((s) => [s.name, "System"]), ...e.people.map((p) => [p.name, "Person"]),
    ...e.projects.map((p) => [p.name, "Project"]), ...e.decisions.map((d) => [d.id, "Decision"])];
}

function updateAutocomplete() {
  const ta = $("#composer-input");
  const before = ta.value.slice(0, ta.selectionStart);
  const m = before.match(/([\w-]{2,})$/);
  const box = $("#autocomplete");
  if (!m) { box.hidden = true; ac.items = []; return; }
  const tok = m[1].toLowerCase();
  ac.token = m[1];
  ac.items = allNames().filter(([n]) => {
    const low = n.toLowerCase();
    return low !== tok && (low.startsWith(tok) || (tok.length >= 3 && low.includes(tok)));
  }).slice(0, 6);
  ac.index = 0;
  if (!ac.items.length) { box.hidden = true; return; }
  box.replaceChildren(...ac.items.map(([n, kind], i) => h("div", {
    class: "ac-item", role: "option", "aria-selected": String(i === 0), id: `ac-${i}`,
    onmousedown: (e) => { e.preventDefault(); ac.index = i; acceptAutocomplete(); },
  }, chip(n, kind, null, { asButton: false }), i === 0 ? h("kbd", {}, "Tab") : null)));
  box.hidden = false;
}

function acceptAutocomplete() {
  const ta = $("#composer-input");
  const [name] = ac.items[ac.index];
  const pos = ta.selectionStart;
  const start = pos - ac.token.length;
  ta.value = ta.value.slice(0, start) + name + ta.value.slice(pos);
  ta.selectionStart = ta.selectionEnd = start + name.length;
  $("#autocomplete").hidden = true;
  ac.items = [];
  autoGrow(ta);
}

function moveAutocomplete(delta) {
  ac.index = (ac.index + delta + ac.items.length) % ac.items.length;
  $$("#autocomplete .ac-item").forEach((el, i) => el.setAttribute("aria-selected", String(i === ac.index)));
}

function wireComposer() {
  const ta = $("#composer-input");
  $("#suggestions").replaceChildren(...SUGGESTIONS.map((q) =>
    h("button", { type: "button", class: "suggestion", onclick: () => ask(q) }, q)));
  $("#composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = ta.value;
    ta.value = "";
    autoGrow(ta);
    $("#autocomplete").hidden = true;
    ask(q);
  });
  ta.addEventListener("input", () => { autoGrow(ta); updateAutocomplete(); });
  ta.addEventListener("blur", () => setTimeout(() => { $("#autocomplete").hidden = true; }, 100));
  ta.addEventListener("keydown", (e) => {
    const open = !$("#autocomplete").hidden && ac.items.length;
    if (open && e.key === "Tab") { e.preventDefault(); acceptAutocomplete(); return; }
    if (open && (e.key === "ArrowDown" || e.key === "ArrowUp")) { e.preventDefault(); moveAutocomplete(e.key === "ArrowDown" ? 1 : -1); return; }
    if (e.key === "Escape") { ta.value = ""; autoGrow(ta); $("#autocomplete").hidden = true; return; }
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#composer").requestSubmit(); }
  });
  document.addEventListener("keydown", (e) => {
    const typing = e.target.closest("input, textarea, select, [contenteditable]");
    if (e.key === "/" && !typing) {
      e.preventDefault();
      if (!isDesktop()) setView("chat");
      ta.focus();
    }
  });
}

// ---------------------------------------------------------------- examples

async function wireExamples() {
  let ex;
  try { ex = await api.examples(); } catch { return; }
  const panel = $("#examples-panel"), btn = $("#examples-btn");
  const groups = [...new Set(ex.questions.map((q) => q.group))];
  $("#examples-body").replaceChildren(...groups.map((g) => h("section", { class: "ex-group" },
    h("h3", {}, g),
    ex.questions.filter((q) => q.group === g).map((q) => {
      const o = OUTCOMES[q.expect.outcome];
      return h("button", { type: "button", class: "ex-item", onclick: () => { toggle(false); ask(q.q); } },
        h("span", { class: "q" }, q.q), h("span", { class: "why" }, q.shows),
        h("span", { class: `stamp ${q.expect.outcome}`, title: `Expected on a fresh graph: ${o.label}` }, `${o.icon} ${o.stamp}`));
    }))));
  const toggle = (open = panel.hidden) => {
    panel.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
    if (open) panel.querySelector(".ex-item")?.focus();
  };
  btn.addEventListener("click", () => toggle());
  $("#examples-close").addEventListener("click", () => { toggle(false); btn.focus(); });
  panel.addEventListener("keydown", (e) => { if (e.key === "Escape") { toggle(false); btn.focus(); } });
  document.addEventListener("click", (e) => { if (!panel.hidden && !e.target.closest("#examples-panel, #examples-btn, #see-all")) toggle(false); });
  const seeAll = $("#see-all");
  if (seeAll) { seeAll.hidden = false; seeAll.textContent = `See all ${ex.questions.length} example questions`; seeAll.addEventListener("click", () => toggle(true)); }

  const pick = $("#ingest-example");
  pick.append(...ex.changes.map((c, i) => h("option", { value: String(i) }, c.label)));
  pick.addEventListener("change", () => {
    const c = ex.changes[Number(pick.value)];
    if (!c) return;
    $("#ingest-text").value = c.text;
    $("#ingest-btn").disabled = false;
    $("#proposal").replaceChildren();
    pick.value = "";
    $("#ingest-text").focus();
  });
}

// ---------------------------------------------------------------- desk: stale docs

function animateCount(el, from, to) {
  if (from == null || from === to || reducedMotion()) { el.textContent = to; return; }
  el.classList.remove("bump");
  void el.offsetWidth;
  el.classList.add("bump");
  const stepMs = 500 / Math.max(1, Math.abs(to - from));
  let cur = from;
  const tick = () => {
    cur += Math.sign(to - from);
    el.textContent = cur;
    if (cur !== to) setTimeout(tick, stepMs);
  };
  tick();
}

function setStaleCount(n) {
  animateCount($("#stale-count"), state.staleCount, n);
  state.staleCount = n;
}

function staleSteps(r) {
  return [[{ id: r.source_id, kind: "Source" },
    { id: r.old_id, kind: "Decision", rel: "ASSUMES", dir: "→", status: "superseded" },
    { id: r.now_id, kind: "Decision", rel: "SUPERSEDES", dir: "←", status: "active", at: r.changed_at }]];
}

function staleRow(r, flash) {
  const show = () => focusNodes([r.source_id, r.old_id, r.now_id], { steps: staleSteps(r) });
  const li = h("li", {
    class: `list-row${flash ? " flash" : ""}`, tabindex: "0", role: "button",
    "aria-label": `${r.stale_doc}: assumes ${r.old_id}, now ${r.now_id}. Show in graph.`,
    onclick: show, onkeydown: (e) => { if (e.key === "Enter" && e.target === li) show(); },
  },
    h("div", { class: "title" }, icon(r.kind), h("span", {}, r.stale_doc)),
    h("div", { class: "line" }, "assumes ", h("span", { class: "old" }, `${r.old_id} ${keyword(r.assumes)}`),
      " → now ", h("span", { class: "now" }, `${r.now_id} ${keyword(r.now_true)}`)),
    h("div", { class: "line" },
      r.author_status === "left" ? [`By ${r.author}`, leftStamp(), " · "] : null,
      "Fix by: ", r.fix_by.length ? r.fix_by.join(", ") : "nobody active"),
  );
  const actions = h("div", { class: "actions" });
  const btn = h("button", { type: "button", class: "btn btn-small", onclick: (e) => { e.stopPropagation(); openReview(li, r); } }, "Mark reviewed");
  actions.append(btn);
  li.append(actions);
  return li;
}

function openReview(li, r) {
  li.querySelector(".review-pop")?.remove();
  const people = activePeople();
  const select = h("select", { "aria-label": "Reviewed by" }, people.map((p) => h("option", { value: p }, p)));
  select.value = r.fix_by[0] || people[0];
  const pop = h("div", { class: "popover review-pop", role: "dialog", "aria-label": "Mark reviewed",
    onclick: (e) => e.stopPropagation(), onkeydown: (e) => { if (e.key === "Escape") pop.remove(); } },
    h("label", {}, "Reviewed by", select),
    h("div", { class: "row-end" },
      h("button", { type: "button", class: "btn-text", onclick: () => pop.remove() }, "Cancel"),
      h("button", { type: "button", class: "btn btn-small btn-green", onclick: async () => {
        try {
          const res = await api.review(r.source_id, r.old_id, select.value);
          pop.remove();
          li.classList.add("leaving");
          setStaleCount(Math.max(0, state.staleCount - 1));
          toast(`Re-pointed to ${res.now_assumes.join(", ")}.`);
          setTimeout(loadStale, 420);
        } catch (err) { toast(err.message); }
      } }, "Save")));
  li.append(pop);
  select.focus();
}

async function loadStale({ flash = [] } = {}) {
  const list = $("#stale-list");
  try {
    const rows = await api.stale();
    setStaleCount(rows.length);
    list.replaceChildren(...(rows.length ? rows.map((r) => staleRow(r, flash.includes(r.source_id)))
      : [h("li", { class: "list-empty" }, h("span", { class: "check", "aria-hidden": "true" }, "✓"), "Every doc matches current decisions.")]));
  } catch (err) { listError(list, "Couldn't load stale docs.", () => loadStale()); }
}

// ---------------------------------------------------------------- desk: risk

async function loadRisk() {
  const list = $("#risk-list");
  try {
    const rows = await api.risk();
    if (!rows.length) { list.replaceChildren(h("li", { class: "list-empty" }, "No system depends on a single person.")); return; }
    list.replaceChildren(...rows.map((r) => {
      const go = () => ask(`Who knows ${r.system}?`);
      return h("li", { class: "list-row", tabindex: "0", role: "button", "aria-label": `Ask who knows ${r.system}`,
        onclick: go, onkeydown: (e) => { if (e.key === "Enter") go(); } },
        h("div", { class: "title" }, chip(r.system, "System", null, { asButton: false })),
        h("div", { class: "line" }, r.active.length ? `1 person left who knows this: ${r.active.join(", ")}` : "Nobody active knows this."),
        r.gone.length ? h("div", { class: "line" }, "Gone: ", r.gone.flatMap((g, i) => [i ? ", " : "", g, leftStamp()])) : null);
    }));
  } catch { listError(list, "Couldn't load risk.", loadRisk); }
}

// ---------------------------------------------------------------- desk: time travel

function wireTimeTravel() {
  $("#tt-date").value = today();
  $("#tt-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const system = $("#tt-system").value, date = $("#tt-date").value;
    const out = $("#tt-result");
    if (!system || !date) { out.textContent = "Pick a system and a date."; return; }
    try {
      const res = await api.asOf(system, date);
      if (!res.rows.length) { out.replaceChildren(`No recorded decision for ${system} on that date.`); return; }
      out.replaceChildren(`On ${fmtDate(date)}, Kettle Labs believed: `, ...res.rows.flatMap((r, i) => [
        i ? "; " : "", h("strong", {}, r.believed),
        ` (since ${fmtDate(r.since)} · ${(r.source || "").split(":")[0]})`]), ".");
      focusNodes([system, ...res.rows.map((r) => r.id)], {
        steps: res.rows.map((r) => [{ id: system, kind: "System" },
          { id: r.id, kind: "Decision", rel: "ABOUT", dir: "←", status: r.status, at: r.since }]) });
    } catch (err) { out.textContent = err.message; }
  });
}

// ---------------------------------------------------------------- desk: load-bearing

let lbLoaded = false;
async function reloadLoadBearing() {
  if (!$("#lb-details").open) { lbLoaded = false; return; }
  const list = $("#lb-list");
  try {
    const rows = await api.loadBearing(5);
    const max = Math.max(...rows.map((r) => r.score), 0.0001);
    list.replaceChildren(...rows.map((r) => h("li", {}, h("button", {
      type: "button", title: `${r.id}: ${r.decision} (score ${r.score})`, onclick: () => ask(`What breaks if we reverse ${r.id}?`),
    }, chip(r.id, "Decision", r.status, { asButton: false }), h("span", { class: "lb-bar", style: `width:${Math.round((r.score / max) * 100)}%` }),
      h("span", { class: "lb-sum" }, r.decision)))));
    lbLoaded = true;
  } catch { listError(list, "Couldn't load rankings.", reloadLoadBearing); }
}

// ---------------------------------------------------------------- desk: ingest

function wireIngest() {
  const ta = $("#ingest-text"), btn = $("#ingest-btn");
  ta.addEventListener("input", () => { btn.disabled = !ta.value.trim(); });
  $("#ingest-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!ta.value.trim()) return;
    btn.disabled = true;
    btn.textContent = "Reading";
    btn.classList.add("reading");
    try {
      renderProposal(await api.propose(ta.value.trim(), $("#ingest-author").value));
    } catch (err) {
      $("#proposal").replaceChildren(h("p", { class: "prop-error" }, err.message));
    } finally {
      btn.textContent = "Read it";
      btn.classList.remove("reading");
      btn.disabled = !ta.value.trim();
    }
  });
}

function candidatesFor(system) {
  return state.entities.decisions.filter((d) => d.about === system && d.status === "active")
    .sort((a, b) => b.id.localeCompare(a.id));
}

function renderProposal(res) {
  const p = res.proposal;
  const summary = h("input", { type: "text", value: p.summary || "", maxlength: "120", "aria-label": "Decision summary" });
  const system = h("select", { class: "sel-system", "aria-label": "System" },
    h("option", { value: "" }, "Pick a system"), res.systems.map((s) => h("option", { value: s }, s)));
  system.value = p.system || "";
  const replaces = h("select", { class: "sel-decision", "aria-label": "Replaces" });
  const author = h("select", { class: "sel-person", "aria-label": "Decided by" },
    h("option", { value: "" }, "Pick a person"), res.people.map((n) => h("option", { value: n }, n)));
  author.value = p.author || "";
  const note = h("p", { class: "prop-note" }, "Nothing is written until you confirm.");
  const confirmBtn = h("button", { type: "button", class: "btn btn-green" }, "Confirm & record");

  const fillCandidates = (list, chosen) => {
    replaces.replaceChildren(...list.map((c) => h("option", { value: c.id }, `${c.id} · ${c.summary}`)),
      h("option", { value: "" }, "Doesn't replace anything"));
    replaces.value = chosen && list.some((c) => c.id === chosen) ? chosen : (list[0]?.id || "");
  };
  const validate = () => {
    const noReplace = !replaces.value;
    note.textContent = noReplace && system.value
      ? "WhyBase only records decisions that change an existing one in this version."
      : "Nothing is written until you confirm.";
    confirmBtn.disabled = noReplace || !system.value || !author.value || summary.value.trim().length < 3;
  };
  fillCandidates(res.candidates, p.old);
  system.addEventListener("change", () => { fillCandidates(candidatesFor(system.value)); validate(); });
  [replaces, author].forEach((el) => el.addEventListener("change", validate));
  summary.addEventListener("input", validate);
  validate();

  const err = (field) => res.problems[field] ? h("p", { class: "prop-error" }, res.problems[field]) : null;
  const card = h("div", { class: "proposal" },
    err("system"),
    h("div", { class: "prop-line" }, h("span", {}, "New decision"), summary),
    h("div", { class: "prop-line" }, h("span", {}, "About"), system),
    h("div", { class: "prop-line" }, h("span", {}, "Replaces"), replaces),
    err("author"),
    h("div", { class: "prop-line" }, h("span", {}, "Decided by"), author),
    h("div", { class: "row-end" },
      h("button", { type: "button", class: "btn-text", onclick: () => $("#proposal").replaceChildren() }, "Discard"),
      confirmBtn),
    note);
  confirmBtn.addEventListener("click", () => confirmProposal(card, {
    text: p.text, system: system.value, summary: summary.value.trim(), old: replaces.value, author: author.value }));
  $("#proposal").replaceChildren(card);
  if (res.problems.system) { system.focus(); system.showPicker?.(); }
}

async function confirmProposal(card, proposal) {
  card.querySelectorAll("button, select, input").forEach((el) => { el.disabled = true; });
  try {
    const res = await api.confirm(proposal);
    const n = res.stale.length;
    card.className = "proposal receipt";
    card.replaceChildren(h("p", {}, "Recorded ", h("strong", {}, res.decision.id), `. ${n} doc${n === 1 ? " is" : "s are"} now out of date.`),
      h("p", { class: "prop-note" }, `${res.decision.id} replaces ${res.decision.replaces} for ${res.decision.system}.`));
    $("#ingest-text").value = "";
    $("#ingest-btn").disabled = true;
    await Promise.all([loadEntities(), loadStats(), loadRisk()]);
    await loadStale({ flash: res.stale.map((r) => r.source_id) });
    reloadLoadBearing();
    const staleIds = res.stale.map((r) => r.source_id);
    focusNodes(res.highlight, { pulse: staleIds, steps: res.stale.map((r) => staleSteps({ ...r, now_id: res.decision.id })[0]) });
    toast(`Recorded ${res.decision.id}. ${n} doc${n === 1 ? "" : "s"} flagged out of date.`);
  } catch (err) {
    card.querySelectorAll("button, select, input").forEach((el) => { el.disabled = false; });
    card.prepend(h("p", { class: "prop-error" }, err.message));
  }
}

// ---------------------------------------------------------------- boot

async function boot() {
  setGraphDownHandler(() => setGraphStatus(false));
  wireTabs();
  wireReset();
  wireComposer();
  wireIngest();
  wireTimeTravel();
  wireGraph();
  wireExamples();
  $("#lb-details").addEventListener("toggle", () => { if ($("#lb-details").open && !lbLoaded) reloadLoadBearing(); });
  $("#banner-retry").addEventListener("click", async () => { if (await loadHealth()) loadAll(); });
  setView("chat");
  if (await loadHealth()) loadAll();
}

function loadAll() {
  return Promise.all([loadStats(), loadEntities(), loadStale(), loadRisk()]);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
