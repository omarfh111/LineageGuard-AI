/* LineageField — WebGL lineage constellation for LineageGuard.
 *
 * Renders a live DataHub catalog (or a synthetic demo constellation) as an
 * additive-blended 3D point/line field with lineage packets flowing along edges.
 *
 * Usage:
 *   import { mountLineageField } from "./lineage-field";
 *   const handle = mountLineageField(el, { mode: "interactive", data, onSelect });
 *   handle.setData(nextData);   // atomic swap, keeps camera
 *   handle.setQuery("orders");  // dims non-matching nodes
 *   handle.dispose();
 *
 * No post-processing passes and no OrbitControls dependency: the orbit camera,
 * halo shader, and hover picking are self-contained so the module stays a single
 * code-split chunk on top of `three`.
 */
import * as THREE from "three";

export type FieldNodeInput = {
  urn: string;
  label: string;
  platform?: string | null;
  entityType?: string | null;
  owners?: number;
  fields?: number;
};

export type FieldEdgeInput = { source: string; target: string };

export type FieldData = { nodes: FieldNodeInput[]; edges: FieldEdgeInput[] };

export type FieldNode = FieldNodeInput & {
  index: number;
  platformKey: string;
  layer: number;
  degree: number;
  x: number;
  y: number;
  z: number;
};

export type LineageFieldOptions = {
  mode?: "ambient" | "interactive";
  data?: FieldData | null;
  motion?: "Flowing" | "Calm" | "Still";
  onSelect?: (node: FieldNode | null) => void;
  onHover?: (node: FieldNode | null) => void;
  onCount?: (visible: number) => void;
};

export type LineageFieldHandle = {
  dispose: () => void;
  setData: (data: FieldData) => void;
  setQuery: (term: string) => void;
  select: (urn: string | null) => void;
  resize: () => void;
};

/* ---------------------------------------------------------------- palette */

// Shared with the Cartography legend, which must not import Three.js.
import { colorForPlatform, platformKey } from "./platformPalette";

export { PLATFORM_COLORS, platformKey } from "./platformPalette";

/* ------------------------------------------------------------ demo graph */

