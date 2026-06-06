import type { LatLng } from "@/lib/types";
import type { StreetSegment } from "./types";
import { buildGraph, contractGraph, shortestPathToAny, dijkstraFrom, reconstruct, type StreetGraph } from "./graph";
import { edgeTimeSec, type PaceModel, DEFAULT_PACE } from "./capacity";
import { pointToSegment, polylineLength, haversine } from "./util";

// Open trails with pruned cul-de-sacs re-walk little, so the budget walk only
// needs a small overhead vs the one-pass street length.
const WALK_OVERHEAD = 1.25;

export interface PlannedZone {
  path: LatLng[];
  meters: number;
  doors: number;
  minutes: number;
  topStreets: string[];
  center: LatLng;
  meet: LatLng;
}

const edgeMid = (g: StreetGraph, ei: number): LatLng => {
  const pts = g.edges[ei].points;
  return pts.length ? pts[Math.floor(pts.length / 2)] : g.nodes[g.edges[ei].a];
};
const d2 = (a: LatLng, b: LatLng) => (a.lat - b.lat) ** 2 + (a.lng - b.lng) ** 2;

/** Count real homes onto the street edge each one fronts (within ~70 m). */
function assignHomes(g: StreetGraph, homes: LatLng[]): Float64Array {
  const hpe = new Float64Array(g.edges.length);
  for (const h of homes) {
    let bn = -1;
    let bd = Infinity;
    for (let i = 0; i < g.nodes.length; i++) {
      const dd = d2(g.nodes[i], h);
      if (dd < bd) {
        bd = dd;
        bn = i;
      }
    }
    if (bn < 0) continue;
    let be = -1;
    let bed = Infinity;
    for (const { edge } of g.adj[bn]) {
      const e = g.edges[edge];
      const dist = pointToSegment(h, g.nodes[e.a], g.nodes[e.b]);
      if (dist < bed) {
        bed = dist;
        be = edge;
      }
    }
    if (be >= 0 && bed <= 70) hpe[be] += 1;
  }
  return hpe;
}

/** Nearest node to `center` that still has an unclaimed incident edge. */
function nearestUnclaimedNode(g: StreetGraph, center: LatLng, claimed: Set<number>): number {
  let best = -1;
  let bd = Infinity;
  for (let i = 0; i < g.nodes.length; i++) {
    let has = false;
    for (const { edge } of g.adj[i]) {
      if (!claimed.has(edge)) {
        has = true;
        break;
      }
    }
    if (!has) continue;
    const dd = d2(g.nodes[i], center);
    if (dd < bd) {
      bd = dd;
      best = i;
    }
  }
  return best;
}

/** Grow ONE compact, EXCLUSIVE block from `seed`, claiming only unclaimed edges
 *  until the time budget is hit. Each pair gets distinct adjacent turf (no
 *  overlap); the next pair's seed starts at this block's boundary. */
function growCompact(
  g: StreetGraph,
  seed: number,
  budgetSec: number,
  claimed: Set<number>,
  cost: (e: number) => number,
): number[] {
  const region: number[] = [];
  let total = 0;
  const dist = new Float64Array(g.nodes.length).fill(Infinity);
  dist[seed] = 0;
  const pq: { d: number; n: number }[] = [{ d: 0, n: seed }];
  while (pq.length && total < budgetSec) {
    let bi = 0;
    for (let i = 1; i < pq.length; i++) if (pq[i].d < pq[bi].d) bi = i;
    const { d, n } = pq.splice(bi, 1)[0];
    if (d > dist[n]) continue;
    for (const { edge, to } of g.adj[n]) {
      if (claimed.has(edge)) continue; // exclusive - never another pair's street
      claimed.add(edge);
      region.push(edge);
      total += cost(edge);
      const nd = d + g.edges[edge].len;
      if (nd < dist[to]) {
        dist[to] = nd;
        pq.push({ d: nd, n: to });
      }
      if (total >= budgetSec) break;
    }
  }
  return region;
}

