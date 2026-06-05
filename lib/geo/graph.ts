import type { LatLng } from "@/lib/types";
import type { StreetSegment } from "./types";
import { haversine } from "./util";

export interface GraphEdge {
  a: number; // node index
  b: number;
  len: number; // meters
  name?: string;
  /** full geometry from node a → node b (a "block" can span many OSM points) */
  points: LatLng[];
}

export interface StreetGraph {
  nodes: LatLng[];
  /** per node: incident edges with the neighbour node */
  adj: { edge: number; to: number }[][];
  edges: GraphEdge[];
  nearest: (p: LatLng) => number;
}

// Snap to ~1.1m grid so OSM ways that share an intersection node connect.
const keyOf = (p: LatLng) => `${p.lat.toFixed(5)},${p.lng.toFixed(5)}`;

/**
 * Build a routable graph from OSM street geometry. Consecutive points in a way
 * become edges; shared intersection nodes (snapped) connect ways together — so
 * any path through the graph follows real streets.
 */
export function buildGraph(segments: StreetSegment[]): StreetGraph {
  const index = new Map<string, number>();
  const nodes: LatLng[] = [];
  const adj: { edge: number; to: number }[][] = [];
  const edges: GraphEdge[] = [];

  const getNode = (p: LatLng): number => {
    const k = keyOf(p);
    let i = index.get(k);
    if (i === undefined) {
      i = nodes.length;
      index.set(k, i);
      nodes.push(p);
      adj.push([]);
    }
    return i;
  };

  for (const seg of segments) {
    for (let i = 1; i < seg.points.length; i++) {
      const a = getNode(seg.points[i - 1]);
      const b = getNode(seg.points[i]);
      if (a === b) continue;
      const len = haversine(nodes[a], nodes[b]);
      const ei = edges.length;
      edges.push({ a, b, len, name: seg.name, points: [nodes[a], nodes[b]] });
      adj[a].push({ edge: ei, to: b });
      adj[b].push({ edge: ei, to: a });
    }
  }

  const nearest = (p: LatLng) => {
    let best = 0;
    let bd = Infinity;
    for (let i = 0; i < nodes.length; i++) {
      const d = haversine(p, nodes[i]);
      if (d < bd) {
        bd = d;
        best = i;
      }
    }
    return best;
  };

  return { nodes, adj, edges, nearest };
}

/** Binary min-heap for Dijkstra. */
class MinHeap {
  private a: { d: number; n: number }[] = [];
  get size() {
    return this.a.length;
  }
  push(d: number, n: number) {
    const a = this.a;
    a.push({ d, n });
    let i = a.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (a[p].d <= a[i].d) break;
      [a[p], a[i]] = [a[i], a[p]];
      i = p;
    }
  }
  pop() {
    const a = this.a;
    const top = a[0];
    const last = a.pop()!;
    if (a.length) {
      a[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let s = i;
        if (l < a.length && a[l].d < a[s].d) s = l;
        if (r < a.length && a[r].d < a[s].d) s = r;
        if (s === i) break;
        [a[s], a[i]] = [a[i], a[s]];
        i = s;
      }
    }
    return top;
  }
}

/** Dijkstra from src (optionally restricted to `allowed` edges). Returns dist + prev. */
export function dijkstraFrom(
  g: StreetGraph,
  src: number,
  allowed?: Set<number>,
): { dist: Float64Array; prev: Int32Array } {
  const dist = new Float64Array(g.nodes.length).fill(Infinity);
  const prev = new Int32Array(g.nodes.length).fill(-1);
  dist[src] = 0;
  const heap = new MinHeap();
  heap.push(0, src);
  while (heap.size) {
    const { d, n } = heap.pop();
    if (d > dist[n]) continue;
    for (const { to, edge } of g.adj[n]) {
      if (allowed && !allowed.has(edge)) continue;
      const nd = d + g.edges[edge].len;
      if (nd < dist[to]) {
        dist[to] = nd;
        prev[to] = n;
        heap.push(nd, to);
      }
    }
  }
  return { dist, prev };
}

/** Reconstruct the node path src→target from a `prev` array (or null). */
export function reconstruct(prev: Int32Array, target: number): number[] | null {
  if (prev[target] === -1 && target !== -1) {
    // could be src itself; caller checks
  }
  const path: number[] = [];
  let c = target;
  let guard = 0;
  while (c !== -1 && guard++ < 100000) {
    path.push(c);
    c = prev[c];
  }
  return path.length ? path.reverse() : null;
}

/**
 * Shortest on-street path (node sequence) from `src` to the nearest node in
 * `targets`. Returns the node-index path (inclusive of both ends), or null.
 */