function mulberry32(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Deterministic showcase catalog used by the marketing hero when no live cache is loaded. */
export function demoData(): FieldData {
  const rnd = mulberry32(20260806);
  const nodes: FieldNodeInput[] = [];
  const edges: FieldEdgeInput[] = [];
  const layers: string[][] = [[], [], [], [], []];

  const urnFor = (label: string, platform: string, dashboard: boolean) =>
    `urn:li:dataset:(urn:li:dataPlatform:${platform},b2fd91.${dashboard ? "analytics" : "order_entry_db.order_entry"}.` +
    `${label.toLowerCase().replace(/[^a-z0-9_]+/g, "_")},PROD)`;

  const add = (label: string, platform: string, layer: number, dashboard = false) => {
    const urn = urnFor(label, platform, dashboard);
    nodes.push({
      urn,
      label,
      platform,
      entityType: dashboard ? "dashboard" : "dataset",
      owners: 1 + Math.floor(rnd() * 3),
      fields: 6 + Math.floor(rnd() * 28)
    });
    layers[layer].push(urn);
    return urn;
  };

  const core: Array<[string, string, number, boolean]> = [
    ["orders_raw", "kafka", 0, false], ["order_items_raw", "kafka", 0, false],
    ["customers_raw", "postgres", 0, false], ["payments_raw", "postgres", 0, false],
    ["sessions_raw", "s3", 0, false], ["catalog_raw", "s3", 0, false],
    ["stg_orders", "dbt", 1, false], ["stg_order_items", "dbt", 1, false],
    ["stg_customers", "dbt", 1, false], ["stg_payments", "dbt", 1, false],
    ["orders", "dbt", 2, false], ["order_items", "dbt", 2, false],
    ["customers", "dbt", 2, false], ["payments", "dbt", 2, false], ["order_facts", "dbt", 2, false],
    ["fct_orders", "snowflake", 3, false], ["dim_customers", "snowflake", 3, false],
    ["agg_daily_revenue", "snowflake", 3, false], ["customer_360", "snowflake", 3, false],
    ["Revenue Overview", "looker", 4, true], ["Customer Health", "looker", 4, true],
    ["Finance Close", "looker", 4, true], ["Ops Daily", "looker", 4, true],
    ["Marketing Attribution", "looker", 4, true]
  ];
  const byLabel = new Map<string, string>();
  core.forEach(([label, platform, layer, dash]) => byLabel.set(label, add(label, platform, layer, dash)));

  const words = ["events", "clicks", "returns", "refunds", "shipments", "carriers", "inventory",
    "promotions", "invoices", "subscriptions", "tickets", "reviews", "warehouse", "regions", "suppliers", "carts"];
  const quals = ["daily", "weekly", "hourly", "enriched", "clean", "curated", "audit", "history"];
  const sourcePlatforms = ["kafka", "postgres", "s3"];
  for (let i = 0; i < 118; i += 1) {
    const layer = i % 5;
    const base = words[Math.floor(rnd() * words.length)];
    const qual = quals[Math.floor(rnd() * quals.length)];
    if (layer === 0) add(`${base}_raw_${10 + Math.floor(rnd() * 89)}`, sourcePlatforms[Math.floor(rnd() * 3)], 0);
    else if (layer === 1) add(`stg_${base}_${qual}`, "dbt", 1);
    else if (layer === 2) add(`${base}_${qual}`, "dbt", 2);
    else if (layer === 3) add(`${rnd() > 0.5 ? "fct_" : "dim_"}${base}`, "snowflake", 3);
    else add(`${base.charAt(0).toUpperCase()}${base.slice(1)} ${rnd() > 0.5 ? "Report" : "Monitor"}`, "looker", 4, true);
  }

  const link = (a?: string, b?: string) => { if (a && b && a !== b) edges.push({ source: a, target: b }); };
  ([["orders_raw", "stg_orders"], ["order_items_raw", "stg_order_items"], ["customers_raw", "stg_customers"],
    ["payments_raw", "stg_payments"], ["stg_orders", "orders"], ["stg_order_items", "order_items"],
    ["stg_customers", "customers"], ["stg_payments", "payments"], ["orders", "order_facts"],
    ["order_items", "order_facts"], ["orders", "fct_orders"], ["order_facts", "fct_orders"],
    ["customers", "dim_customers"], ["payments", "agg_daily_revenue"], ["fct_orders", "agg_daily_revenue"],
    ["dim_customers", "customer_360"], ["fct_orders", "customer_360"], ["agg_daily_revenue", "Revenue Overview"],
    ["agg_daily_revenue", "Finance Close"], ["customer_360", "Customer Health"], ["fct_orders", "Ops Daily"],
    ["customer_360", "Marketing Attribution"], ["fct_orders", "Revenue Overview"]] as Array<[string, string]>)
    .forEach(([a, b]) => link(byLabel.get(a), byLabel.get(b)));

  const linked = new Set<string>();
  edges.forEach((e) => { linked.add(e.source); linked.add(e.target); });
  for (let layer = 1; layer < 5; layer += 1) {
    layers[layer].forEach((urn) => {
      if (linked.has(urn)) return;
      const parents = layers[layer - 1];
      const count = 1 + Math.floor(rnd() * 2);
      for (let k = 0; k < count; k += 1) link(parents[Math.floor(rnd() * parents.length)], urn);
    });
  }
  for (let s = 0; s < 26; s += 1) {
    const l = 1 + Math.floor(rnd() * 3);
    link(layers[l][Math.floor(rnd() * layers[l].length)], layers[l + 1][Math.floor(rnd() * layers[l + 1].length)]);
  }
  return { nodes, edges };
}

/* ---------------------------------------------------------------- layout */

type Edge = { s: number; t: number };

/** Layers nodes by longest upstream path, then relaxes them into a lineage-flow constellation. */
function layout(data: FieldData): { nodes: FieldNode[]; edges: Edge[]; adjacency: number[][] } {
  const rnd = mulberry32(7919);
  const index = new Map<string, number>();
  data.nodes.forEach((n, i) => index.set(n.urn, i));

  const edges: Edge[] = [];
  data.edges.forEach((e) => {
    const s = index.get(e.source);
    const t = index.get(e.target);
    if (s === undefined || t === undefined || s === t) return;
    edges.push({ s, t });
  });

  const degree = new Array<number>(data.nodes.length).fill(0);
  const outgoing: number[][] = data.nodes.map(() => []);
  const incoming = new Array<number>(data.nodes.length).fill(0);
  edges.forEach((e) => {
    degree[e.s] += 1; degree[e.t] += 1;
    outgoing[e.s].push(e.t); incoming[e.t] += 1;
  });

  // longest-path layering with a cycle-safe visit budget
  const layer = new Array<number>(data.nodes.length).fill(0);
  const queue: number[] = [];
  const remaining = incoming.slice();
  remaining.forEach((v, i) => { if (v === 0) queue.push(i); });
  let guard = data.nodes.length * 8;
  while (queue.length && guard-- > 0) {
    const i = queue.shift() as number;
    outgoing[i].forEach((j) => {
      layer[j] = Math.max(layer[j], Math.min(layer[i] + 1, 6));
      remaining[j] -= 1;
      if (remaining[j] <= 0) queue.push(j);
    });
  }
  const maxLayer = Math.max(1, ...layer);

  const nodes: FieldNode[] = data.nodes.map((n, i) => {
    const angle = rnd() * Math.PI * 2;
    const radius = 11 + Math.sqrt(rnd()) * 42;
    const centered = layer[i] - maxLayer / 2;
    return {
      ...n,
      index: i,
      platformKey: platformKey(n.platform || n.entityType || "unknown"),
      layer: layer[i],
      degree: degree[i],
      x: centered * (108 / Math.max(maxLayer, 1)) + (rnd() - 0.5) * 8,
      y: Math.sin(angle) * radius * 0.92,
      z: Math.cos(angle) * radius * 1.05
    };
  });

  for (let iteration = 0; iteration < 14; iteration += 1) {
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i];
        const b = nodes[j];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dz = b.z - a.z;
        const d2 = dx * dx + dy * dy + dz * dz;
        if (d2 < 90 && d2 > 0.0001) {
          const d = Math.sqrt(d2);
          const f = ((9.5 - d) / d) * 0.28;
          a.x -= dx * f * 0.35; a.y -= dy * f; a.z -= dz * f;
          b.x += dx * f * 0.35; b.y += dy * f; b.z += dz * f;
        }
      }
    }
    edges.forEach((e) => {
      const a = nodes[e.s];
      const b = nodes[e.t];
      const dy = b.y - a.y;
      const dz = b.z - a.z;
      a.y += dy * 0.02; a.z += dz * 0.02;
      b.y -= dy * 0.02; b.z -= dz * 0.02;
    });
    nodes.forEach((n) => {
      const home = (n.layer - maxLayer / 2) * (108 / Math.max(maxLayer, 1));
      n.x += (home - n.x) * 0.18;
    });
  }

  const adjacency: number[][] = nodes.map(() => []);
  edges.forEach((e, i) => { adjacency[e.s].push(i); adjacency[e.t].push(i); });
  return { nodes, edges, adjacency };
}