/**
 * Minimum-weight matching of odd-degree nodes (within `allowed` streets) → the
 * set of paths to duplicate so a covering circuit exists with the LEAST extra
 * walking. Exact (bitmask DP) for small odd-sets, greedy nearest beyond.
 * Result: the only re-walked streets are unavoidable dead-end spurs.
 */
function minWeightMatching(g: StreetGraph, odd: number[], allowed: Set<number>): number[][] {
  const n = odd.length;
  if (n < 2) return [];
  const dij = odd.map((o) => dijkstraFrom(g, o, allowed));
  const D: number[][] = [];
  const P: (number[] | null)[][] = [];
  for (let i = 0; i < n; i++) {
    D[i] = [];
    P[i] = [];
    for (let j = 0; j < n; j++) {
      if (i === j) {
        D[i][j] = 0;
        P[i][j] = null;
        continue;
      }
      const d = dij[i].dist[odd[j]];
      D[i][j] = Number.isFinite(d) ? d : 1e12;
      P[i][j] = Number.isFinite(d) ? reconstruct(dij[i].prev, odd[j]) : null;
    }
  }

  const pairs: [number, number][] = [];
  if (n <= 18) {
    // exact min-weight perfect matching via bitmask DP
    const full = (1 << n) - 1;
    const dp = new Float64Array(1 << n).fill(Infinity);
    dp[0] = 0;
    const par = new Int32Array(1 << n).fill(-1);
    for (let mask = 0; mask <= full; mask++) {
      if (dp[mask] === Infinity) continue;
      let i = 0;
      while (i < n && mask & (1 << i)) i++;
      if (i >= n) continue;
      for (let j = i + 1; j < n; j++) {
        if (mask & (1 << j)) continue;
        const nm = mask | (1 << i) | (1 << j);
        const c = dp[mask] + D[i][j];
        if (c < dp[nm]) {
          dp[nm] = c;
          par[nm] = (i << 8) | j;
        }
      }
    }
    let mask = full;
    while (mask > 0) {
      const pij = par[mask];
      if (pij < 0) break;
      const i = pij >> 8;
      const j = pij & 0xff;
      pairs.push([i, j]);
      mask &= ~((1 << i) | (1 << j));
    }
  } else {
    // global shortest-edge greedy (near-optimal): always take the cheapest pair
    const cand: [number, number, number][] = [];
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) cand.push([D[i][j], i, j]);
    cand.sort((a, b) => a[0] - b[0]);
    const used = new Array(n).fill(false);
    for (const [, i, j] of cand) {
      if (used[i] || used[j]) continue;
      used[i] = used[j] = true;
      pairs.push([i, j]);
    }
  }

  const paths: number[][] = [];
  for (const [i, j] of pairs) {
    const p = P[i][j];
    if (p && p.length >= 2) paths.push(p);
  }
  return paths;
}

/**
 * Closed walking LOOP for a zone - a route-inspection (Chinese-Postman style)
 * Eulerian circuit: connect components, even-out odd nodes via shortest on-street
 * paths, then Hierholzer. Starts and ends at the meet node (nearest the center),
 * covering every street with minimal re-walking.
 */
/** Remove dead-end spurs longer than `maxSpur` (defer them to a later session)
 *  so the route never has to walk in-and-out of a long cul-de-sac. Short stubs
 *  (a quick dip) are kept. */
function pruneLongSpurs(g: StreetGraph, zoneEdges: number[], maxSpur = 90): number[] {
  const kept = new Set(zoneEdges);
  for (let pass = 0; pass < 12; pass++) {
    const deg = new Map<number, number>();
    for (const ei of kept) {
      const e = g.edges[ei];
      deg.set(e.a, (deg.get(e.a) ?? 0) + 1);
      deg.set(e.b, (deg.get(e.b) ?? 0) + 1);
    }
    let removed = false;
    for (const [node, d] of deg) {
      if (d !== 1) continue;
      const stub: number[] = [];
      let len = 0;
      let cur = node;
      let prevEdge = -1;
      while (true) {
        let nextEdge = -1;
        let nextNode = -1;
        for (const { edge, to } of g.adj[cur]) {
          if (edge !== prevEdge && kept.has(edge)) {
            nextEdge = edge;
            nextNode = to;
            break;
          }
        }
        if (nextEdge === -1) break;
        stub.push(nextEdge);
        len += g.edges[nextEdge].len;
        prevEdge = nextEdge;
        cur = nextNode;
        if ((deg.get(cur) ?? 0) !== 2) break; // hit a junction
      }
      if (len > maxSpur) {
        for (const e of stub) kept.delete(e);
        removed = true;
      }
    }
    if (!removed) break;
  }
  return [...kept];
}