export function shortestPathToAny(
  g: StreetGraph,
  src: number,
  targets: Set<number>,
  allowed?: Set<number>,
): number[] | null {
  if (targets.has(src)) return [src];
  const dist = new Float64Array(g.nodes.length).fill(Infinity);
  const prev = new Int32Array(g.nodes.length).fill(-1);
  dist[src] = 0;
  const heap = new MinHeap();
  heap.push(0, src);
  while (heap.size) {
    const { d, n } = heap.pop();
    if (d > dist[n]) continue;
    if (targets.has(n)) {
      const path: number[] = [];
      let c = n;
      while (c !== -1) {
        path.push(c);
        c = prev[c];
      }
      return path.reverse();
    }
    for (const { to, edge } of g.adj[n]) {
      if (allowed && !allowed.has(edge)) continue; // stay within the allowed street set
      const nd = d + g.edges[edge].len;
      if (nd < dist[to]) {
        dist[to] = nd;
        prev[to] = n;
        heap.push(nd, to);
      }
    }
  }
  return null;
}

/**
 * Collapse pass-through (degree-2) points so each edge becomes one whole street
 * BLOCK between intersections (or to a dead-end). Planning then treats a block
 * atomically — a street is covered whole, never half. Homes are aggregated per
 * block from the fine-edge assignment.
 */
export function contractGraph(
  fine: StreetGraph,
  homesPerFineEdge: Float64Array,
): { graph: StreetGraph; homes: Float64Array } {
  const degree = fine.adj.map((a) => a.length);
  const isReal = (n: number) => degree[n] !== 2; // intersection or dead-end

  const newIndex = new Map<number, number>();
  const nodes: LatLng[] = [];
  const adj: { edge: number; to: number }[][] = [];
  const edges: GraphEdge[] = [];
  const homes: number[] = [];

  const getNode = (oldN: number) => {
    let i = newIndex.get(oldN);
    if (i === undefined) {
      i = nodes.length;
      newIndex.set(oldN, i);
      nodes.push(fine.nodes[oldN]);
      adj.push([]);
    }
    return i;
  };
  const addBlock = (an: number, bn: number, points: LatLng[], len: number, name: string | undefined, h: number) => {
    const a = getNode(an);
    const b = getNode(bn);
    const ei = edges.length;
    edges.push({ a, b, len, name, points });
    homes.push(h);
    adj[a].push({ edge: ei, to: b });
    adj[b].push({ edge: ei, to: a });
  };

  const used = new Set<number>(); // fine edge indices consumed

  const walkChain = (startReal: number, firstEdge: number, firstTo: number) => {
    const points: LatLng[] = [fine.nodes[startReal], fine.nodes[firstTo]];
    let len = fine.edges[firstEdge].len;
    let h = homesPerFineEdge[firstEdge];
    const names = new Map<string, number>();
    if (fine.edges[firstEdge].name) names.set(fine.edges[firstEdge].name!, len);
    used.add(firstEdge);
    let prevEdge = firstEdge;
    let cur = firstTo;
    while (!isReal(cur)) {
      let nextE = -1;
      let nextN = -1;
      for (const { edge, to } of fine.adj[cur]) {
        if (edge !== prevEdge && !used.has(edge)) {
          nextE = edge;
          nextN = to;
          break;
        }
      }
      if (nextE === -1) break;
      used.add(nextE);
      points.push(fine.nodes[nextN]);
      len += fine.edges[nextE].len;
      h += homesPerFineEdge[nextE];
      const nm = fine.edges[nextE].name;
      if (nm) names.set(nm, (names.get(nm) ?? 0) + fine.edges[nextE].len);
      prevEdge = nextE;
      cur = nextN;
    }
    const name = [...names.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
    addBlock(startReal, cur, points, len, name, h);
  };

  for (let r = 0; r < fine.nodes.length; r++) {
    if (!isReal(r)) continue;
    for (const { edge, to } of fine.adj[r]) {
      if (used.has(edge)) continue;
      walkChain(r, edge, to);
    }
  }
  // pure cycles (no real node in the component)
  for (let fe = 0; fe < fine.edges.length; fe++) {
    if (used.has(fe)) continue;
    walkChain(fine.edges[fe].a, fe, fine.edges[fe].b);
  }

  const nearest = (p: LatLng) => {
    let best = 0;
    let bd = Infinity;
    for (let i = 0; i < nodes.length; i++) {
      const d = haversine(p, nodes[i]);
      if (d < bd) {
        bd = d;
        best = i;
      }
    }
    return best;
  };

  return { graph: { nodes, adj, edges, nearest }, homes: Float64Array.from(homes) };
}