/* --------------------------------------------------------------- shaders */

const VERTEX_SHADER = `
attribute float size;
attribute float glow;
attribute float dim;
uniform float uPixelRatio;
varying vec3 vColor;
varying float vGlow;
varying float vDim;
void main() {
  vColor = color; vGlow = glow; vDim = dim;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_PointSize = size * uPixelRatio * (1.0 + glow * 0.8) * (300.0 / max(-mv.z, 1.0));
  gl_Position = projectionMatrix * mv;
}`;

const FRAGMENT_SHADER = `
varying vec3 vColor;
varying float vGlow;
varying float vDim;
void main() {
  float d = length(gl_PointCoord - vec2(0.5));
  if (d > 0.5) discard;
  float core = smoothstep(0.5, 0.04, d);
  float halo = pow(max(0.0, 1.0 - d * 2.0), 2.6);
  float a = (core * 0.52 + halo * 0.22) * (0.45 + vGlow) * vDim;
  gl_FragColor = vec4(vColor * (0.72 + vGlow * 0.55), a);
}`;

const NOOP_HANDLE: LineageFieldHandle = {
  dispose: () => undefined,
  setData: () => undefined,
  setQuery: () => undefined,
  select: () => undefined,
  resize: () => undefined
};

/* ----------------------------------------------------------------- mount */