/** Open covering TRAIL (route inspection) - cover each street once with the
 *  fewest repeats, NOT forced to return to start. Leaves the most-expensive
 *  odd-vertex pair as the open start/end, matches the rest. */
function coverTrail(g: StreetGraph, keptEdges: number[], meet: LatLng): { path: LatLng[]; start: number } {
  if (!keptEdges.length) return { path: [], start: -1 };
  const allowed = new Set(keptEdges);
  const sp = (src: number, targets: Set<number>) =>
    shortestPathToAny(g, src, targets, allowed) ?? shortestPathToAny(g, src, targets);
  const instAdj: number[][] = Array.from({ length: g.nodes.length }, () => []);
  const inst: { a: number; b: number }[] = [];
  const addInst = (a: number, b: number) => {
    const id = inst.length;
    inst.push({ a, b });
    instAdj[a].push(id);
    instAdj[b].push(id);
  };
  for (const ei of keptEdges) addInst(g.edges[ei].a, g.edges[ei].b);

  const zoneNodes = new Set<number>();
  for (const ei of keptEdges) {
    zoneNodes.add(g.edges[ei].a);
    zoneNodes.add(g.edges[ei].b);
  }

  // connect disjoint components
  const comp = new Map<number, number>();
  let cid = 0;
  for (const s of zoneNodes) {
    if (comp.has(s)) continue;
    const st = [s];
    comp.set(s, cid);
    while (st.length) {
      const v = st.pop()!;
      for (const id of instAdj[v]) {
        const e = inst[id];
        const to = e.a === v ? e.b : e.a;
        if (!comp.has(to)) {
          comp.set(to, cid);
          st.push(to);
        }
      }
    }
    cid++;
  }
  if (cid > 1) {
    const byComp = new Map<number, number[]>();
    for (const [n, c] of comp) (byComp.get(c) ?? byComp.set(c, []).get(c)!).push(n);
    const mainNode = byComp.get(0)![0];
    for (let c = 1; c < cid; c++) {
      const path = sp(mainNode, new Set(byComp.get(c)));
      if (path) for (let i = 1; i < path.length; i++) addInst(path[i - 1], path[i]);
    }
  }

  const odd = [...new Set([...zoneNodes, ...inst.flatMap((e) => [e.a, e.b])])].filter(
    (n) => instAdj[n].length % 2 === 1,
  );
  const matches = minWeightMatching(g, odd, allowed);
  const plen = (p: number[]) => {
    let s = 0;
    for (let i = 1; i < p.length; i++) s += haversine(g.nodes[p[i - 1]], g.nodes[p[i]]);
    return s;
  };
  let start = -1;
  if (matches.length > 0) {
    matches.sort((a, b) => plen(b) - plen(a));
    start = matches[0][0]; // leave the costliest pair OPEN - its ends are the trail ends
    for (let m = 1; m < matches.length; m++) {
      const p = matches[m];
      for (let i = 1; i < p.length; i++) addInst(p[i - 1], p[i]);
    }
  }
  if (start === -1) {
    let bd = Infinity;
    for (const n of zoneNodes) {
      const dd = d2(g.nodes[n], meet);
      if (dd < bd) {
        bd = dd;
        start = n;
      }
    }
  }
  if (start === -1) return { path: [], start: -1 };

  // Hierholzer (Euler trail from `start`)
  const used = new Array(inst.length).fill(false);
  const ptr = new Array(g.nodes.length).fill(0);
  const stack = [start];
  const out: number[] = [];
  while (stack.length) {
    const v = stack[stack.length - 1];
    while (ptr[v] < instAdj[v].length && used[instAdj[v][ptr[v]]]) ptr[v]++;
    if (ptr[v] >= instAdj[v].length) {
      out.push(v);
      stack.pop();
    } else {
      const id = instAdj[v][ptr[v]];
      used[id] = true;
      const e = inst[id];
      stack.push(e.a === v ? e.b : e.a);
    }
  }
  out.reverse();
  // Build the path from full BLOCK geometry so each street is drawn whole.
  const path: LatLng[] = [];
  for (let i = 0; i < out.length; i++) {
    if (i === 0) {
      path.push(g.nodes[out[0]]);
      continue;
    }
    const prev = out[i - 1];
    const node = out[i];
    const be = g.adj[prev].find((a) => a.to === node)?.edge;
    if (be !== undefined) {
      const blk = g.edges[be];
      const pts = blk.a === prev ? blk.points : [...blk.points].reverse();
      for (let k = 1; k < pts.length; k++) path.push(pts[k]);
    } else {
      path.push(g.nodes[node]);
    }
  }
  return { path, start };
}

