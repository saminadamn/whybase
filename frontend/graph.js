// Cytoscape graph view: colour key, shapes, highlighting, pulses and controls.

const C = {
  paper: "#FBF7EE", paper2: "#F4EEDF", card: "#FFFDF8", ink: "#2A2420", inkSoft: "#6B6158",
  yellow: "#FFE066", green: "#7BC47F", orange: "#FF9F43", red: "#E5484D", pink: "#F48FB1", purple: "#B39DDB", lime: "#C5E063",
};
const HATCH = "data:image/svg+xml;utf8," + encodeURIComponent(
  `<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><path d="M-2 2l4-4M0 8l8-8M6 10l4-4" stroke="${C.inkSoft}" stroke-width="1.3"/></svg>`);
const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const strike = (s) => [...s].map((ch) => ch + "̶").join("");

let cy = null;
let onSelect = () => {};

function label(n) {
  const text = n.label.length > 22 ? n.label.slice(0, 21) + "…" : n.label;
  return n.kind === "Decision" && n.status === "superseded" ? strike(text) : text;
}

const STYLE = [
  { selector: "node", style: {
    "background-color": C.card, "border-width": 1.5, "border-color": C.ink, width: 28, height: 28,
    label: "data(display)", "font-family": "Figtree, system-ui, sans-serif", "font-size": 11, color: C.ink,
    "text-valign": "bottom", "text-margin-y": 4, "text-wrap": "none", "min-zoomed-font-size": 6,
    "transition-property": "opacity, border-width", "transition-duration": "0.2s",
  } },
  { selector: 'node[kind="Person"]', style: { shape: "ellipse", "background-color": C.pink } },
  { selector: 'node[kind="Person"][status="left"]', style: { "border-style": "dashed", "border-color": C.red, "border-width": 2 } },
  { selector: 'node[kind="Team"]', style: { shape: "round-rectangle", "background-color": C.purple, width: 36, height: 24 } },
  { selector: 'node[kind="System"]', style: { shape: "hexagon", "background-color": C.green, width: 34, height: 30 } },
  { selector: 'node[kind="Project"]', style: { shape: "tag", "background-color": C.lime, width: 34, height: 24 } },
  { selector: 'node[kind="Source"]', style: { shape: "cut-rectangle", "background-color": C.orange, width: 24, height: 30 } },
  { selector: 'node[kind="Decision"]', style: { shape: "diamond", "background-color": C.yellow, width: 34, height: 34, "font-family": "JetBrains Mono, monospace", "font-size": 10 } },
  { selector: 'node[kind="Decision"][status="superseded"]', style: {
    "background-color": C.paper2, "background-image": HATCH, "background-repeat": "repeat", "background-fit": "none",
    "border-style": "dashed", color: C.inkSoft } },
  { selector: "edge", style: {
    width: 1.2, "line-color": C.inkSoft, "target-arrow-shape": "triangle", "target-arrow-color": C.inkSoft, "arrow-scale": 0.7,
    "curve-style": "bezier", label: "data(type)", "font-family": "JetBrains Mono, monospace", "font-size": 7,
    "text-transform": "uppercase", "text-opacity": 0, "text-rotation": "autorotate", color: C.ink,
    "text-background-color": C.paper, "text-background-opacity": 0.9, "text-background-padding": 1,
  } },
  { selector: "edge.hover", style: { "text-opacity": 1, "z-index": 10 } },
  { selector: ".dim", style: { opacity: 0.25 } },
  { selector: "node.hl", style: { "border-width": 3, opacity: 1 } },
  { selector: "edge.hl", style: { width: 2.5, "line-color": C.ink, "target-arrow-color": C.ink, opacity: 1 } },
  { selector: "node:selected", style: { "overlay-color": C.yellow, "overlay-opacity": 0.45, "overlay-padding": 6 } },
];

export function initGraph(container, handlers = {}) {
  if (!window.cytoscape) return false;
  onSelect = handlers.onSelect || onSelect;
  window.cytoscape.warnings(false);  // layout animation briefly overlaps nodes; the warnings are noise
  cy = window.cytoscape({ container, style: STYLE, minZoom: 0.2, maxZoom: 3, boxSelectionEnabled: false });
  cy.on("tap", "node", (e) => onSelect(e.target.data()));
  cy.on("tap", (e) => { if (e.target === cy) onSelect(null); });
  cy.on("mouseover", "edge", (e) => e.target.addClass("hover"));
  cy.on("mouseout", "edge", (e) => e.target.removeClass("hover"));
  return true;
}

/** Replace the canvas with {nodes, edges}; highlight the given ids and dim the rest. */
export function showGraph(data, highlight = [], { pulse = [], fitAll = false } = {}) {
  if (!cy) return;
  cy.elements().remove();
  cy.add([
    ...data.nodes.map((n) => ({ group: "nodes", data: { ...n, display: label(n) } })),
    ...data.edges.map((e) => ({ group: "edges", data: { id: `${e.source}|${e.type}|${e.target}`, ...e } })),
  ]);
  applyHighlight(highlight);
  const layout = cy.layout({
    name: "cose", animate: !reducedMotion(), animationDuration: 300, padding: 24,
    nodeRepulsion: () => 9000, idealEdgeLength: () => 70, nodeOverlap: 12, randomize: true, fit: true,
  });
  layout.one("layoutstop", () => { if (fitAll) cy.fit(undefined, 24); else fitFocus(); pulseNodes(pulse); });
  layout.run();
}

export function applyHighlight(ids) {
  if (!cy) return;
  const set = new Set(ids);
  cy.elements().removeClass("hl dim");
  if (!set.size) return;
  const nodes = cy.nodes().filter((n) => set.has(n.id()));
  nodes.addClass("hl");
  nodes.edgesWith(nodes).addClass("hl");
  cy.elements().not(nodes).not(nodes.edgesWith(nodes)).addClass("dim");
}

/** Highlight ids that are already on the canvas. Returns false if any are missing. */
export function focusIfPresent(ids) {
  if (!cy || !ids.every((id) => cy.getElementById(id).nonempty())) return false;
  applyHighlight(ids);
  return true;
}

export function pulseNodes(ids) {
  if (!cy || reducedMotion()) return;
  ids.forEach((id) => {
    const n = cy.getElementById(id);
    if (n.empty()) return;
    const big = { style: { "border-color": C.orange, "border-width": 7 } };
    const back = { style: { "border-color": C.ink, "border-width": 3 } };
    n.animate(big, { duration: 280 }).animate(back, { duration: 280 })
      .animate(big, { duration: 280 }).animate(back, { duration: 280, complete: () => n.removeStyle("border-color border-width") });
  });
}

/** Fit to the highlighted nodes (with a little context) or to everything. */
function fitFocus() {
  const hl = cy.nodes(".hl");
  cy.fit(hl.nonempty() ? hl.union(hl.neighborhood()) : undefined, 28);
}

export const fit = () => cy && cy.animate({ fit: { padding: 24 } }, { duration: reducedMotion() ? 0 : 200 });
export const zoom = (f) => cy && cy.zoom({ level: cy.zoom() * f, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
export const resize = () => cy && (cy.resize(), cy.fit(undefined, 24));
export const isEmpty = () => !cy || cy.elements().empty();
export const nodeData = (id) => (cy && cy.getElementById(id).nonempty() ? cy.getElementById(id).data() : null);
