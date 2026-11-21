/* The mission map: a slippy map built to be flown over, not looked at.
 *
 * WHY THIS IS NOT TerrainMap
 * --------------------------
 * TerrainMap is correct and it is slow, for one structural reason: the camera
 * lives in React state. Every pixel of a pan set state, which re-rendered the
 * whole map, which re-ran the projection over every waypoint, every event,
 * every reach ring AND every flight sample -- several hundred of them -- to
 * rebuild two polyline strings that had not changed shape at all. Panning a
 * simulated sortie was rebuilding a kilobyte of SVG path data sixty times a
 * second to move a picture sideways.
 *
 * THE FIX IS GEOMETRIC, NOT A MICRO-OPTIMISATION
 * ----------------------------------------------
 * Everything drawn is laid out ONCE in world pixels at the current integer
 * tile zoom -- tiles, route, track, rings, markers, all in the same coordinate
 * system -- inside a single positioned element. Moving the camera then writes
 * one `transform` on that one element. Panning recomputes nothing; it does not
 * even re-render. React is only involved when the integer zoom changes or the
 * viewport crosses a tile boundary, which is a handful of times per gesture
 * instead of a thousand.
 *
 * Two consequences fall out of that and both are wanted. Strokes carry
 * `vector-effect: non-scaling-stroke`, so a route line stays one width while
 * the ground under it scales. Symbols -- waypoints, bases, the aircraft --
 * sit in a counter-scaled group so they stay the same size on screen, which is
 * what a symbol is for; circles that represent a real distance, the reach
 * rings and the patrol areas, are left to scale with the ground, because they
 * are not symbols, they are distances.
 *
 * INTERACTION
 * -----------
 * The camera is a mutable ref driven by a requestAnimationFrame loop that runs
 * only while something is moving. The wheel sets a zoom TARGET and the loop
 * eases towards it about the cursor, so a wheel notch is a smooth fractional
 * move rather than a jump of a factor of two. A drag pans directly and leaves
 * velocity behind it, which decays; an operator throws the map and it comes to
 * rest. None of that touches React.
 *
 * WHAT IS CARRIED OVER FROM TerrainMap UNCHANGED
 * ----------------------------------------------
 * The tile layer list and its per-layer, per-tile health model: a tile that
 * fails is retried on the next host, a layer that keeps failing is reported as
 * degraded, and a layer that fails outright hands over to one that works and
 * says which and why. That behaviour was written against real tile services
 * having real bad days and there is no reason to rediscover it.
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { FlightEvent } from "../lib/api";
import { latOfMercY, mercY } from "../lib/geo";
import { AIRBASES, type Airbase, type BaseRole } from "../data/airbases";
import type { ExpandedPatrol, PlanPoint } from "../mission/plan";
import { Playback } from "../mission/clock";
import { LAYERS, type TileLayer } from "./TerrainMap";

const TILE = 256;
const MIN_ZOOM = 3;
const MAX_ZOOM = 17;
const TILE_RETRIES = 2;

/* How hard a throw carries, and how quickly it lets go. 0.90 per frame is
 * about a third of a second of glide at 60 Hz -- enough to feel like momentum,
 * short enough that the map is never still moving when the hand comes back. */
const PAN_EASE = 0.16;
const GLIDE = 0.9;
const GLIDE_FLOOR = 0.015;
/* Round numbers a scale bar is allowed to be. */
const NICE_KM = [0.5, 1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2000];
/* Fraction of the remaining zoom distance covered per frame. 0.22 settles in
 * roughly a sixth of a second and never overshoots. */
const ZOOM_EASE = 0.22;

type Health = "unknown" | "ok" | "degraded" | "down";

interface Cam { x: number; y: number; zoom: number; }   // x, y in unit mercator

const unitX = (lon: number) => (lon + 180) / 360;
const unitY = (lat: number) => 0.5 - mercY(lat) / (2 * Math.PI);
const lonOf = (x: number) => x * 360 - 180;
const latOf = (y: number) => latOfMercY((0.5 - y) * 2 * Math.PI);

export interface MapEvent extends Pick<FlightEvent, "lat_deg" | "lon_deg" | "severity"> {
  code?: string; message?: string; t_s?: number;
}