interface LoopResult {
  path: LatLng[];
  loopMeters: number;
  doors: number;
  minutes: number;
  keptEdges: number[];
}

function buildLoopResult(
  g: StreetGraph,
  zoneEdges: number[],
  meet: LatLng,
  hpe: Float64Array,
  pace: PaceModel,
  people: number,
): LoopResult {
  // defer long cul-de-sacs, then cover the rest as an open minimal-repeat trail.
  // If pruning would strip a small zone to nothing, keep it unpruned - a short
  // route beats an empty one (this is what dropped tiny/over-trimmed zones).
  const pruned = pruneLongSpurs(g, zoneEdges);
  const keptEdges = pruned.length ? pruned : zoneEdges;
  const { path } = coverTrail(g, keptEdges, meet);
  const loopMeters = polylineLength(path);
  const doors = Math.round(keptEdges.reduce((a, ei) => a + hpe[ei], 0)); // covered streets only
  const knock = (doors / Math.max(1, people)) * pace.timePerDoorSec;
  const minutes = Math.round((knock + loopMeters / pace.walkSpeedMps) / 60);
  return { path, loopMeters, doors, minutes, keptEdges };
}

/** Size a zone to the session budget by keeping the LARGEST core of streets,
 *  nearest the meet point outward, whose ACTUAL covering-trail (walk + knock)
 *  time fits the budget. We binary-search the cut so we use as much of the
 *  session as possible (no tiny routes) without overshooting, and we always keep
 *  a usable core (never drop the zone). Replaces an older chunked farthest-first
 *  trim that overshot wildly - shrinking a full zone to a sliver and sometimes
 *  collapsing the second pair's zone to nothing. */
function fitZoneToBudget(
  g: StreetGraph,
  zoneEdges: number[],
  meet: LatLng,
  budgetSec: number,
  hpe: Float64Array,
  pace: PaceModel,
  people: number,
): { edges: number[] } & LoopResult {
  // Streets ordered compactly from the meet outward; we pack them in greedily.
  const sorted = [...zoneEdges].sort((a, b) => d2(edgeMid(g, a), meet) - d2(edgeMid(g, b), meet));
  const cap = budgetSec * 1.1; // a route may run a touch over a full session
  const minKeep = Math.min(sorted.length, 4);

  // Greedily add streets nearest-first; keep one whenever it still fits the
  // session, otherwise skip it and try the next (so one oversized street near the
  // edge doesn't stop us from filling the rest of the session). Stop once we've
  // essentially filled the budget, so the zone stays tight around the meet.
  let kept: number[] = [];
  let res = buildLoopResult(g, kept, meet, hpe, pace, people);
  for (const e of sorted) {
    const trial = [...kept, e];
    const r = buildLoopResult(g, trial, meet, hpe, pace, people);
    if (r.minutes * 60 <= cap) {
      kept = trial;
      res = r;
      if (kept.length >= minKeep && r.minutes * 60 >= budgetSec * 0.95) break; // budget filled
    }
  }
  // Never return an empty/degenerate zone - keep a small nearest core at minimum.
  if (kept.length < minKeep) {
    kept = sorted.slice(0, minKeep);
    res = buildLoopResult(g, kept, meet, hpe, pace, people);
  }
  return { edges: kept, ...res };
}