export function mountLineageField(container: HTMLElement, options: LineageFieldOptions = {}): LineageFieldHandle {
  const ambient = options.mode !== "interactive";
  const motion = options.motion ?? "Flowing";
  const reduced = typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
  } catch {
    return NOOP_HANDLE;
  }
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
  renderer.setPixelRatio(pixelRatio);
  renderer.setClearColor(0x000000, 0);
  renderer.domElement.style.cssText = `display:block;width:100%;height:100%;${ambient ? "" : "cursor:grab;"}`;
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x05070f, ambient ? 0.0038 : 0.0062);
  const camera = new THREE.PerspectiveCamera(52, 1, 1, 800);
  const world = new THREE.Group();
  scene.add(world);

  const nodeMaterial = new THREE.ShaderMaterial({
    uniforms: { uPixelRatio: { value: pixelRatio } },
    vertexShader: VERTEX_SHADER,
    fragmentShader: FRAGMENT_SHADER,
    vertexColors: true,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending
  });
  const edgeMaterial = new THREE.LineBasicMaterial({
    vertexColors: true, transparent: true, opacity: ambient ? 0.62 : 0.78,
    depthWrite: false, blending: THREE.AdditiveBlending
  });
  const highlightMaterial = new THREE.LineBasicMaterial({
    color: 0xbcd6ff, transparent: true, opacity: 0.9, depthWrite: false, blending: THREE.AdditiveBlending
  });

  // A decorative home hero may use deterministic sample data. The live map
  // must never show sample assets while the server-owned catalog cache is
  // still empty or reconnecting.
  const initialData = options.data?.nodes.length
    ? options.data
    : ambient
      ? demoData()
      : { nodes: [], edges: [] };
  let graph = layout(initialData);
  let nodeGeometry = new THREE.BufferGeometry();
  let edgeGeometry = new THREE.BufferGeometry();
  const highlightGeometry = new THREE.BufferGeometry();
  highlightGeometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(160 * 6), 3));
  highlightGeometry.setDrawRange(0, 0);

  let points = new THREE.Points(nodeGeometry, nodeMaterial);
  let lines = new THREE.LineSegments(edgeGeometry, edgeMaterial);
  const highlight = new THREE.LineSegments(highlightGeometry, highlightMaterial);
  world.add(points, lines, highlight);

  let glowAttr = new Float32Array(0);
  let dimAttr = new Float32Array(0);
  let baseEdgeOpacity = ambient ? 0.62 : 0.78;
  let hovered = -1;
  let selected = -1;
  let query = "";

  const PACKETS = ambient ? 70 : 110;
  const packets = Array.from({ length: PACKETS }, () => ({ edge: 0, t: Math.random(), v: 0.06 + Math.random() * 0.16 }));
  const packetPos = new Float32Array(PACKETS * 3);
  const packetGlow = new Float32Array(PACKETS).fill(0.5);
  const packetDim = new Float32Array(PACKETS).fill(1);
  const packetGeometry = new THREE.BufferGeometry();
  packetGeometry.setAttribute("position", new THREE.BufferAttribute(packetPos, 3));
  packetGeometry.setAttribute("color", new THREE.BufferAttribute(
    Float32Array.from({ length: PACKETS * 3 }, (_, i) => (i % 3 === 0 ? 0.48 : i % 3 === 1 ? 0.74 : 1)), 3));
  packetGeometry.setAttribute("size", new THREE.BufferAttribute(new Float32Array(PACKETS).fill(1.9), 1));
  packetGeometry.setAttribute("glow", new THREE.BufferAttribute(packetGlow, 1));
  packetGeometry.setAttribute("dim", new THREE.BufferAttribute(packetDim, 1));
  world.add(new THREE.Points(packetGeometry, nodeMaterial));

  const DUST = 420;
  const dustGeometry = new THREE.BufferGeometry();
  dustGeometry.setAttribute("position", new THREE.BufferAttribute(
    Float32Array.from({ length: DUST * 3 }, (_, i) => (Math.random() - 0.5) * (i % 3 === 1 ? 170 : i % 3 === 2 ? 260 : 300)), 3));
  dustGeometry.setAttribute("color", new THREE.BufferAttribute(
    Float32Array.from({ length: DUST * 3 }, (_, i) => (i % 3 === 0 ? 0.45 : i % 3 === 1 ? 0.56 : 0.85)), 3));
  dustGeometry.setAttribute("size", new THREE.BufferAttribute(
    Float32Array.from({ length: DUST }, () => 0.8 + Math.random()), 1));
  dustGeometry.setAttribute("glow", new THREE.BufferAttribute(new Float32Array(DUST).fill(0.02), 1));
  dustGeometry.setAttribute("dim", new THREE.BufferAttribute(new Float32Array(DUST).fill(0.5), 1));
  scene.add(new THREE.Points(dustGeometry, nodeMaterial));

  function buildBuffers() {
    const nodeCount = graph.nodes.length;
    const position = new Float32Array(nodeCount * 3);
    const color = new Float32Array(nodeCount * 3);
    const size = new Float32Array(nodeCount);
    glowAttr = new Float32Array(nodeCount).fill(0.12);
    dimAttr = new Float32Array(nodeCount).fill(1);
    const scratch = new THREE.Color();

    graph.nodes.forEach((node, i) => {
      position[i * 3] = node.x; position[i * 3 + 1] = node.y; position[i * 3 + 2] = node.z;
      scratch.setHex(colorForPlatform(node.platformKey));
      color[i * 3] = scratch.r; color[i * 3 + 1] = scratch.g; color[i * 3 + 2] = scratch.b;
      const dashboard = (node.entityType || "").toLowerCase().includes("dashboard");
      size[i] = (dashboard ? 5.4 : 3.9) + Math.min(node.degree, 8) * 0.34;
    });

    const next = new THREE.BufferGeometry();
    next.setAttribute("position", new THREE.BufferAttribute(position, 3));
    next.setAttribute("color", new THREE.BufferAttribute(color, 3));
    next.setAttribute("size", new THREE.BufferAttribute(size, 1));
    next.setAttribute("glow", new THREE.BufferAttribute(glowAttr, 1));
    next.setAttribute("dim", new THREE.BufferAttribute(dimAttr, 1));
    nodeGeometry.dispose();
    nodeGeometry = next;
    points.geometry = next;

    const edgeCount = graph.edges.length;
    const edgePosition = new Float32Array(edgeCount * 6);
    const edgeColor = new Float32Array(edgeCount * 6);
    graph.edges.forEach((edge, i) => {
      const a = graph.nodes[edge.s];
      const b = graph.nodes[edge.t];
      edgePosition[i * 6] = a.x; edgePosition[i * 6 + 1] = a.y; edgePosition[i * 6 + 2] = a.z;
      edgePosition[i * 6 + 3] = b.x; edgePosition[i * 6 + 4] = b.y; edgePosition[i * 6 + 5] = b.z;
      scratch.setHex(colorForPlatform(a.platformKey)).multiplyScalar(0.3);
      edgeColor[i * 6] = scratch.r; edgeColor[i * 6 + 1] = scratch.g; edgeColor[i * 6 + 2] = scratch.b;
      scratch.setHex(colorForPlatform(b.platformKey)).multiplyScalar(0.3);
      edgeColor[i * 6 + 3] = scratch.r; edgeColor[i * 6 + 4] = scratch.g; edgeColor[i * 6 + 5] = scratch.b;
    });
    const nextEdges = new THREE.BufferGeometry();
    nextEdges.setAttribute("position", new THREE.BufferAttribute(edgePosition, 3));
    nextEdges.setAttribute("color", new THREE.BufferAttribute(edgeColor, 3));
    edgeGeometry.dispose();
    edgeGeometry = nextEdges;
    lines.geometry = nextEdges;

    packets.forEach((packet) => { packet.edge = Math.floor(Math.random() * Math.max(edgeCount, 1)); });
    if (query) setQuery(query);
  }
  buildBuffers();

  /* camera + interaction */
  const target = new THREE.Vector3(ambient ? -24 : 0, ambient ? 2 : 0, 0);
  let yaw = ambient ? -0.55 : -0.62;
  let pitch = ambient ? 0.16 : 0.22;
  let distance = ambient ? 126 : 108;
  let distanceTarget = distance;
  let yawVelocity = 0;
  let pitchVelocity = 0;
  let dragging = false;
  let lastX = 0;
  let lastY = 0;
  let travel = 0;
  let pointerX = 0;
  let pointerY = 0;
  let smoothX = 0;
  let smoothY = 0;
  let reveal = 0;

  const raycaster = new THREE.Raycaster();
  raycaster.params.Points = { threshold: 2.6 };
  const ndc = new THREE.Vector2(2, 2);

  const setGlow = (i: number, value: number) => {
    if (i < 0 || i >= glowAttr.length) return;
    glowAttr[i] = value;
    nodeGeometry.attributes.glow.needsUpdate = true;
  };

  function applyHighlight(index: number) {
    const array = highlightGeometry.attributes.position.array as Float32Array;
    let count = 0;
    if (index >= 0) {
      const list = graph.adjacency[index] ?? [];
      for (let i = 0; i < list.length && count < 160; i += 1) {
        const edge = graph.edges[list[i]];
        const a = graph.nodes[edge.s];
        const b = graph.nodes[edge.t];
        array[count * 6] = a.x; array[count * 6 + 1] = a.y; array[count * 6 + 2] = a.z;
        array[count * 6 + 3] = b.x; array[count * 6 + 4] = b.y; array[count * 6 + 5] = b.z;
        count += 1;
      }
    }
    highlightGeometry.attributes.position.needsUpdate = true;
    highlightGeometry.setDrawRange(0, count * 2);
  }

  function selectIndex(index: number) {
    if (selected === index) return;
    if (selected >= 0) setGlow(selected, 0.12);
    selected = index;
    if (index >= 0) setGlow(index, 1.5);
    applyHighlight(index);
    options.onSelect?.(index >= 0 ? graph.nodes[index] : null);
  }

  function setQuery(term: string) {
    query = (term || "").trim().toLowerCase();
    let visible = 0;
    graph.nodes.forEach((node, i) => {
      const haystack = `${node.label} ${node.platformKey} ${node.entityType ?? ""}`.toLowerCase();
      const hit = !query || haystack.includes(query);
      dimAttr[i] = hit ? 1 : 0.1;
      if (hit) visible += 1;
    });
    nodeGeometry.attributes.dim.needsUpdate = true;
    baseEdgeOpacity = query ? 0.14 : (ambient ? 0.62 : 0.78);
    options.onCount?.(visible);
  }

  function onPointerDown(event: PointerEvent) {
    if (ambient) return;
    dragging = true; travel = 0; lastX = event.clientX; lastY = event.clientY;
    renderer.domElement.style.cursor = "grabbing";
    renderer.domElement.setPointerCapture?.(event.pointerId);
  }
  function onPointerUp() {
    if (!dragging) return;
    dragging = false;
    renderer.domElement.style.cursor = "grab";
    if (travel < 5) selectIndex(hovered);
  }
  function onPointerMove(event: PointerEvent) {
    const rect = container.getBoundingClientRect();
    pointerX = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointerY = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    ndc.set(pointerX, pointerY);
    if (!dragging) return;
    const dx = event.clientX - lastX;
    const dy = event.clientY - lastY;
    travel += Math.abs(dx) + Math.abs(dy);
    yawVelocity -= dx * 0.0042;
    pitchVelocity -= dy * 0.0032;
    lastX = event.clientX; lastY = event.clientY;
  }
  const onPointerLeave = () => ndc.set(2, 2);
  function onWheel(event: WheelEvent) {
    if (ambient) return;
    event.preventDefault();
    distanceTarget = Math.max(52, Math.min(230, distanceTarget + event.deltaY * 0.16));
  }

  const pointerHost: HTMLElement | Window = ambient ? window : renderer.domElement;
  if (!ambient) {
    renderer.domElement.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("pointerup", onPointerUp);
    renderer.domElement.addEventListener("pointerleave", onPointerLeave);
    renderer.domElement.addEventListener("wheel", onWheel, { passive: false });
  }
  pointerHost.addEventListener("pointermove", onPointerMove as EventListener);

  function resize() {
    const width = container.clientWidth || 1;
    const height = container.clientHeight || 1;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }
  resize();
  const observer = typeof ResizeObserver === "function" ? new ResizeObserver(resize) : null;
  if (observer) observer.observe(container); else window.addEventListener("resize", resize);

  const clock = new THREE.Clock();
  let running = true;
  let frameHandle = 0;
  const spin = motion === "Still" ? 0 : motion === "Calm" ? 0.00016 : 0.00034;

  function frame() {
    if (!running) return;
    frameHandle = requestAnimationFrame(frame);
    const delta = Math.min(clock.getDelta(), 0.05);
    const time = clock.elapsedTime;

    reveal = Math.min(1, reveal + delta * 0.55);
    const ease = 1 - Math.pow(1 - reveal, 3);

    if (!dragging && !reduced) yawVelocity += spin * (ambient ? 1.25 : 1) * 60 * delta;
    yaw += yawVelocity;
    pitch = Math.max(-1.05, Math.min(1.05, pitch + pitchVelocity));
    yawVelocity *= 0.9;
    pitchVelocity *= 0.9;
    distance += (distanceTarget - distance) * 0.08;

    smoothX += (pointerX - smoothX) * 0.05;
    smoothY += (pointerY - smoothY) * 0.05;
    const parallaxX = ambient ? smoothX * 9 : smoothX * 3.2;
    const parallaxY = ambient ? smoothY * 6 : smoothY * 2.2;

    const radius = distance * (2 - ease);
    camera.position.set(
      target.x + Math.sin(yaw) * Math.cos(pitch) * radius + parallaxX,
      target.y + Math.sin(pitch) * radius + parallaxY,
      target.z + Math.cos(yaw) * Math.cos(pitch) * radius
    );
    camera.lookAt(target);
    world.rotation.z = reduced ? 0 : Math.sin(time * 0.11) * 0.012;

    const edgeCount = graph.edges.length;
    if (edgeCount) {
      packets.forEach((packet, i) => {
        packet.t += packet.v * delta * (motion === "Still" ? 0 : motion === "Calm" ? 0.5 : 1);
        if (packet.t > 1) {
          packet.t = 0;
          packet.edge = Math.floor(Math.random() * edgeCount);
          packet.v = 0.06 + Math.random() * 0.16;
        }
        const edge = graph.edges[packet.edge % edgeCount];
        const a = graph.nodes[edge.s];
        const b = graph.nodes[edge.t];
        packetPos[i * 3] = a.x + (b.x - a.x) * packet.t;
        packetPos[i * 3 + 1] = a.y + (b.y - a.y) * packet.t;
        packetPos[i * 3 + 2] = a.z + (b.z - a.z) * packet.t;
        packetGlow[i] = 0.3 + Math.sin(packet.t * Math.PI) * 0.55;
        packetDim[i] = ease * Math.min(dimAttr[edge.s], dimAttr[edge.t]);
      });
      packetGeometry.attributes.position.needsUpdate = true;
      packetGeometry.attributes.glow.needsUpdate = true;
      packetGeometry.attributes.dim.needsUpdate = true;
    }

    if (!ambient && ndc.x <= 1) {
      raycaster.setFromCamera(ndc, camera);
      const hits = raycaster.intersectObject(points, false);
      const index = hits.length && hits[0].index !== undefined ? (hits[0].index as number) : -1;
      if (index !== hovered) {
        if (hovered >= 0 && hovered !== selected) setGlow(hovered, 0.12);
        hovered = index;
        if (index >= 0 && index !== selected) setGlow(index, 1);
        if (selected < 0) applyHighlight(index);
        renderer.domElement.style.cursor = index >= 0 ? "pointer" : dragging ? "grabbing" : "grab";
        options.onHover?.(index >= 0 ? graph.nodes[index] : null);
      }
    }

    if (selected >= 0) {
      glowAttr[selected] = 1.2 + Math.sin(time * 3.4) * 0.45;
      nodeGeometry.attributes.glow.needsUpdate = true;
      highlightMaterial.opacity = 0.65 + Math.sin(time * 3.4) * 0.22;
    }

    edgeMaterial.opacity = baseEdgeOpacity * ease;
    renderer.render(scene, camera);
  }
  frame();

  function onVisibility() {
    if (document.hidden) {
      running = false;
      cancelAnimationFrame(frameHandle);
    } else if (!running) {
      running = true;
      clock.getDelta();
      frame();
    }
  }
  document.addEventListener("visibilitychange", onVisibility);

  return {
    dispose() {
      running = false;
      cancelAnimationFrame(frameHandle);
      document.removeEventListener("visibilitychange", onVisibility);
      pointerHost.removeEventListener("pointermove", onPointerMove as EventListener);
      if (!ambient) {
        renderer.domElement.removeEventListener("pointerdown", onPointerDown);
        window.removeEventListener("pointerup", onPointerUp);
        renderer.domElement.removeEventListener("pointerleave", onPointerLeave);
        renderer.domElement.removeEventListener("wheel", onWheel);
      }
      if (observer) observer.disconnect(); else window.removeEventListener("resize", resize);
      nodeGeometry.dispose(); edgeGeometry.dispose(); highlightGeometry.dispose();
      packetGeometry.dispose(); dustGeometry.dispose();
      nodeMaterial.dispose(); edgeMaterial.dispose(); highlightMaterial.dispose();
      renderer.dispose();
      renderer.domElement.parentNode?.removeChild(renderer.domElement);
    },
    setData(data: FieldData) {
      if (!data || !data.nodes.length) return;
      const selectedUrn = selected >= 0 ? graph.nodes[selected].urn : null;
      graph = layout(data);
      hovered = -1;
      selected = -1;
      buildBuffers();
      if (selectedUrn) {
        const next = graph.nodes.findIndex((n) => n.urn === selectedUrn);
        if (next >= 0) selectIndex(next);
      }
    },
    setQuery,
    select(urn: string | null) {
      if (!urn) { selectIndex(-1); return; }
      const index = graph.nodes.findIndex((node) => node.urn === urn);
      selectIndex(index);
    },
    resize
  };
}