export interface MissionMapProps {
  /** The plan, as the operator built it. */
  points: PlanPoint[];
  /** The circuits a patrol area expanded into -- what will actually be flown. */
  patrols: ExpandedPatrol[];
  /** The expanded waypoint list, which is the line the aircraft will follow. */
  routeLine: { lat_deg: number; lon_deg: number }[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onAddPoint: (lat: number, lon: number) => void;
  onMovePoint: (id: string, lat: number, lon: number) => void;
  onBaseAction: (base: Airbase, role: BaseRole) => void;
  alternateId: string | null;
  /** Live playback. The map subscribes; it is never handed a frame index. */
  playback: Playback;
  events?: MapEvent[];
  onSeek?: (t: number) => void;
  envKm?: number;
  envNewKm?: number;
  /** Rendered height: a number of pixels, or a CSS length such as "100%".
   *  The width is always measured from the element. */
  height: number | string;
  /** PLAN / SIMULATE / ANALYZE -- changes what the map emphasises. */
  stage: "PLAN" | "FLYING" | "ANALYZE";
  /** Expose airfield actions while keeping the route itself read-only. */
  selectBases?: boolean;
  /** Which airfield actions to show. Defaults to all roles for existing callers. */
  baseActions?: BaseRole[];
  /* THE MAP IS THE PAGE, NOT A WIDGET ON IT. Full bleed drops the border and
   * the corner radius: there is nothing beside it for a frame to separate it
   * from, and a card edge around the whole workspace is a line that says the
   * work is happening somewhere else. */
  fullBleed?: boolean;
  /** The page's own floating instruments, rendered inside the map. */
  overlays?: React.ReactNode;
  /* SOMETHING GLUED TO A PLACE ON THE GROUND. The map already writes one
   * transform per frame; this is a second, so an editor opened on a waypoint
   * follows it through a pan and a zoom without the page re-rendering or ever
   * knowing where the camera is. */
  anchor?: { lat: number; lon: number; children: React.ReactNode } | null;
  /** Keeps the bottom furniture clear of whatever the page floats down there. */
  padBottom?: number;
  /* THE MAP IS AN EDITOR ONLY WHILE THE MISSION IS BEING PLANNED.
   * Once a sortie has been committed to the engine model, dragging a waypoint
   * would silently make the track, the verdict and the margins on screen
   * describe a route that no longer exists. So the editing gestures -- drop a
   * point, drag a point, open a field -- are switched off at the source rather
   * than undone afterwards. Pan, zoom, select and inspect stay live, because
   * none of them changes what was flown. */
  editable: boolean;
  /* WHAT A CLICK ON EMPTY GROUND MEANS, when the page offers a choice of
   * tools. "add" is the behaviour this map has always had and the default, so
   * a caller that says nothing gets exactly what it got before. "select"
   * leaves a click to pan, select and inspect -- the page's SELECT tool -- and
   * nothing is dropped on the ground by accident while an operator is reading
   * it. Fields stay clickable in both, because offering a field is not an
   * edit to the route. */
  clickIntent?: "add" | "select";
  /* THE LEG AS A PICKABLE OBJECT. Opt-in: with no handler no pick layer is
   * rendered and the map is byte-for-byte what it was. The strokes are
   * transparent and wide, and sit under the waypoints, so a click near a point
   * still gets the point. */
  onSelectLeg?: (i: number | null) => void;
  selectedLeg?: number | null;
}

export function MissionMap(props: MissionMapProps) {
  const boxRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const coordRef = useRef<HTMLDivElement>(null);
  const aircraftRef = useRef<SVGGElement>(null);
  const flownCaseRef = useRef<SVGPathElement>(null);
  const flownLineRef = useRef<SVGPathElement>(null);
  const barRef = useRef<HTMLSpanElement>(null);
  const barTextRef = useRef<HTMLSpanElement>(null);
  const pinRef = useRef<HTMLDivElement>(null);

  const [size, setSize] = useState({ w: 900, h: 420 });
  const [layer, setLayer] = useState<TileLayer>(
    LAYERS.find((l) => l.id === "terrain") ?? LAYERS[0]);
  const [health, setHealth] = useState<Record<string, Health>>({});
  const [handover, setHandover] = useState("");
  const [retry, setRetry] = useState<Record<string, number>>({});
  const [radar, setRadar] = useState(false);
  const [layerOpen, setLayerOpen] = useState(false);
  const [menu, setMenu] = useState<{ base: Airbase; x: number; y: number } | null>(null);

  /* The tile grid React knows about. Changes only when the integer zoom moves
   * or the viewport crosses a tile boundary -- a few times per gesture. */
  const [grid, setGrid] = useState({ z: 5, x0: 0, x1: 1, y0: 0, y1: 1 });

  const camRef = useRef<Cam>({ x: unitX(74.5), y: unitY(26.5), zoom: 5.4 });
  const zoomTargetRef = useRef(camRef.current.zoom);
  const anchorRef = useRef<{ x: number; y: number } | null>(null);
  const velRef = useRef({ x: 0, y: 0 });
  /* WHERE THE CAMERA IS GOING, when something other than the hand is moving
   * it: the fit button, the first framing, and a point selected in the panel
   * beside the map. Eased in the same loop as the zoom, so every automatic
   * move on this map is a move rather than a cut. */
  const panTargetRef = useRef<{ x: number; y: number } | null>(null);
  const dragRef = useRef<{ px: number; py: number; moved: number } | null>(null);
  const movingRef = useRef<{ id: string } | null>(null);
  const rafRef = useRef(0);
  const lastKRef = useRef(1);
  const tally = useRef({ id: layer.id, ok: 0, bad: 0 });
  const fitted = useRef("");

  const { w, h } = size;
  const sizeRef = useRef({ x: w / 2, y: h / 2 });
  sizeRef.current = { x: w / 2, y: h / 2 };

  /* ---- measurement ------------------------------------------------------ */
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const next = { w: Math.max(240, el.clientWidth), h: Math.max(200, el.clientHeight) };
      setSize((p) => (p.w === next.w && p.h === next.h ? p : next));
    });
    ro.observe(el);
    setSize({ w: Math.max(240, el.clientWidth), h: Math.max(200, el.clientHeight) });
    return () => ro.disconnect();
  }, []);

  /* ---- camera maths ----------------------------------------------------- */
  const worldPx = useCallback((zoom: number) => TILE * Math.pow(2, zoom), []);

  const screenToUnit = useCallback((px: number, py: number) => {
    const c = camRef.current;
    const S = worldPx(c.zoom);
    return { x: c.x + (px - w / 2) / S, y: c.y + (py - h / 2) / S };
  }, [w, h, worldPx]);

  const unitToScreen = useCallback((ux: number, uy: number) => {
    const c = camRef.current;
    const S = worldPx(c.zoom);
    return { x: w / 2 + (ux - c.x) * S, y: h / 2 + (uy - c.y) * S };
  }, [w, h, worldPx]);

  /* ---- the one write per frame ------------------------------------------ */
  /* THE TILE ZOOM THE DOM IS ACTUALLY SHOWING, which is not always the one in
   * state. `syncGrid` sets the new zoom during a frame; the tiles for it are
   * not mounted until React commits. Painting the transform for a zoom whose
   * tiles are not on screen yet is a visible jump every time a continuous zoom
   * crosses an integer, so this only moves in the layout effect below -- in
   * the same frame as the commit that mounted them. */
  const zRef = useRef(grid.z);

  const paint = useCallback(() => {
    const st = stageRef.current;
    if (!st) return;
    const c = camRef.current;
    const z = zRef.current;
    const Wz = worldPx(z);
    const k = Math.pow(2, c.zoom - z);
    const tx = w / 2 - c.x * Wz * k;
    const ty = h / 2 - c.y * Wz * k;
    st.style.transform =
      "translate3d(" + tx.toFixed(2) + "px," + ty.toFixed(2) + "px,0) scale(" + k + ")";

    /* The anchored editor, moved the same way and for the same reason. */
    const an = pinRef.current;
    if (an && an.dataset.lat) {
      const S = worldPx(c.zoom);
      const ax = w / 2 + (unitX(+an.dataset.lon!) - c.x) * S;
      const ay = h / 2 + (unitY(+an.dataset.lat!) - c.y) * S;
      const card = an.firstElementChild as HTMLElement | null;
      const ch = card?.offsetHeight ?? 200;
      // Clear of the bottom of the map AND of whatever the page floats there.
      const floor = h - 8 - (props.padBottom ?? 0) - ch + 40;
      const cy = Math.max(48, Math.min(ay, Math.max(48, floor)));
      an.style.transform =
        "translate3d(" + ax.toFixed(1) + "px," + cy.toFixed(1) + "px,0)";
      an.dataset.flip = ax > w - 300 ? "1" : "0";
    }
    /* Symbols must not grow with the ground. Rewritten only when the scale has
     * actually moved, so a pan costs nothing here. */
    if (Math.abs(k - lastKRef.current) > 1e-4) {
      lastKRef.current = k;
      const inv = 1 / k;
      st.querySelectorAll<SVGGElement>("[data-fixed]").forEach((g) => {
        g.setAttribute("transform", "scale(" + inv + ")");
      });
      /* THE SCALE BAR IS THE ONE PIECE OF FURNITURE THAT LIVES OUTSIDE THE
       * STAGE AND STILL DEPENDS ON THE CAMERA. It is written here rather than
       * rendered, because the alternative is a React render per wheel notch
       * to keep a 60-pixel rule honest. */
      const kmPerPx = (40075.016686 * Math.cos(latOf(c.y) * Math.PI / 180))
                      / worldPx(c.zoom);
      const km = NICE_KM.find((m) => m / kmPerPx > 76) ?? NICE_KM[NICE_KM.length - 1];
      if (barRef.current) barRef.current.style.width = Math.round(km / kmPerPx) + "px";
      if (barTextRef.current) {
        barTextRef.current.textContent = km >= 1 ? km + " km" : Math.round(km * 1000) + " m";
      }
    }
  }, [w, h, worldPx]);

  /* Which tiles the viewport needs, with one ring of margin so a pan does not
   * flash. Compared against what is mounted; state moves only on a change. */
  const syncGrid = useCallback(() => {
    const c = camRef.current;
    const z = Math.max(MIN_ZOOM, Math.min(Math.round(c.zoom), layer.maxZoom));
    const S = worldPx(c.zoom);
    const hx = w / 2 / S, hy = h / 2 / S;
    const n = Math.pow(2, z);
    const x0 = Math.floor((c.x - hx) * n) - 1;
    const x1 = Math.ceil((c.x + hx) * n) + 1;
    const y0 = Math.max(0, Math.floor((c.y - hy) * n) - 1);
    const y1 = Math.min(n, Math.ceil((c.y + hy) * n) + 1);
    setGrid((g) => (g.z === z && g.x0 === x0 && g.x1 === x1 && g.y0 === y0 && g.y1 === y1)
      ? g : { z, x0, x1, y0, y1 });
  }, [layer.maxZoom, w, h, worldPx]);

  /* THE LOOP OUTLIVES THE RENDER THAT STARTED IT, so it reads its callbacks
   * out of refs rather than closing over them. A loop started before a resize
   * and still running after it would otherwise keep projecting against the old
   * box, and one running across a layer change would keep asking the old
   * layer's maximum zoom what the tile zoom should be. */
  const paintRef = useRef(paint);
  const syncRef = useRef(syncGrid);
  const s2uRef = useRef(screenToUnit);
  const wpxRef = useRef(worldPx);
  useLayoutEffect(() => {
    paintRef.current = paint;
    syncRef.current = syncGrid;
    s2uRef.current = screenToUnit;
    wpxRef.current = worldPx;
  });

  /* The loop runs only while something is moving, and stops itself. */
  const wake = useCallback(() => {
    if (rafRef.current) return;
    const step = () => {
      const c = camRef.current;
      let busy = false;

      const dz = zoomTargetRef.current - c.zoom;
      if (Math.abs(dz) > 1e-4) {
        const a = anchorRef.current ?? sizeRef.current;
        const before = s2uRef.current(a.x, a.y);
        c.zoom += dz * ZOOM_EASE;
        const after = s2uRef.current(a.x, a.y);
        c.x += before.x - after.x;
        c.y += before.y - after.y;
        busy = true;
      } else if (c.zoom !== zoomTargetRef.current) {
        c.zoom = zoomTargetRef.current;
        busy = true;
      }

      const pt = panTargetRef.current;
      if (pt && !dragRef.current) {
        const dx = pt.x - c.x, dy = pt.y - c.y;
        if (Math.abs(dx) > 1e-6 || Math.abs(dy) > 1e-6) {
          c.x += dx * PAN_EASE;
          c.y += dy * PAN_EASE;
          busy = true;
          if (Math.abs(pt.x - c.x) < 1e-6 && Math.abs(pt.y - c.y) < 1e-6) {
            c.x = pt.x; c.y = pt.y; panTargetRef.current = null;
          }
        } else {
          c.x = pt.x; c.y = pt.y; panTargetRef.current = null;
        }
      }

      const v = velRef.current;
      if (!dragRef.current && (Math.abs(v.x) > GLIDE_FLOOR || Math.abs(v.y) > GLIDE_FLOOR)) {
        const S = wpxRef.current(c.zoom);
        c.x -= v.x / S;
        c.y -= v.y / S;
        v.x *= GLIDE; v.y *= GLIDE;
        busy = true;
      }

      clampCam(c);
      paintRef.current();
      syncRef.current();

      if (busy || dragRef.current) {
        rafRef.current = requestAnimationFrame(step);
      } else {
        rafRef.current = 0;
      }
    };
    rafRef.current = requestAnimationFrame(step);
  }, []);

  /* THE ID HAS TO BE CLEARED, NOT JUST CANCELLED. `wake()` starts with
   * `if (rafRef.current) return;`, so a cancelled frame whose id is still in
   * the ref means the loop can never be started again -- and in development
   * StrictMode runs this cleanup between its two mounts, which killed the loop
   * on the first render of every map. Dragging survived because it paints
   * directly; wheel zoom, the zoom buttons, FIT, follow and the glide all go
   * through the loop, and all of them were silently dead on the dev server. */
  /* AND THE LOOP IS WOKEN ON MOUNT, not only by a gesture. A camera target set
   * before this effect ran -- the initial fit to the route does exactly that --
   * is otherwise left sitting in the ref with nothing to animate it, which is
   * how the map came up showing the whole subcontinent with the sortie as a
   * smudge over Jodhpur. One frame; if there is nothing to move, it stops. */
  useEffect(() => {
    wake();
    return () => { cancelAnimationFrame(rafRef.current); rafRef.current = 0; };
  }, [wake]);
  /* Tiles are computed by the animation loop, and the loop only runs while
   * something is moving -- so the FIRST grid has to be asked for, and asked
   * for again whenever the box changes size or the layer changes its maximum
   * zoom. Without this the map came up empty until the first drag. */
  useEffect(() => { syncGrid(); }, [syncGrid]);
  /* The tiles for `grid.z` are on screen as of this commit, so the transform
   * may now be computed against it. Both in one effect, in this order. */
  useLayoutEffect(() => { zRef.current = grid.z; lastKRef.current = -1; paint(); });

  /* ---- fitting ---------------------------------------------------------- */
  const fit = useCallback((pts: { lat_deg: number; lon_deg: number }[], pad = 1.35) => {
    if (pts.length === 0 || w < 10) return;
    const xs = pts.map((q) => unitX(q.lon_deg));
    const ys = pts.map((q) => unitY(q.lat_deg));
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const y0 = Math.min(...ys), y1 = Math.max(...ys);
    const dx = Math.max(x1 - x0, 1e-5) * pad;
    const dy = Math.max(y1 - y0, 1e-5) * pad;
    const z = Math.min(Math.log2(w / (TILE * dx)), Math.log2(h / (TILE * dy)));
    panTargetRef.current = { x: (x0 + x1) / 2, y: (y0 + y1) / 2 };
    zoomTargetRef.current = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, z));
    anchorRef.current = null;
    velRef.current = { x: 0, y: 0 };
    wake();
  }, [w, h, wake]);

  /* Framed once when the route first exists and once when a flight first
   * arrives, and never again: after that the operator owns the camera. */
  useEffect(() => {
    const track = props.playback.samples;
    const key = track.length ? "flight" : props.routeLine.length > 1 ? "route" : "";
    if (!key || fitted.current === key || w < 10) return;
    fitted.current = key;
    fit(track.length ? track : props.routeLine);
  }, [props.routeLine, props.playback.samples, fit, w]);

  /* SELECTING A ROW IN THE PANEL BRINGS THE POINT INTO VIEW, and only when it
   * is not already in view -- a camera that recentres on every click takes the
   * map away from the operator, who may have framed it deliberately. Nothing
   * moves while a point is being dragged: the selection changed because the
   * drag started, and chasing it would fight the hand. */
  useEffect(() => {
    const id = props.selectedId;
    if (!id || w < 10 || dragRef.current) return;
    const q = props.points.find((x) => x.id === id);
    if (!q) return;
    const s = unitToScreen(unitX(q.lon_deg), unitY(q.lat_deg));
    const mx = Math.max(60, w * 0.12), my = Math.max(50, h * 0.14);
    if (s.x < mx || s.x > w - mx || s.y < my || s.y > h - my) {
      panTargetRef.current = { x: unitX(q.lon_deg), y: unitY(q.lat_deg) };
      velRef.current = { x: 0, y: 0 };
      wake();
    }
    // Deliberately only on the SELECTION changing: moving a point, or the plan
    // re-rendering for any other reason, must not move the camera.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.selectedId]);

  /* ---- wheel ------------------------------------------------------------ */
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      // A wheel over an instrument belongs to the instrument -- a scroll in the
      // layer list is a scroll, not a zoom.
      if ((e.target as HTMLElement | null)?.closest?.("[data-map-ui]")) return;
      /* The map is the hero of this page and the page itself does not scroll,
       * so an unmodified wheel over the map means zoom -- which is what an
       * operator expects and what TerrainMap could not offer, because there it
       * sat inside a column that did scroll. */
      e.preventDefault();
      const r = el.getBoundingClientRect();
      anchorRef.current = { x: e.clientX - r.left, y: e.clientY - r.top };
      panTargetRef.current = null;          // the hand always wins
      const px = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
      /* Proportional to the gesture, capped so one violent flick cannot cross
       * more than a level, and accumulated onto the TARGET rather than the
       * camera -- which is what makes a fast wheel feel like acceleration
       * instead of a stutter. */
      const step = Math.max(-1, Math.min(1, -px * 0.006));
      zoomTargetRef.current = Math.max(MIN_ZOOM,
        Math.min(MAX_ZOOM, zoomTargetRef.current + step));
      wake();
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [wake]);

  /* ---- pointer ---------------------------------------------------------- */
  const hitPoint = useCallback((px: number, py: number): PlanPoint | null => {
    for (let i = props.points.length - 1; i >= 0; i--) {
      const p = props.points[i];
      const s = unitToScreen(unitX(p.lon_deg), unitY(p.lat_deg));
      if (Math.hypot(s.x - px, s.y - py) < 15) return p;
    }
    return null;
  }, [props.points, unitToScreen]);

  /* Only the fields that are DRAWN as available fields are clickable as
   * fields. One that is already the departure is drawn as the departure, and
   * clicking it selects that point rather than offering to make it one. */
  const usedBaseIds = useMemo(
    () => new Set(props.points.map((q) => q.base_id).filter(Boolean) as string[]),
    [props.points]);

  /* Dropping a point is an edit AND a tool choice: the mission has to be
   * unlocked, and the page's active tool has to be one that adds. */
  const addOnClick = props.editable && (props.clickIntent ?? "add") === "add";

  const hitBase = useCallback((px: number, py: number): Airbase | null => {
    for (const b of AIRBASES) {
      if (usedBaseIds.has(b.id)) continue;
      const s = unitToScreen(unitX(b.lon_deg), unitY(b.lat_deg));
      if (Math.hypot(s.x - px, s.y - py) < 13) return b;
    }
    return null;
  }, [unitToScreen, usedBaseIds]);

  const onPointerDown = (e: React.PointerEvent) => {
    const r = boxRef.current!.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;
    setMenu(null);
    setLayerOpen(false);
    const hit = hitPoint(px, py);
    if (hit) {
      props.onSelect(hit.id);
      // Selecting is inspection and stays live; MOVING is an edit and does not.
      if (props.editable) movingRef.current = { id: hit.id };
    }
    dragRef.current = { px: e.clientX, py: e.clientY, moved: 0 };
    velRef.current = { x: 0, y: 0 };
    panTargetRef.current = null;
    /* CAPTURE ON THE BOX, NOT ON THE TILE UNDER THE CURSOR. Panning replaces
     * tile elements as the viewport crosses a boundary, and a capture held by
     * an element that is then unmounted is released -- which showed up as a
     * drag that stopped dead halfway across the map. */
    boxRef.current?.setPointerCapture?.(e.pointerId);
    if (boxRef.current) boxRef.current.style.cursor = hit ? "grabbing" : "grabbing";
    wake();
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const r = boxRef.current!.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;

    /* The coordinate readout is a DOM write, not state: it changes on every
     * mouse move and nothing else on the page depends on it. */
    if (coordRef.current) {
      const u = screenToUnit(px, py);
      const la = latOf(u.y), lo = lonOf(u.x);
      coordRef.current.style.opacity = "1";
      coordRef.current.textContent =
        Math.abs(la).toFixed(3) + "°" + (la >= 0 ? "N" : "S") + "  "
        + Math.abs(lo).toFixed(3) + "°" + (lo >= 0 ? "E" : "W")
        + "   z" + camRef.current.zoom.toFixed(1);
    }
    /* The cursor says what a click would do here: grab a point, open a field,
     * or drop a new waypoint. Written directly for the same reason as the
     * readout -- it changes on every move and nothing depends on it. */
    if (boxRef.current && !dragRef.current) {
      boxRef.current.style.cursor = hitPoint(px, py)
        ? (props.editable ? "grab" : "pointer")
        : props.editable && hitBase(px, py) ? "pointer"
        : addOnClick ? "crosshair" : "grab";
    }

    const d = dragRef.current;
    if (!d) return;
    const dx = e.clientX - d.px, dy = e.clientY - d.py;
    d.moved += Math.abs(dx) + Math.abs(dy);
    d.px = e.clientX; d.py = e.clientY;

    if (movingRef.current) {
      const u = screenToUnit(px, py);
      props.onMovePoint(movingRef.current.id, +latOf(u.y).toFixed(4), +lonOf(u.x).toFixed(4));
      return;
    }
    const c = camRef.current;
    const S = worldPx(c.zoom);
    c.x -= dx / S;
    c.y -= dy / S;
    clampCam(c);
    /* Velocity for the glide. Blended rather than taken raw so one stuttering
     * frame at the end of a drag does not throw the map across the country. */
    velRef.current.x = velRef.current.x * 0.6 + dx * 0.4;
    velRef.current.y = velRef.current.y * 0.6 + dy * 0.4;
    paint();
    syncGrid();
  };

  const onPointerUp = (e: React.PointerEvent) => {
    const d = dragRef.current;
    dragRef.current = null;
    const wasMoving = movingRef.current;
    movingRef.current = null;
    if (boxRef.current) boxRef.current.style.cursor = addOnClick ? "crosshair" : "grab";
    if (!d) return;

    if (d.moved < 4) {
      velRef.current = { x: 0, y: 0 };
      const r = boxRef.current!.getBoundingClientRect();
      const px = e.clientX - r.left, py = e.clientY - r.top;
      if (!props.editable) {
        if (props.selectBases) {
          const base = hitBase(px, py);
          if (base) setMenu({ base, x: px, y: py });
        }
        return;                                   // locked: no route edits
      }
      const base = hitBase(px, py);
      if (base) { setMenu({ base, x: px, y: py }); return; }
      if (wasMoving) return;                     // a click on a waypoint selects it
      if (hitPoint(px, py)) return;
      // The SELECT tool: a click on open ground pans and deselects, and the
      // route is left exactly as it was.
      if (!addOnClick) { props.onSelect(null); props.onSelectLeg?.(null); return; }
      const u = screenToUnit(px, py);
      props.onAddPoint(+latOf(u.y).toFixed(4), +lonOf(u.x).toFixed(4));
      return;
    }
    wake();
  };

  /* ---- tiles ------------------------------------------------------------ */
  const pickLayer = useCallback((l: TileLayer) => {
    tally.current = { id: l.id, ok: 0, bad: 0 };
    setRetry({}); setHandover(""); setLayer(l); setLayerOpen(false);
  }, []);

  const failLayer = useCallback((failed: TileLayer) => {
    const next = LAYERS.find((l) => l.id !== failed.id && health[l.id] !== "down");
    if (!next) return;
    tally.current = { id: next.id, ok: 0, bad: 0 };
    setRetry({}); setLayer(next);
    setHandover(failed.label + " is not serving tiles — showing " + next.label);
  }, [health]);

  const onTile = useCallback((ok: boolean, l: TileLayer) => {
    if (tally.current.id !== l.id) return;
    if (ok) tally.current.ok += 1; else tally.current.bad += 1;
    const { ok: g, bad } = tally.current;
    const state: Health = bad === 0 ? (g > 0 ? "ok" : "unknown")
      : g === 0 && bad >= 4 ? "down" : "degraded";
    setHealth((prev) => (prev[l.id] === state ? prev : { ...prev, [l.id]: state }));
    if (state === "down") failLayer(l);
  }, [failLayer]);

  const tiles = useMemo(() => {
    const { z, x0, x1, y0, y1 } = grid;
    const n = Math.pow(2, z);
    const subs = layer.subdomains ?? [""];
    const out: { key: string; url: string; left: number; top: number; tries: number }[] = [];
    for (let ty = y0; ty < y1; ty++) {
      for (let tx = x0; tx < x1; tx++) {
        const wrapped = ((tx % n) + n) % n;
        const key = layer.id + "/" + z + "/" + tx + "/" + ty;
        const tries = retry[key] ?? 0;
        out.push({
          key, tries,
          url: layer.url
            .replace("{s}", subs[(Math.abs(tx + ty) + tries) % subs.length])
            .replace("{z}", String(z))
            .replace("{x}", String(wrapped))
            .replace("{y}", String(ty)),
          left: tx * TILE, top: ty * TILE,
        });
      }
    }
    return out;
  }, [grid, layer, retry]);

  /* ---- overlay geometry, in world pixels at grid.z ---------------------- */
  const P = useCallback((lat: number, lon: number) => {
    const Wz = worldPx(grid.z);
    return { x: unitX(lon) * Wz, y: unitY(lat) * Wz };
  }, [grid.z, worldPx]);

  const kmPerWorldPx = useMemo(() => {
    const Wz = worldPx(grid.z);
    return (40075.016686 * Math.cos(latOf(camRef.current.y) * Math.PI / 180)) / Wz;
  }, [grid, worldPx]);   // grid, so the figure follows the camera latitude

  const routeD = useMemo(() => {
    const r = props.routeLine;
    if (r.length < 2) return "";
    return r.map((q, i) => {
      const s = P(q.lat_deg, q.lon_deg);
      return (i ? "L" : "M") + s.x.toFixed(1) + " " + s.y.toFixed(1);
    }).join(" ");
  }, [props.routeLine, P]);

  /* ONE PATH PER LEG, so a leg can be picked and highlighted. Only built when
   * the page has asked for leg picking. */
  const legD = useMemo(() => {
    if (!props.onSelectLeg) return [];
    const r = props.routeLine;
    const out: string[] = [];
    for (let i = 1; i < r.length; i++) {
      const a = P(r[i - 1].lat_deg, r[i - 1].lon_deg);
      const b = P(r[i].lat_deg, r[i].lon_deg);
      out.push("M" + a.x.toFixed(1) + " " + a.y.toFixed(1)
               + "L" + b.x.toFixed(1) + " " + b.y.toFixed(1));
    }
    return out;
  }, [props.routeLine, props.onSelectLeg, P]);

  const trackD = useMemo(() => {
    const s = props.playback.samples;
    if (s.length < 2) return "";
    return s.map((q, i) => {
      const t = P(q.lat_deg, q.lon_deg);
      return (i ? "L" : "M") + t.x.toFixed(1) + " " + t.y.toFixed(1);
    }).join(" ");
  }, [props.playback.samples, P]);

  const patrolGeom = useMemo(() => props.patrols.map((pa) => {
    const home = props.points.find((q) => q.id === pa.point_id);
    const centre = home ? P(home.lat_deg, home.lon_deg) : { x: 0, y: 0 };
    const ring = pa.ring.map((q) => {
      const s = P(q.lat_deg, q.lon_deg);
      return s.x.toFixed(1) + "," + s.y.toFixed(1);
    }).join(" ");
    const r = home
      ? Math.hypot(P(pa.ring[0].lat_deg, pa.ring[0].lon_deg).x - centre.x,
                   P(pa.ring[0].lat_deg, pa.ring[0].lon_deg).y - centre.y)
      : 0;
    return { id: pa.point_id, centre, ring, r, laps: pa.laps };
  }), [props.patrols, props.points, P]);

  /* ---- the aircraft, moved by subscription rather than by props ---------- */
  const paintFlight = useCallback((t: number) => {
    const pb = props.playback;
    const g = aircraftRef.current;
    const cased = flownCaseRef.current;
    const line = flownLineRef.current;
    if (!pb.samples.length) {
      if (g) g.style.display = "none";
      return;
    }
    const at = pb.interpolate(t);
    if (g && at) {
      const s = P(at.lat, at.lon);
      const i = at.i;
      const a = pb.samples[Math.max(0, i - 1)];
      const b = pb.samples[Math.min(pb.samples.length - 1, i + 1)];
      const dx = (b.lon_deg - a.lon_deg) *
                 Math.cos(((a.lat_deg + b.lat_deg) / 2) * Math.PI / 180);
      const dy = b.lat_deg - a.lat_deg;
      const hdg = (dx || dy) ? (Math.atan2(dx, dy) * 180) / Math.PI : 0;
      g.style.display = "";
      g.setAttribute("transform",
        "translate(" + s.x.toFixed(1) + "," + s.y.toFixed(1) + ") rotate(" + hdg.toFixed(1) + ")");
    }
    /* ONE ATTRIBUTE PER FRAME REVEALS THE TRACK. The path is normalised to
     * pathLength 1 and dashed "1 1", so the offset IS the fraction flown --
     * measured along the ground rather than by sample number, because the
     * samples are spaced in time and would run ahead of the aircraft through
     * the cruise. */
    const off = String(1 - pb.revealed(t));
    if (cased) cased.setAttribute("stroke-dashoffset", off);
    if (line) line.setAttribute("stroke-dashoffset", off);
  }, [props.playback, P]);

  useEffect(() => props.playback.subscribe((t) => paintFlight(t)),
            [props.playback, paintFlight]);
  useLayoutEffect(() => { paintFlight(props.playback.t); });

  /* ---- radar rings ------------------------------------------------------ */
  const ringKm = [5, 10, 25, 50, 100, 200, 500, 1000]
    .find((k) => k / kmPerWorldPx > h / 9) ?? 1000;
  const station = props.points.find((p) => p.kind === "DEPARTURE") ?? props.points[0];
  const alternate = props.alternateId
    ? AIRBASES.find((b) => b.id === props.alternateId) ?? null : null;

  const dot = (s: Health) =>
    s === "ok" ? "var(--state-normal)" : s === "degraded" ? "var(--alert-caut)"
    : s === "down" ? "var(--alert-warn)" : "var(--ink-mute)";

  return (
    <div
      ref={boxRef}
      className="ms-map"
      style={{
        position: "relative", width: "100%", height: props.height,
        minHeight: 0, overflow: "hidden", background: "#070b11",
        border: props.fullBleed ? "none" : "1px solid var(--line)",
        borderRadius: props.fullBleed ? 0 : "var(--radius)",
        userSelect: "none", touchAction: "none",
        cursor: addOnClick ? "crosshair" : "grab",
      }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onDoubleClick={(e) => {
        const r = boxRef.current!.getBoundingClientRect();
        anchorRef.current = { x: e.clientX - r.left, y: e.clientY - r.top };
        zoomTargetRef.current = Math.min(MAX_ZOOM, zoomTargetRef.current + 1);
        wake();
      }}
      onPointerLeave={() => {
        if (coordRef.current) {
          coordRef.current.textContent = "";
          coordRef.current.style.opacity = "0";
        }
      }}
    >
      {/* Everything that lives in world coordinates, moved by ONE transform. */}
      <div ref={stageRef}
           style={{ position: "absolute", left: 0, top: 0, width: 0, height: 0,
                    transformOrigin: "0 0", willChange: "transform" }}>
        {tiles.map((t) => (
          <img key={t.key + "#" + t.tries} src={t.url} alt=""
               draggable={false} decoding="async" referrerPolicy="no-referrer"
               onLoad={() => onTile(true, layer)}
               onError={() => {
                 if (t.tries < TILE_RETRIES) {
                   setRetry((r) => ({ ...r, [t.key]: (r[t.key] ?? 0) + 1 }));
                 } else onTile(false, layer);
               }}
               style={{ position: "absolute", left: t.left, top: t.top,
                        width: TILE, height: TILE,
                        /* A hair of overlap: at fractional scales adjacent
                           tiles otherwise leave a one-pixel seam. */
                        outline: "0.5px solid transparent",
                        imageRendering: "auto" }} />
        ))}

        <svg style={{ position: "absolute", left: 0, top: 0, width: 1, height: 1,
                      overflow: "visible", pointerEvents: "none" }}>
          <defs>
            <filter id="ms-glow" x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur stdDeviation="2.5" result="b" />
              <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
            <marker id="ms-arrow" viewBox="0 0 10 10" refX="6" refY="5"
                    markerWidth="5" markerHeight="5" orient="auto-start-reverse"
                    markerUnits="strokeWidth">
              <path d="M0,1 L9,5 L0,9 z" fill="var(--alert-advis)" opacity="0.85" />
            </marker>
          </defs>

          {/* A DARK WASH so the console's own colours stay the brightest thing
              on the screen. Satellite imagery at noon is brighter than every
              alert colour in the palette, which inverts the whole hierarchy. */}
          <rect x={0} y={0} width={worldPx(grid.z)} height={worldPx(grid.z)}
                fill="#060a10" opacity={0.3} />

          {/* Reach: what an as-new engine could cover, and what this one can. */}
          {station && props.envNewKm ? (
            <circle cx={P(station.lat_deg, station.lon_deg).x}
                    cy={P(station.lat_deg, station.lon_deg).y}
                    r={props.envNewKm / kmPerWorldPx} fill="none" stroke="#dbe6f2"
                    strokeWidth={1.4} strokeDasharray="2 8" opacity={0.6}
                    vectorEffect="non-scaling-stroke" />
          ) : null}
          {station && props.envKm ? (
            <circle cx={P(station.lat_deg, station.lon_deg).x}
                    cy={P(station.lat_deg, station.lon_deg).y}
                    r={props.envKm / kmPerWorldPx} fill="var(--alert-caut)"
                    fillOpacity={0.04} stroke="var(--alert-caut)"
                    strokeWidth={1.8} strokeDasharray="9 6" opacity={0.75}
                    vectorEffect="non-scaling-stroke" />
          ) : null}

          {/* Range and bearing from the field the aircraft has to get back to. */}
          {radar && station && (
            <g opacity={0.75}>
              {[1, 2, 3, 4].map((i) => (
                <circle key={i} cx={P(station.lat_deg, station.lon_deg).x}
                        cy={P(station.lat_deg, station.lon_deg).y}
                        r={(ringKm * i) / kmPerWorldPx} fill="none"
                        stroke="var(--alert-advis)" strokeWidth={1}
                        strokeDasharray="3 7" opacity={0.5}
                        vectorEffect="non-scaling-stroke" />
              ))}
            </g>
          )}

          {/* PATROL AREAS. The soft disc is the area; the polygon inside it is
              the circuit that will actually be flown, lap for lap. */}
          {patrolGeom.map((pa) => (
            <g key={pa.id}>
              <circle cx={pa.centre.x} cy={pa.centre.y} r={pa.r * 1.06}
                      fill="var(--alert-caut)" fillOpacity={0.09}
                      stroke="var(--alert-caut)" strokeWidth={1.4}
                      strokeDasharray="7 6" opacity={0.85}
                      vectorEffect="non-scaling-stroke"
                      className={props.selectedId === pa.id ? "ms-pulse" : undefined} />
              <polygon points={pa.ring} fill="none" stroke="var(--alert-caut)"
                       strokeWidth={1.6} opacity={0.9} strokeLinejoin="round"
                       vectorEffect="non-scaling-stroke" />
            </g>
          ))}

          {/* THE PLANNED ROUTE. Cased in black first so it reads over imagery
              of any brightness, then the line, then the direction of travel. */}
          {routeD && (
            <>
              <path d={routeD} fill="none" stroke="#000" strokeWidth={6}
                    opacity={0.5} strokeLinejoin="round" strokeLinecap="round"
                    vectorEffect="non-scaling-stroke" />
              <path d={routeD} fill="none" stroke="var(--alert-advis)"
                    strokeWidth={2.4} strokeLinejoin="round" strokeLinecap="round"
                    opacity={props.stage === "PLAN" ? 1 : 0.42}
                    strokeDasharray={props.stage === "PLAN" ? undefined : "8 6"}
                    markerMid="url(#ms-arrow)"
                    vectorEffect="non-scaling-stroke" />
            </>
          )}

          {/* THE LEGS, AS OBJECTS. A wide transparent stroke per leg catches
              the click; the selected one is drawn back over the route in the
              selection colour. Rendered after the route and before the
              waypoints, so a click near a point still gets the point. */}
          {legD.map((d, i) => (
            <g key={"leg" + i}>
              <path d={d} fill="none" stroke="transparent" strokeWidth={16}
                    strokeLinecap="round" vectorEffect="non-scaling-stroke"
                    style={{ pointerEvents: "stroke", cursor: "pointer" }}
                    onClick={(ev) => {
                      ev.stopPropagation();
                      props.onSelectLeg?.(props.selectedLeg === i ? null : i);
                    }} />
              {props.selectedLeg === i && (
                <path d={d} fill="none" stroke="var(--ref-selected)"
                      strokeWidth={4} strokeLinecap="round"
                      vectorEffect="non-scaling-stroke"
                      style={{ pointerEvents: "none" }} />
              )}
            </g>
          ))}

          {/* THE TRACK ACTUALLY FLOWN, revealed by arc length as time runs. */}
          {trackD && (
            <>
              <path d={trackD} fill="none" stroke="#cbd8e6" strokeWidth={1.2}
                    opacity={0.22} strokeLinejoin="round"
                    vectorEffect="non-scaling-stroke" />
              <path ref={flownCaseRef} d={trackD} fill="none" stroke="#000"
                    strokeWidth={6} opacity={0.45} pathLength={1}
                    strokeDasharray="1 1" strokeDashoffset={1}
                    strokeLinejoin="round" strokeLinecap="round"
                    vectorEffect="non-scaling-stroke" />
              <path ref={flownLineRef} d={trackD} fill="none"
                    stroke="var(--state-normal)"
                    strokeWidth={2.8} pathLength={1}
                    strokeDasharray="1 1" strokeDashoffset={1}
                    strokeLinejoin="round" strokeLinecap="round"
                    filter="url(#ms-glow)" vectorEffect="non-scaling-stroke" />
            </>
          )}

          {/* Where a limit was crossed, on the ground it was crossed over. */}
          {props.events?.map((e, i) => {
            const s = P(e.lat_deg, e.lon_deg);
            const col = e.severity === "WARNING" ? "var(--alert-warn)"
              : e.severity === "CAUTION" ? "var(--alert-caut)" : "var(--alert-advis)";
            return (
              <g key={i} transform={"translate(" + s.x + "," + s.y + ")"}
                 style={{ pointerEvents: props.onSeek ? "auto" : "none",
                          cursor: props.onSeek ? "pointer" : "default" }}
                 onClick={() => e.t_s != null && props.onSeek?.(e.t_s)}>
                <g data-fixed transform="scale(1)">
                  <circle r={7} fill="none" stroke={col} strokeWidth={2.2} />
                  <circle r={2} fill={col} />
                  <title>{e.message ?? e.code ?? ""}</title>
                </g>
              </g>
            );
          })}

          {/* AIRBASES that are not in the plan: available, and quiet about it. */}
          {AIRBASES.filter((b) => !usedBaseIds.has(b.id) && b.id !== props.alternateId)
            .map((b) => {
              const s = P(b.lat_deg, b.lon_deg);
              return (
                <g key={b.id} transform={"translate(" + s.x + "," + s.y + ")"}
                   style={{ pointerEvents: "none" }}>
                  <g data-fixed transform="scale(1)" className="ms-base-idle">
                    <circle r={5.5} fill="#0b1018" stroke="#8ea3ba"
                            strokeWidth={1.6} opacity={0.9} />
                    <circle r={1.6} fill="#8ea3ba" />
                    <text x={10} y={4} fontSize={12} fill="#c2d1e2" opacity={0.9}
                          style={{ paintOrder: "stroke", stroke: "#000a",
                                   strokeWidth: 3 }}>{b.short}</text>
                  </g>
                </g>
              );
            })}

          {alternate && (() => {
            const s = P(alternate.lat_deg, alternate.lon_deg);
            return (
              <g transform={"translate(" + s.x + "," + s.y + ")"}
                 style={{ pointerEvents: "none" }}>
                <g data-fixed transform="scale(1)">
                  <circle r={8} fill="none" stroke="var(--ref-selected)"
                          strokeWidth={1.6} strokeDasharray="3 3" />
                  <circle r={4} fill="#0b1018" stroke="var(--ref-selected)"
                          strokeWidth={2} />
                  <text x={13} y={4} fontSize={12} fill="var(--ref-selected-ink)"
                        style={{ paintOrder: "stroke", stroke: "#000b", strokeWidth: 3 }}>
                    {alternate.short} · ALT
                  </text>
                </g>
              </g>
            );
          })()}

          {/* THE PLAN'S OWN POINTS. Numbered, because a route is an order. */}
          {props.points.map((p, i) => {
            const s = P(p.lat_deg, p.lon_deg);
            const on = props.selectedId === p.id;
            const isBase = p.kind === "DEPARTURE" || p.kind === "RECOVERY";
            const col = isBase ? "var(--state-normal)"
              : p.kind === "PATROL" ? "var(--alert-caut)" : "var(--alert-advis)";
            return (
              <g key={p.id} transform={"translate(" + s.x + "," + s.y + ")"}
                 style={{ pointerEvents: "none" }}>
                <g data-fixed transform="scale(1)"
                   className={on ? "ms-sel" : undefined}>
                  {on && <circle r={15} fill="none" stroke={col} strokeWidth={1.4}
                                 opacity={0.7} className="ms-halo" />}
                  {isBase ? (
                    <>
                      <circle r={9} fill="#08121a" stroke={col} strokeWidth={2.4} />
                      <path d="M-4.2,0 L4.2,0 M0,-4.2 L0,4.2" stroke={col}
                            strokeWidth={2} strokeLinecap="round" />
                    </>
                  ) : p.kind === "PATROL" ? (
                    <path d="M0,-8 L8,0 L0,8 L-8,0 Z" fill="#08121a" stroke={col}
                          strokeWidth={2.2} strokeLinejoin="round" />
                  ) : (
                    <circle r={6.5} fill="#08121a" stroke={col} strokeWidth={2.4} />
                  )}
                  <text x={14} y={-4} fontSize={13} fontWeight={700} fill="#eef4fb"
                        style={{ paintOrder: "stroke", stroke: "#000c", strokeWidth: 3.5 }}>
                    {i + 1}. {p.name}
                  </text>
                  <text x={14} y={10} fontSize={12} fill="#a9bbcf"
                        style={{ paintOrder: "stroke", stroke: "#000c", strokeWidth: 3 }}>
                    {Math.round(p.altitude_ft).toLocaleString()} ft
                    {p.kind === "PATROL" && p.loiter_min ? " · " + p.loiter_min + " min" : ""}
                  </text>
                </g>
              </g>
            );
          })}

          {/* THE AIRCRAFT. Pointed the way it is going -- a symbol without
              heading is a dot, and a dot on a track says nothing the track
              does not already say. */}
          <g ref={aircraftRef} style={{ display: "none", pointerEvents: "none" }}>
            <g data-fixed transform="scale(1)">
              <circle r={13} fill="var(--state-normal)" opacity={0.12}
                      className="ms-ping" />
              <path d="M0,-12 L7.5,8 L0,4 L-7.5,8 Z" fill="var(--state-normal)"
                    stroke="#04222b" strokeWidth={1.3} strokeLinejoin="round" />
            </g>
          </g>

          </svg>
      </div>

      {/* ---- THE INSTRUMENT LAYER -------------------------------------------
       * Everything that is not the map itself lives in here, and this is the
       * one place that decides pointer routing. `pointerEvents: none` on the
       * layer lets a press pass through its empty parts to the map; each
       * control turns them back on for itself.
       *
       * THE DEFECT THIS FIXES. The box takes a POINTER CAPTURE on pointerdown
       * so that a drag survives the tiles being unmounted underneath it. A
       * capture held by an ANCESTOR retargets the pointerup, so `click` was
       * dispatched to the box rather than to the button that had been pressed
       * -- and the box, seeing a pointer that had not moved, dropped a
       * waypoint. Pressing "Terrain" added a point instead of opening the
       * layer list, which is where the unasked-for waypoints came from.
       * Stopping the gesture here means the box never captures one that began
       * on an instrument.                                                    */}
      <div data-map-ui
           style={{ position: "absolute", inset: 0, pointerEvents: "none",
                    zIndex: 3 }}
           onPointerDown={(e) => e.stopPropagation()}
           onPointerUp={(e) => e.stopPropagation()}
           onDoubleClick={(e) => e.stopPropagation()}>

      {/* ---- floating controls, which never cover the route ---------------- */}
      <div data-map-tools
           style={{ position: "absolute", left: 10, top: 10, display: "flex",
                    flexDirection: "column", gap: 6, pointerEvents: "auto" }}>
        <div style={chipCol}>
          <button style={iconBtn} aria-label="zoom in" title="zoom in"
                  onClick={() => { anchorRef.current = null;
                                   zoomTargetRef.current = Math.min(MAX_ZOOM, zoomTargetRef.current + 1);
                                   wake(); }}>+</button>
          <div style={{ height: 1, background: "var(--line)" }} />
          <button style={iconBtn} aria-label="zoom out" title="zoom out"
                  onClick={() => { anchorRef.current = null;
                                   zoomTargetRef.current = Math.max(MIN_ZOOM, zoomTargetRef.current - 1);
                                   wake(); }}>−</button>
        </div>
        <button style={{ ...iconBtn, ...chipCol, width: 34, height: 34 }}
                title="frame the whole sortie" aria-label="fit route"
                onClick={() => fit(props.playback.samples.length
                  ? props.playback.samples : props.routeLine)}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M3 8V3h5M16 3h5v5M21 16v5h-5M8 21H3v-5" />
          </svg>
        </button>
        <button style={{ ...iconBtn, ...chipCol, width: 34, height: 34,
                         color: radar ? "var(--alert-advis)" : "var(--ink-dim)" }}
                title="range rings from the departure field"
                aria-label="range rings"
                onClick={() => setRadar((r) => !r)}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="3" /><circle cx="12" cy="12" r="8" opacity="0.6" />
          </svg>
        </button>
      </div>

      {/* Layer picker: one chip, a list when asked, and a health dot so the
          state of the tile service is visible before anything is clicked. */}
      <div data-map-tools
           style={{ position: "absolute", left: 10, top: 156, textAlign: "left",
                    pointerEvents: "auto" }}>
        <button style={{ ...chip, display: "inline-flex", alignItems: "center", gap: 8 }}
                onClick={() => setLayerOpen((o) => !o)}>
          <span style={{ width: 8, height: 8, borderRadius: 4,
                         background: dot(health[layer.id] ?? "unknown") }} />
          {layer.label}
          <span style={{ opacity: 0.6 }}>▾</span>
        </button>
        {layerOpen && (
          <div style={{ ...chipCol, marginTop: 6, overflow: "hidden", minWidth: 190 }}
               className="ms-pop">
            {LAYERS.map((l) => (
              <button key={l.id} onClick={() => pickLayer(l)}
                      style={{ ...menuItem,
                               color: l.id === layer.id ? "var(--alert-advis)" : "var(--ink)" }}>
                <span style={{ width: 8, height: 8, borderRadius: 4, flex: "0 0 auto",
                               background: dot(health[l.id] ?? "unknown") }} />
                {l.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* The state of the mission, the verdict and every other thing that is
          about the SORTIE rather than about the chart are the page's, and are
          passed in through `overlays`. What is left here is what a map has:
          its tools, its scale, where the cursor is, and what the tiles are
          doing. */}

      {/* What clicking a field can do. Opens where it was clicked. */}
      {menu && (
        <div className="ms-pop"
             style={{ position: "absolute", left: Math.min(menu.x + 10, w - 210),
                      top: Math.min(menu.y + 10, h - 150), width: 196, zIndex: 5,
                      pointerEvents: "auto", ...chipCol }}>
          <div style={{ padding: "8px 10px", borderBottom: "1px solid var(--line)" }}>
            <div style={{ fontWeight: 700, fontSize: 16 }}>{menu.base.name}</div>
            <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                          fontFamily: "var(--font-num)" }}>
              {menu.base.id} · {menu.base.elevation_ft.toLocaleString()} ft
            </div>
          </div>
          {(props.baseActions ?? (["DEPARTURE", "RECOVERY", "ALTERNATE"] as BaseRole[])).map((role) => (
            <button key={role} style={menuItem}
                    onClick={() => { props.onBaseAction(menu.base, role); setMenu(null); }}>
              SET {role}
            </button>
          ))}
        </div>
      )}

      {/* Scale, coordinates and attribution -- the furniture a chart needs. */}
      <div style={{ position: "absolute", left: 10, bottom: 8 + (props.padBottom ?? 0),
                    display: "flex", alignItems: "center", gap: 10,
                    pointerEvents: "none" }}>
        <div style={{ ...chip, display: "flex", alignItems: "center", gap: 7 }}>
          <span ref={barRef} style={{ display: "inline-block", height: 7, width: 60,
                                      borderLeft: "2px solid currentColor",
                                      borderRight: "2px solid currentColor",
                                      borderBottom: "2px solid currentColor" }} />
          <span ref={barTextRef} style={{ fontFamily: "var(--font-num)" }} />
        </div>
        <div style={{ ...chip, display: "flex", alignItems: "center", gap: 5 }}
             title="the map is north-up and does not rotate">
          <span style={{ fontSize: "var(--size-label)", lineHeight: 1 }}>▲</span>N
        </div>
        {/* Empty until the cursor is over the map, and invisible while it is
            empty -- a dark bar with nothing in it reads as a broken control. */}
        <div ref={coordRef} style={{ ...chip, fontFamily: "var(--font-num)",
                                     minWidth: 220, opacity: 0,
                                     transition: "opacity 120ms ease" }} />
      </div>

      <div style={{ position: "absolute", right: 8, bottom: 6 + (props.padBottom ?? 0),
                    fontSize: "var(--size-label)",
                    color: "var(--ink-dim)", background: chipBg, padding: "2px 7px",
                    borderRadius: 2, pointerEvents: "none" }}>
        {layer.attribution}
      </div>

      {/* Said once, about the layer it applies to, and cleared by switching. */}
      {handover && <div style={notice}>{handover}</div>}
      {!handover && health[layer.id] === "degraded" && (
        <div style={notice}>
          {layer.label}: some tiles are not arriving. The route, the reach rings
          and the terrain check are computed here and are unaffected.
        </div>
      )}
      {!handover && LAYERS.every((l) => health[l.id] === "down") && (
        <div style={notice}>
          No map imagery — this station has no route to any tile service. The
          route, the reach rings, the terrain check and the flight simulation
          all still work: those are computed here, not fetched.
        </div>
      )}

      {props.anchor && (
        <div ref={pinRef} className="ms-anchor"
             data-lat={props.anchor.lat} data-lon={props.anchor.lon}
             style={{ position: "absolute", left: 0, top: 0, width: 0, height: 0,
                      pointerEvents: "none" }}>
          {props.anchor.children}
        </div>
      )}

      {/* THE PAGE'S OWN INSTRUMENTS, inside the map's positioning context and
          under the same pointer routing -- so a planner or a dock floating on
          the canvas cannot drop a waypoint either. */}
      {props.overlays}
      </div>
    </div>
  );
}

/* The camera cannot leave the world, and mercator has no poles. */
function clampCam(c: Cam) {
  c.zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, c.zoom));
  c.x = ((c.x % 1) + 1) % 1;
  c.y = Math.max(0.02, Math.min(0.98, c.y));
}

/* THE FURNITURE IS PART OF THE CONSOLE, NOT PART OF THE IMAGERY.
 * These were a hardcoded near-black -- which is right over a night map and
 * invisible over a day one: on the DAY ambient the zoom buttons were dark ink
 * on a dark chip on a pale chart, four grey squares with nothing readable in
 * them. They are drawn from the panel token now, mixed with a little of the
 * map behind them, so they read in both ambients and pick up a theme change
 * without anything here knowing about it. */
const chipBg = "var(--bg-panel)";

const chip: React.CSSProperties = {
  background: chipBg, border: "1px solid var(--line)",
  borderRadius: "var(--radius)", color: "var(--ink)", fontSize: "var(--size-label)",
  padding: "5px 10px", fontFamily: "var(--font-ui)", cursor: "pointer",
};

const chipCol: React.CSSProperties = {
  background: chipBg, border: "1px solid var(--line)",
  borderRadius: "var(--radius)", display: "flex", flexDirection: "column",
};

const iconBtn: React.CSSProperties = {
  width: 34, height: 32, display: "flex", alignItems: "center",
  justifyContent: "center", background: "transparent", border: "none",
  color: "var(--ink)", fontSize: 18, lineHeight: 1, cursor: "pointer",
  fontFamily: "var(--font-ui)",
};

const menuItem: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 9, width: "100%",
  padding: "9px 11px", background: "transparent", border: "none",
  borderTop: "1px solid transparent", color: "var(--ink)", textAlign: "left",
  fontSize: "var(--size-label)", letterSpacing: "0.05em", cursor: "pointer",
  fontFamily: "var(--font-ui)",
};

const notice: React.CSSProperties = {
  position: "absolute", left: 56, top: 52, maxWidth: 360,
  fontSize: "var(--size-label)", color: "var(--alert-caut)",
  background: chipBg, padding: "7px 11px", borderRadius: "var(--radius)",
  lineHeight: 1.45, border: "1px solid var(--line)", pointerEvents: "none",
};