export function planCoverage(
  streets: StreetSegment[],
  homes: LatLng[],
  center: LatLng,
  budgetsSec: number[],
  pace: PaceModel = DEFAULT_PACE,
  peoplePerGroup: number[] = [],
): { zones: PlannedZone[]; totalHomes: number } {
  // assign homes on the fine graph (short segments = accurate), then contract
  // to a BLOCK graph so each street is planned/covered as one whole unit.
  const fine = buildGraph(streets);
  if (!fine.nodes.length || !budgetsSec.length) return { zones: [], totalHomes: 0 };
  const hpeFine = assignHomes(fine, homes);
  const { graph: g, homes: blockHomes } = contractGraph(fine, hpeFine);

  let homesPerEdge = blockHomes;
  const assigned = homesPerEdge.reduce((a, b) => a + b, 0);
  if (assigned < 1) {
    // no building data - fall back to a suburban density estimate
    homesPerEdge = Float64Array.from(g.edges.map((e) => e.len / 20));
  }

  const peopleFor = (z: number) => peoplePerGroup[z] ?? 2;

  // Grow each pair's block one at a time from the center outward, claiming
  // streets exclusively → distinct, adjacent, non-overlapping neighborhoods.
  // Cost knocks homes in parallel (one per side) and inflates walking by loop overhead.
  const claimed = new Set<number>();
  const groups: number[][] = [];
  for (let z = 0; z < budgetsSec.length; z++) {
    const people = peopleFor(z);
    const cost = (ei: number) => edgeTimeSec(homesPerEdge[ei], g.edges[ei].len * WALK_OVERHEAD, pace, people);
    const seed = z === 0 ? g.nearest(center) : nearestUnclaimedNode(g, center, claimed);
    if (seed < 0) break;
    // over-grow so enough through-streets survive cul-de-sac pruning to fill the session
    const region = growCompact(g, seed, budgetsSec[z] * 1.5, claimed, cost);
    if (region.length) groups.push(region);
  }
  if (!groups.length) return { zones: [], totalHomes: Math.round(assigned) };

  const zones: PlannedZone[] = groups.map((zoneEdges, gi) => {
    const budget = budgetsSec[Math.min(gi, budgetsSec.length - 1)];
    const people = peopleFor(gi);
    // meet point = nearest node to this block's centre, near the area centre
    const zmids0 = zoneEdges.map((ei) => edgeMid(g, ei));
    const zcenter0 = zmids0.reduce((a, m) => ({ lat: a.lat + m.lat, lng: a.lng + m.lng }), { lat: 0, lng: 0 });
    const meetCoord = { lat: zcenter0.lat / zmids0.length, lng: zcenter0.lng / zmids0.length };
    const fit = fitZoneToBudget(g, zoneEdges, meetCoord, budget, homesPerEdge, pace, people);
    const ze = fit.keptEdges.length ? fit.keptEdges : fit.edges; // name/center from covered streets
    const names = new Map<string, number>();
    for (const ei of ze) {
      const n = g.edges[ei].name;
      if (n) names.set(n, (names.get(n) ?? 0) + g.edges[ei].len);
    }
    const topStreets = [...names.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([n]) => n);
    const mids = ze.map((ei) => edgeMid(g, ei));
    const zc = mids.reduce((a, m) => ({ lat: a.lat + m.lat, lng: a.lng + m.lng }), { lat: 0, lng: 0 });
    const n = Math.max(1, mids.length);
    return {
      path: fit.path,
      meters: Math.round(fit.loopMeters),
      doors: fit.doors,
      minutes: fit.minutes,
      topStreets,
      center: { lat: zc.lat / n, lng: zc.lng / n },
      meet: fit.path[0] ?? meetCoord,
    };
  });

  return { zones, totalHomes: Math.round(assigned) };
}
