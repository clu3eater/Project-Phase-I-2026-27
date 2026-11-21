/* A real slippy map: global tiles, selectable layers, and the flight on top.
 *
 * WHAT THIS REPLACED, TWICE
 * -------------------------
 * First a coordinate graticule with a magenta line across it, which was not a
 * map at all -- no ground under the route, so a leg planned at 12,000 ft over
 * terrain standing at 19,900 looked exactly like a leg over the sea. Then a
 * shipped raster of one region, which was real but covered India only.
 *
 * This is the whole world, from the same kind of tile service every chart
 * application uses, with the layers a planner actually switches between.
 *
 * WHAT A TILE SERVICE DOES WHEN IT IS HAVING A BAD DAY
 * ---------------------------------------------------
 * It does not go down. It rate-limits one host, or serves nine tiles out of
 * ten, or times out for thirty seconds and then recovers. The first version of
 * this treated every one of those as "no route to the tile service", latched
 * that message on for the rest of the session, and -- because the flag was one
 * boolean shared by all five layers -- kept showing it after switching to a
 * layer that was working perfectly. Switching TO a broken layer from a working
 * one showed nothing at all, because the flag had already latched true.
 *
 * So tile health is now per-layer and per-tile: a tile that fails is retried
 * on a different host, a layer that keeps failing is reported as degraded
 * rather than absent, and a layer that fails outright hands over to one that
 * works and SAYS which and why. The layer menu carries a dot per layer so the
 * state is visible before anything is clicked.
 *
 * ONLINE, WITH AN HONEST OFFLINE STORY
 * ------------------------------------
 * A ground station that is air-gapped will show no tiles, and the map says so
 * rather than drawing an empty rectangle -- and the route, the waypoints, the
 * reach rings, the terrain clearance and the whole flight simulation still
 * work, because those are computed from data the station holds, not from the
 * picture.
 *
 * Every layer here is free to use with attribution, which is displayed. None
 * of them needs a key, because a key is a thing that expires in a drawer three
 * months before a demonstration.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FlightSample, RouteWaypoint } from "../lib/api";
import { latOfMercY, mercY } from "../lib/geo";

export interface TileLayer {
  id: string; label: string; url: string; attribution: string;
  maxZoom: number;
  /* Hosts the {s} placeholder rotates through. A failed tile is retried on the
   * NEXT one, which is what makes a single rate-limited host survivable. */
  subdomains?: string[];
}

/* THE LAYER MENU: ONLY SERVICES THAT ANSWER A CONSOLE LIKE THIS ONE.
 *
 * Two layers came out on 23 Sep 2026, both volunteer-run and both refusing
 * this console by policy rather than failing by accident:
 *
 *   Street (tile.openstreetmap.org) answered every tile with a picture of the
 *   words "Access blocked" and HTTP 403. The OSM Foundation's tile policy
 *   requires a Referer and says "do not send no-referrer" -- and this map
 *   sends no referrer on purpose, because a ground station does not announce
 *   its address to third-party servers. The 403 image LOADS as an image, so
 *   the per-tile health check scored the layer healthy while it showed an
 *   error notice across the whole route.
 *   Topographic (OpenTopoMap) asks for low volume and rate-limits with 403s
 *   when a slippy map asks for twenty tiles per pan.
 *
 * What remains is Esri's basemap tile services -- free to use with the
 * attribution shown, served from a CDN built for volume, and indifferent to
 * the referrer, the night layer included. Esri's World Street Map replaces
 * the street layer. */
export const LAYERS: TileLayer[] = [
  { id: "terrain", label: "Terrain", maxZoom: 19,
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
    attribution: "Esri, HERE, Garmin, USGS, NGA, and the GIS User Community" },
  { id: "sat", label: "Satellite", maxZoom: 19,
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "Esri, Maxar, Earthstar Geographics, and the GIS User Community" },
  { id: "street", label: "Street", maxZoom: 19,
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    attribution: "Esri, HERE, Garmin, USGS, and the GIS User Community" },
  { id: "relief", label: "Shaded relief", maxZoom: 13,
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Shaded_Relief/MapServer/tile/{z}/{y}/{x}",
    attribution: "Esri World Shaded Relief" },
  /* Esri's World Dark Gray Canvas. CARTO's dark basemap, here until 24 Sep
   * 2026, began answering every tile with the words "API KEY REQUIRED" -- an
   * image, so it loaded and the per-tile health check scored it healthy. */
  { id: "plain", label: "Plain (night)", maxZoom: 16,
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    attribution: "Esri, HERE, Garmin, © OpenStreetMap contributors, and the GIS User Community" },
];

/* THE LAYER THE MAP OPENS ON: Esri's World Topo, a contoured, relief-shaded
 * chart -- the closest thing here to what a route is planned against -- from
 * a service built for volume. */
const DEFAULT_LAYER_ID = "terrain";

const TILE = 256;
const MIN_ZOOM = 2;
const MAX_ZOOM = 18;
/* How many times a single tile is retried, each time on the next host, before
 * it is counted against the layer. Two is enough for a rate-limit blip and few
 * enough that a genuinely dead layer is reported within a couple of seconds. */
const TILE_RETRIES = 2;
// Loaded tiles remembered for drawing beneath a level still arriving.
const LOADED_KEEP = 300;

export interface View { lat: number; lon: number; zoom: number; }

function project(view: View, w: number, h: number) {
  const n = Math.pow(2, view.zoom) * TILE;              // world size in pixels
  const wx = (lon: number) => ((lon + 180) / 360) * n;
  const wy = (lat: number) => (0.5 - mercY(lat) / (2 * Math.PI)) * n;
  const cx = wx(view.lon), cy = wy(view.lat);
  return {
    n,
    x: (lon: number) => wx(lon) - cx + w / 2,
    y: (lat: number) => wy(lat) - cy + h / 2,
    lon: (px: number) => ((px - w / 2 + cx) / n) * 360 - 180,
    lat: (py: number) => latOfMercY((0.5 - (py - h / 2 + cy) / n) * 2 * Math.PI),
    // Metres per pixel at this latitude, the standard web-mercator figure.
    mPerPx: (156543.03392 * Math.cos((view.lat * Math.PI) / 180)) /
            Math.pow(2, view.zoom),
  };
}

/* Bearing between two points, for pointing the aircraft symbol the way it is
 * actually going. Plane trigonometry on the mercator plane rather than a great
 * circle: over the few kilometres between two samples the difference is far
 * below the width of the symbol. */
function bearing(a: FlightSample, b: FlightSample): number {
  const dx = (b.lon_deg - a.lon_deg) *
             Math.cos(((a.lat_deg + b.lat_deg) / 2) * Math.PI / 180);
  const dy = b.lat_deg - a.lat_deg;
  if (!dx && !dy) return 0;
  return (Math.atan2(dx, dy) * 180) / Math.PI;
}

type Health = "unknown" | "ok" | "degraded" | "down";

/* One map tile. `key` names the tile; `rkey` names the <img> showing it,
 * which changes on a retry so that the browser asks again. */
interface Tile {
  key: string; rkey: string; url: string; left: number; top: number;
  size: number; tries: number; z: number; tx: number; ty: number; layer: string;
}

export function TerrainMap({
  wps, onChange, onPick, w: wProp = 620, h: hProp = 470, envKm, envNewKm, flight, flightIndex,
  events, verdict,
}: {
  wps: RouteWaypoint[];
  onChange?: (w: RouteWaypoint[]) => void;
  /* A click on the map, as a position. Given, it replaces the default
   * "append a waypoint": the planner decides what a click means (origin,
   * destination, or a point on the way). */
  onPick?: (lat: number, lon: number) => void;
  w?: number; h?: number; envKm?: number; envNewKm?: number;
  /* The flown track, when a flight has been simulated. The map draws the part
   * already flown solid and the part still to come faint, with the aircraft at
   * `flightIndex` -- so the picture is a flight in progress, not a line. */
  flight?: FlightSample[];
  flightIndex?: number;
  events?: { lat_deg: number; lon_deg: number; severity: string; code: string;
             message?: string }[];
  /* GO / GO_WITH_LIMITS / NO_GO, shown as a corner annunciator. The verdict is
   * decided by the engine model on the server; the map only displays it, and
   * displays it HERE because the answer belongs beside the route it is about
   * rather than in a panel the operator has to look away to read. */
  verdict?: string;
}) {
  /* THE MAP IS AS WIDE AS THE PANEL IT IS IN, NOT 620 PIXELS.
   *
   * A fixed pixel width is a layout bug waiting for the first change of
   * furniture, and Zone D was that change: adding the alert rail the HMI
  * standard requires took 300 px out of the work area and the map carried
  * straight on drawing itself 620 px wide, clipped at the panel edge.
   *
   * PRD Part 4 s6.3 also requires the console to remain usable at 1366x768,
   * which a fixed-width map cannot do. The projection maths needs a NUMBER
  * rather than a percentage -- every tile position and every waypoint is
  * computed from it -- so the container is measured and the number comes
  * from that. */
  const wrap = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const [measuredW, setMeasuredW] = useState<number | null>(null);
  const [measuredH, setMeasuredH] = useState<number | null>(null);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const host = el.parentElement;
    /* THE MAP TAKES THE PANEL'S SLACK, MEASURED RATHER THAN ESTIMATED.
     *
     * This used to add up the other children's heights at a guessed 12 px
     * apiece, forgot the toolbar above the map and the panel's own padding,
     * and then capped the answer at 340 px -- so on a 1080-line display the
     * map sat in the top third of its panel over 300 px of nothing, and
     * wherever the guess came out short the panel overflowed and flashed its
     * MORE BELOW strip on and off as the two resized each other.
     *
     * Now: how far the panel's last line of content falls short of (or past)
     * the panel's inner bottom edge is exactly how much taller (or shorter)
     * the map can be. One pass lands on it, because nothing else in the panel
     * depends on the map's height; a 3 px dead band keeps sub-pixel rounding
     * from ever re-triggering it. A panel that sizes to its content has no
     * slack in either direction, and the map keeps the height it was given. */
    const measure = () => {
      setMeasuredW((prev) => (prev === el.clientWidth ? prev : el.clientWidth));
      const mapBox = box.current;
      if (!host || !mapBox) return;
      const inner = host.getBoundingClientRect().top + host.clientTop
        + host.clientHeight - parseFloat(getComputedStyle(host).paddingBottom || "0");
      let bottom = -Infinity;
      for (const c of Array.from(host.children) as HTMLElement[]) {
        const mb = parseFloat(getComputedStyle(c).marginBottom || "0");
        bottom = Math.max(bottom, c.getBoundingClientRect().bottom + mb);
      }
      if (!Number.isFinite(bottom)) return;
      // Content scrolled up sits higher on screen than it is laid out.
      const slack = inner - (bottom + host.scrollTop);
      const next = Math.round(mapBox.getBoundingClientRect().height + slack);
      setMeasuredH((prev) =>
        prev != null && Math.abs(prev - next) < 3 ? prev : next);
      // A sibling that changes height (the playback transport appearing, the
      // route profile arriving) changes the slack without resizing the panel.
      for (const c of Array.from(host.children)) ro.observe(c);
    };
    const ro = new ResizeObserver(() => measure());
    ro.observe(el);
    if (host) ro.observe(host);
    measure();
    return () => ro.disconnect();
  }, []);
  // Never narrower than a usable chart; the panel scrolls before the map does.
  const w = Math.max(320, Math.round(measuredW ?? wProp));
  /* THE HEIGHT COMES FROM THE PANEL TOO, down to a floor at which a chart
   * stops being a chart. `h` is only the starting height. */
  const h = Math.max(220, Math.round(measuredH ?? hProp));

  const [layer, setLayer] = useState<TileLayer>(
    LAYERS.find((l) => l.id === DEFAULT_LAYER_ID) ?? LAYERS[0]);
  /* RADAR MODE: range and bearing from the ground station.
   *
   * A plan view answers "where does the route go". It does not answer the
   * question a ground station actually asks about an aircraft in the air,
   * which is "how far out is it and on what bearing" -- the two numbers that
   * decide whether it is still inside the control link, whether it can be
   * recovered, and how long until it is home. Those are one ring diagram and
   * they are drawn from the station, not from the aircraft. */
  const [radar, setRadar] = useState(false);
  const [view, setView] = useState<View>({ lat: 27.5, lon: 78.0, zoom: 5 });
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);
  const [moved, setMoved] = useState(false);
  const [hover, setHover] = useState<{ lat: number; lon: number } | null>(null);
  /* Per-tile retry count, keyed by tile. Bumping it both picks the next host
   * and changes the img's React key, which is what forces the re-request. */
  const [retry, setRetry] = useState<Record<string, number>>({});
  const [health, setHealth] = useState<Record<string, Health>>({});
  const [handover, setHandover] = useState<string>("");
  /* Tile outcomes for the layer currently shown. A ref rather than state: it
   * is written on every tile load and reading it must not re-render. */
  const tally = useRef<{ id: string; ok: number; bad: number }>(
    { id: DEFAULT_LAYER_ID, ok: 0, bad: 0 });

  const p = useMemo(() => project(view, w, h), [view, w, h]);

  /* Switching layer resets everything that was measured about the last one.
   * The bug this fixes: one shared boolean meant a layer that had failed kept
   * its error message on a layer that was working, and vice versa. */
  const pickLayer = useCallback((l: TileLayer) => {
    tally.current = { id: l.id, ok: 0, bad: 0 };
    setRetry({});
    setHandover("");
    setLayer(l);
  }, []);

  /* A layer that will not serve tiles hands over to one that will, and says
   * so. Silently showing a different map than the one selected would be worse
   * than showing none. */
  const failLayer = useCallback((failed: TileLayer) => {
    const next = LAYERS.find(
      (l) => l.id !== failed.id && health[l.id] !== "down");
    if (!next) return;
    tally.current = { id: next.id, ok: 0, bad: 0 };
    setRetry({});
    setLayer(next);
    setHandover(`${failed.label} is not serving tiles — showing ${next.label}`);
  }, [health]);

  const onTile = useCallback((_key: string, ok: boolean, l: TileLayer) => {
    if (tally.current.id !== l.id) return;
    if (ok) { tally.current.ok += 1; } else { tally.current.bad += 1; }
    const { ok: g, bad } = tally.current;
    const state: Health =
      bad === 0 ? (g > 0 ? "ok" : "unknown")
      : g === 0 && bad >= 4 ? "down"
      : "degraded";
    setHealth((prev) => (prev[l.id] === state ? prev : { ...prev, [l.id]: state }));
    if (state === "down") failLayer(l);
  }, [failLayer]);

  // Which tiles cover the viewport, plus one ring so a pan does not flash.
  /* THE TILE ZOOM MUST BE A WHOLE NUMBER; see below. */
  const tz = Math.max(0, Math.min(Math.floor(view.zoom), layer.maxZoom));
  const tiles = useMemo(() => {
    /* THE TILE ZOOM MUST BE A WHOLE NUMBER.
     * The view zoom is fractional so that the wheel can move smoothly; a tile
     * URL cannot be. Flooring here and scaling the tile size by the remainder
     * is what makes a fractional view zoom draw at all -- without it the URLs
     * ask for level 5.37 and every tile 404s. */
    const z = tz;
    const scale = Math.pow(2, view.zoom - z);
    const size = TILE * scale;
    const n = Math.pow(2, z);
    const originX = p.x(-180);
    const worldY0 = p.y(latOfMercY(Math.PI));
    const x0 = Math.floor((0 - originX) / size) - 1;
    const x1 = Math.ceil((w - originX) / size) + 1;
    const y0 = Math.max(0, Math.floor((0 - worldY0) / size) - 1);
    const y1 = Math.min(n, Math.ceil((h - worldY0) / size) + 1);
    const subs = layer.subdomains ?? [""];
    const out: Tile[] = [];
    for (let ty = y0; ty < y1; ty++) {
      for (let tx = x0; tx < x1; tx++) {
        const wrapped = ((tx % n) + n) % n;
        const key = `${layer.id}/${z}/${tx}/${ty}`;
        const tries = retry[key] ?? 0;
        out.push({
          key, rkey: `${key}#${tries}`, tries, z, tx, ty, layer: layer.id,
          url: layer.url
            .replace("{s}", subs[(Math.abs(tx + ty) + tries) % subs.length])
            .replace("{z}", String(z))
            .replace("{x}", String(wrapped))
            .replace("{y}", String(ty)),
          left: originX + tx * size,
          top: worldY0 + ty * size,
          size,
        });
      }
    }
    return out;
  }, [view, layer, tz, w, h, p, retry]);

  /* KEEP THE LAST PICTURE UNTIL THE NEXT ONE HAS ARRIVED.
   *
   * The flicker: every time the zoom crossed a whole level, every tile's URL
   * changed at once, React removed all of them, and the map went to its bare
   * background until the new level downloaded -- measured, up to 20 of 20
   * tiles blank at once, on every zoom step and every notch of the slider
   * that crossed a level. Every map application avoids this the same way:
   * the level on screen stays underneath, scaled to the new zoom, until the
   * level replacing it has finished loading on top.
   *
   * `loaded` remembers the tiles that have actually arrived, at every level,
   * most recent last and bounded; `settled` is the last level whose every
   * tile arrived. Until the level on screen settles, whatever is remembered
   * of the other levels is drawn beneath it, coarse under fine -- zooming in,
   * the level just left covers everything; zooming out, it covers the middle
   * and the coarser levels seen earlier fill the edges. Tiles keep their React
   * key when they move from "current" to "underneath", so the <img> already on
   * screen is the one that stays -- nothing is fetched or decoded again. */
  const loaded = useRef(new Map<string, { url: string; z: number; tx: number;
                                           ty: number; layer: string }>());
  const [settled, setSettled] = useState<{ z: number; layer: string } | null>(null);
  const current = useRef<Tile[]>(tiles);
  current.current = tiles;

  const remember = useCallback((t: Tile) => {
    const m = loaded.current;
    m.delete(t.rkey);
    m.set(t.rkey, { url: t.url, z: t.z, tx: t.tx, ty: t.ty, layer: t.layer });
    // A few screens' worth; the oldest go first.
    while (m.size > LOADED_KEEP) m.delete(m.keys().next().value as string);
  }, []);

  /* Settled when every <img> of the level on screen has finished -- asked of
   * the images themselves. Bookkeeping by tile name got it wrong: a tile that
   * had loaded once at this level was counted as loaded when it came back,
   * though the <img> showing it was new and still empty, and the map dropped
   * the level beneath with half the screen still blank. `complete` is also
   * true of a tile that failed outright, which must not hold the level below
   * forever either. */
  const checkSettled = useCallback(() => {
    const cur = current.current;
    const imgs = box.current?.querySelectorAll<HTMLImageElement>("img[data-tile]");
    if (!cur.length || !imgs?.length || !Array.from(imgs).every((i) => i.complete)) return;
    const { z, layer: lid } = cur[0];
    setSettled((prev) => (prev && prev.z === z && prev.layer === lid
                          ? prev : { z, layer: lid }));
  }, []);
  // A level made of tiles already on screen (zoomed away and straight back)
  // fires no load events, so it is also checked each time the set changes.
  useEffect(() => { checkSettled(); }, [tiles, checkSettled]);

  const under = useMemo(() => {
    if (settled && settled.layer === layer.id && settled.z === tz) return [] as Tile[];
    const originX = p.x(-180);
    const worldY0 = p.y(latOfMercY(Math.PI));
    const out: Tile[] = [];
    loaded.current.forEach((rec, rkey) => {
      if (rec.layer !== layer.id || rec.z === tz || Math.abs(rec.z - tz) > 4) return;
      const size = TILE * Math.pow(2, view.zoom - rec.z);
      const left = originX + rec.tx * size, top = worldY0 + rec.ty * size;
      if (left > w || top > h || left + size < 0 || top + size < 0) return;
      out.push({ key: rkey, rkey, tries: 0, z: rec.z, tx: rec.tx, ty: rec.ty,
                 layer: rec.layer, url: rec.url, left, top, size });
    });
    // Coarse first, so the sharper levels are drawn over it where they exist.
    return out.sort((a, b) => a.z - b.z);
  }, [settled, layer.id, tz, view, w, h, p]);

  /* ---- zoom -------------------------------------------------------------
   * The complaint that produced this: one wheel notch moved a whole zoom
   * level, so a single flick of a smooth-scrolling wheel or one trackpad
   * gesture went from continent to street and back. A zoom level is a factor
   * of two; nothing else in a user interface moves by 100 % per event.
   *
   * The zoom is now fractional and proportional to the scroll distance, which
   * is what every map application does, with a hard cap per event so that one
   * violent gesture cannot cross more than half a level. */
  const zoomAbout = useCallback((px: number, py: number, dz: number) => {
    setView((v) => {
      const q = project(v, w, h);
      const lat = q.lat(py), lon = q.lon(px);
      const zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, v.zoom + dz));
      const nv = { ...v, zoom };
      const q2 = project(nv, w, h);
      // Keep the point under the pointer under the pointer.
      return { ...nv,
        lon: nv.lon + (lon - q2.lon(px)),
        lat: Math.max(-84, Math.min(84, nv.lat + (lat - q2.lat(py)))) };
    });
  }, [w, h]);

  /* ZOOM IS A DELIBERATE ACT, NOT A SIDE EFFECT OF SCROLLING PAST.
   *
   * The remaining complaint after the fractional zoom above was that the map
   * still zoomed whenever the wheel moved over it. On a page this tall that is
   * not a zoom control at all: an operator scrolling down to the assessment
   * panel passes the pointer across the map and arrives somewhere else on the
   * planet, having asked for neither.
   *
   * So the wheel zooms only while a modifier is held, which is what every
   * embedded map does and for the same reason, and the map SAYS so the moment
   * an unmodified wheel crosses it rather than leaving the operator to guess
   * why nothing happened. The slider and the +/- buttons beside it are the
   * deliberate controls; the wheel is the shortcut for someone who knows it.
   */
  const [scrollHint, setScrollHint] = useState(false);
  const hintTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) {
        // Not ours: let the page scroll, and say why the map did not move.
        setScrollHint(true);
        window.clearTimeout(hintTimer.current);
        hintTimer.current = window.setTimeout(() => setScrollHint(false), 1400);
        return;
      }
      // Ctrl+wheel is also the browser's own page zoom, so this one IS ours
      // to swallow -- and the listener must be non-passive to be allowed to.
      e.preventDefault();
      setScrollHint(false);
      const r = el.getBoundingClientRect();
      // deltaMode 1 is lines rather than pixels; a line is worth about 16 px.
      const px = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
      const dz = Math.max(-0.5, Math.min(0.5, -px * 0.0035));
      zoomAbout(e.clientX - r.left, e.clientY - r.top, dz);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      el.removeEventListener("wheel", onWheel);
      window.clearTimeout(hintTimer.current);
    };
  }, [zoomAbout]);

  const zoomStep = (d: number) => zoomAbout(w / 2, h / 2, d);

  /* Frame the whole route, which is the first thing wanted after placing
   * waypoints anywhere other than where the map happens to be looking. */
  /* 1.6: room around the route for the waypoint LABELS as well as the
   * points -- at 1.25 a two-point route put its end labels under the
   * position readout and off the right edge. */
  const fit = useCallback((pad = 1.6) => {
    const pts = flight?.length ? flight : wps;
    if (!pts.length) return;
    const lats = pts.map((q: any) => q.lat_deg), lons = pts.map((q: any) => q.lon_deg);
    const latMin = Math.min(...lats), latMax = Math.max(...lats);
    const lonMin = Math.min(...lons), lonMax = Math.max(...lons);
    const lat = (latMin + latMax) / 2, lon = (lonMin + lonMax) / 2;
    const dLon = Math.max(lonMax - lonMin, 0.02) * pad;
    const dLat = Math.max(mercY(latMax) - mercY(latMin), 0.0004) * pad;
    // The zoom at which the span fills the box, in each axis; take the tighter.
    const zx = Math.log2((w / TILE) * (360 / dLon));
    const zy = Math.log2((h / TILE) * ((2 * Math.PI) / dLat));
    setView({ lat, lon, zoom: Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Math.min(zx, zy))) });
  }, [wps, flight, w, h]);

  /* FRAME THE ROUTE ON ARRIVAL, RATHER THAN WAITING TO BE ASKED.
   *
   * The default view is a whole-subcontinent z5, and the default sortie spans
   * about two hundred kilometres inside it -- so the map opened showing the
   * route as three dots in the corner of an empty continent, which reads as a
   * map that has not loaded rather than one that is zoomed out. Fitted once on
   * arrival and once more when a flight is first simulated, and never again:
   * after that the operator owns the camera, and a view that re-centres itself
   * under the hand is worse than one that is slightly wrong.
   */
  const fitted = useRef("");
  useEffect(() => {
    const key = flight?.length ? "flight" : wps.length > 1 ? "route" : "";
    if (!key || fitted.current === key) return;
    fitted.current = key;
    fit();
  }, [wps, flight, fit]);

  /* ---- pan and place ---------------------------------------------------- */
  const onDown = (e: React.MouseEvent) => {
    setDrag({ x: e.clientX, y: e.clientY }); setMoved(false);
  };
  const onMove = (e: React.MouseEvent) => {
    const r = box.current?.getBoundingClientRect();
    if (r) setHover({ lat: p.lat(e.clientY - r.top), lon: p.lon(e.clientX - r.left) });
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) setMoved(true);
    setDrag({ x: e.clientX, y: e.clientY });
    setView((v) => {
      const q = project(v, w, h);
      return { ...v, lon: v.lon - (q.lon(w / 2 + dx) - q.lon(w / 2)),
               lat: Math.max(-84, Math.min(84, v.lat - (q.lat(h / 2 + dy) - q.lat(h / 2)))) };
    });
  };
  const onUp = (e: React.MouseEvent) => {
    setDrag(null);
    // A drag pans; a click places. Without the distinction every pan dropped a
    // waypoint where the operator let go.
    if (moved || (!onChange && !onPick)) return;
    const r = box.current?.getBoundingClientRect();
    if (!r) return;
    const lat = p.lat(e.clientY - r.top), lon = p.lon(e.clientX - r.left);
    if (onPick) { onPick(+lat.toFixed(4), +lon.toFixed(4)); return; }
    if (!onChange) return;
    onChange([...wps, {
      name: `WP${wps.length + 1}`,
      lat_deg: +lat.toFixed(4), lon_deg: +lon.toFixed(4),
      // The altitude is corrected by the terrain check once the route is
      // assessed; this is a starting value, not a claim about the ground.
      altitude_ft: wps.length ? wps[wps.length - 1].altitude_ft : 15000,
    }]);
  };

  const mPerPx = p.mPerPx;
  const barM = [100, 250, 500, 1000, 2000, 5000, 10000, 25000, 50000,
                100000, 250000, 500000, 1000000].find((m) => m / mPerPx > 70) ?? 1000000;
  const barLabel = barM >= 1000 ? `${barM / 1000} km` : `${barM} m`;
  const route = wps.map((q) => `${p.x(q.lon_deg).toFixed(1)},${p.y(q.lat_deg).toFixed(1)}`);
  const kmPerPx = mPerPx / 1000;

  /* WAYPOINT LABELS THAT DO NOT LIE ON TOP OF EACH OTHER.
   *
   * Every label used to sit up and to the right of its point, so a route with
   * waypoints close together printed "WP10 · 2,000 ft" through "WP12 · 2,000
   * ft" as one unreadable smear. Each label now takes the first of four places
   * around its point that no earlier label (or point) occupies; failing that
   * the name alone; failing that nothing on the map and the full label on
   * hover. Text is measured at the 13 px face's ~7.2 px per character, which
   * is conservative for this font. */
  const labels = (() => {
    const taken: { x0: number; y0: number; x1: number; y1: number }[] = [];
    const hit = (b: { x0: number; y0: number; x1: number; y1: number }) =>
      taken.some((o) => b.x0 < o.x1 && b.x1 > o.x0 && b.y0 < o.y1 && b.y1 > o.y0);
    const pts = wps.map((q) => ({ x: p.x(q.lon_deg), y: p.y(q.lat_deg) }));
    for (const pt of pts) taken.push({ x0: pt.x - 7, y0: pt.y - 7, x1: pt.x + 7, y1: pt.y + 7 });
    return wps.map((q, i) => {
      const { x, y } = pts[i];
      const full = `${q.name} · ${Math.round(q.altitude_ft).toLocaleString()} ft`;
      for (const text of [full, q.name]) {
        const tw = text.length * 7.2;
        const spots: [number, number, "start" | "end"][] = [
          [x + 10, y - 6, "start"], [x + 10, y + 17, "start"],
          [x - 10, y - 6, "end"], [x - 10, y + 17, "end"]];
        for (const [tx, ty, anchor] of spots) {
          const x0 = anchor === "start" ? tx : tx - tw;
          const box = { x0, y0: ty - 12, x1: x0 + tw, y1: ty + 3 };
          // A spot that would run off the map is not a spot: the label is cut
          // at the edge (a destination near the right read "DESTINATION · 12,").
          if (box.x0 < 4 || box.x1 > w - 4 || box.y0 < 34 || box.y1 > h - 30) continue;
          if (!hit(box)) {
            taken.push(box);
            return { x, y, tx, ty, anchor, text, full };
          }
        }
      }
      return { x, y, tx: x, ty: y, anchor: "start" as const, text: "", full };
    });
  })();

  /* ---- the flight ------------------------------------------------------- */
  const idx = Math.max(0, Math.min(flightIndex ?? 0, (flight?.length ?? 1) - 1));
  const flown = flight?.slice(0, idx + 1) ?? [];
  const ahead = flight?.slice(idx) ?? [];
  const here = flight?.[idx];
  const hdg = flight && flight.length > 1
    ? bearing(flight[Math.max(0, idx - 1)], flight[Math.min(flight.length - 1, idx + 1)])
    : 0;
  const pts = (rows: FlightSample[]) =>
    rows.map((s) => `${p.x(s.lon_deg).toFixed(1)},${p.y(s.lat_deg).toFixed(1)}`).join(" ");

  /* ---- radar: range and bearing from the ground station ------------------
   *
   * The station is the FIRST waypoint, because that is where the sortie is
   * launched and recovered from and therefore where the control link lives.
   * Range is a great circle and bearing is a true initial bearing -- not the
   * mercator-plane approximation used for pointing the aircraft symbol, which
   * is fine over the two kilometres between samples and is not fine over the
   * three hundred to the target.
   */
  const station = wps[0];
  const scope = (() => {
    if (!radar || !station || !here) return null;
    const toRad = Math.PI / 180;
    const p1 = station.lat_deg * toRad, p2 = here.lat_deg * toRad;
    const dl = (here.lon_deg - station.lon_deg) * toRad;
    const s = Math.sin(dl) * Math.cos(p2);
    const c = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
    const brg = (((Math.atan2(s, c) / toRad) % 360) + 360) % 360;
    const a = Math.sin((p2 - p1) / 2) ** 2
            + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    const km = 2 * 6371.0088 * Math.asin(Math.sqrt(a));
    return { brg, km };
  })();

  /* Ring spacing chosen so four rings span most of the visible half-height --
   * the same "pick a round number that fits" rule the scale bar uses, so the
   * rings and the bar never disagree about what a centimetre is worth. */
  const ringKm = [1, 2, 5, 10, 25, 50, 100, 200, 500, 1000]
    .find((k) => k / kmPerPx > h / 9) ?? 1000;

  const dot = (s: Health) =>
    s === "ok" ? "var(--state-normal)"
    : s === "degraded" ? "var(--alert-caut)"
    : s === "down" ? "var(--alert-warn)" : "var(--ink-mute)";

  return (
    <div ref={wrap} style={{ display: "flex", flexDirection: "column",
                             gap: "var(--space-2)", width: "100%", minWidth: 0 }}>
      {/* ONE TOOLBAR ABOVE THE MAP, NOT A COLUMN BESIDE IT.
          Six layer buttons stacked vertically spent a whole column of the panel
          on a setting that is changed once a session, next to the one thing on
          the page anybody actually looks at. They are a select now, and the
          controls that ARE used -- zoom, fit, radar -- sit in a single row that
          costs one line instead of a column. */}
      <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)",
                    flexWrap: "wrap", minWidth: 0 }}>
        <select value={layer.id}
                onChange={(e) => {
                  const l = LAYERS.find((x) => x.id === e.target.value);
                  if (l) pickLayer(l);
                }}
                title={layer.attribution}
                style={{ ...zoomBtn, padding: "5px 8px", fontSize: 16,
                         maxWidth: 170 }}>
          {LAYERS.map((l) => (
            <option key={l.id} value={l.id}>
              {l.label}
              {health[l.id] === "down" ? " — not serving"
               : health[l.id] === "degraded" ? " — degraded" : ""}
            </option>
          ))}
        </select>
        {/* The health of the layer in use, kept as a dot because the select
            cannot colour its own options reliably across browsers. */}
        <span title={health[layer.id] === "down" ? "not serving tiles"
                     : health[layer.id] === "degraded" ? "some tiles failing"
                     : "serving normally"}
              style={{ width: 9, height: 9, borderRadius: 5, flex: "0 0 auto",
                       background: dot(health[layer.id] ?? "unknown") }} />

        <button onClick={() => zoomStep(-1)} aria-label="zoom out"
                style={zoomBtn}>−</button>
        <input type="range" min={MIN_ZOOM} max={MAX_ZOOM} step={0.25}
               value={view.zoom} aria-label="zoom"
               onChange={(e) => setView((v) => ({ ...v, zoom: Number(e.target.value) }))}
               style={{ width: 130, minWidth: 0 }} />
        <button onClick={() => zoomStep(1)} aria-label="zoom in"
                style={zoomBtn}>+</button>

        <button onClick={() => fit()} style={{ ...zoomBtn, fontSize: 16 }}>
          FIT ROUTE
        </button>
        <button onClick={() => setRadar((r) => !r)}
                title="range and bearing rings from the ground station"
                style={{ ...zoomBtn, fontSize: 16,
                         background: radar ? "var(--alert-advis)" : "var(--bg-raised)",
                         color: radar ? "var(--on-advis)" : "var(--ink)" }}>
          {radar ? "RADAR ON" : "RADAR"}
        </button>

        {/* Only the zoom here: its width never changes. The pointer's
            position used to be printed here as well, and appearing on hover it
            wrapped the toolbar onto a second line -- which took 27 px off the
            map, and gave them back when the pointer left: the map jumped on
            every pass of the mouse. It is drawn on the map now. */}
        <div style={{ marginLeft: "auto", fontSize: 16, color: "var(--ink-mute)",
                      fontFamily: "var(--font-num)", whiteSpace: "nowrap" }}>
          {`z${view.zoom.toFixed(1)}`}
        </div>
      </div>

      <div ref={box} className="on-imagery"
           style={{ position: "relative", width: w, height: h, userSelect: "none",
                    border: "1px solid var(--line)", borderRadius: "var(--radius)",
                    overflow: "hidden", background: "#0b1018",
                    cursor: drag ? "grabbing" : "crosshair" }}
           onMouseDown={onDown} onMouseMove={onMove}
           onMouseUp={onUp} onMouseLeave={() => { setDrag(null); setHover(null); }}>
        {/* The settled level first, so the level loading lands on top of it;
            one list, so a tile keeps its <img> as it moves between them. */}
        {under.map((t) => (
          <img key={t.rkey} src={t.url} alt="" draggable={false}
               referrerPolicy="no-referrer"
               style={{ position: "absolute", left: t.left, top: t.top,
                        width: t.size, height: t.size }} />
        )).concat(tiles.map((t) => (
          <img key={t.rkey} src={t.url}
               width={t.size} height={t.size}
               alt="" draggable={false} loading="eager" decoding="async"
               referrerPolicy="no-referrer" data-tile=""
               onLoad={() => {
                 remember(t);
                 onTile(t.key, true, layer);
                 checkSettled();
               }}
               onError={() => {
                 // Retry on the NEXT host before counting it against the
                 // layer: one rate-limited host is the common case and it is
                 // survivable, where treating it as an outage is not.
                 if (t.tries < TILE_RETRIES) {
                   setRetry((r) => ({ ...r, [t.key]: (r[t.key] ?? 0) + 1 }));
                 } else {
                   onTile(t.key, false, layer);
                   checkSettled();
                 }
               }}
               style={{ position: "absolute", left: t.left, top: t.top,
                        width: t.size, height: t.size }} />
        )))}

        <svg width={w} height={h} style={{ position: "absolute", inset: 0,
                                           pointerEvents: "none" }}>
          {/* RANGE RINGS from the first waypoint, as the reference chart has
              them -- but these are not decorative distance rings: the outer is
              what an as-new engine could reach and the inner is what THIS one
              can. Dashed, because a model's reach is not a surveyed boundary. */}
          {envNewKm ? (
            <>
              <circle cx={p.x(wps[0]?.lon_deg ?? 0)} cy={p.y(wps[0]?.lat_deg ?? 0)}
                      r={envNewKm / kmPerPx} fill="none" stroke="#ffffff"
                      strokeWidth={1.6} strokeDasharray="2 7" opacity={0.85} />
              <text x={p.x(wps[0]?.lon_deg ?? 0)}
                    y={p.y(wps[0]?.lat_deg ?? 0) - envNewKm / kmPerPx - 5}
                    fontSize={12} fill="#fff" textAnchor="middle"
                    style={{ paintOrder: "stroke", stroke: "#000a", strokeWidth: 3 }}>
                {Math.round(envNewKm)} km as-new
              </text>
            </>
          ) : null}
          {envKm ? (
            <>
              <circle cx={p.x(wps[0]?.lon_deg ?? 0)} cy={p.y(wps[0]?.lat_deg ?? 0)}
                      r={envKm / kmPerPx} fill="none" stroke="var(--alert-caut)"
                      strokeWidth={2.2} strokeDasharray="9 5" />
              <text x={p.x(wps[0]?.lon_deg ?? 0)}
                    y={p.y(wps[0]?.lat_deg ?? 0) + envKm / kmPerPx + 15}
                    fontSize={12} fill="#ffb302" textAnchor="middle"
                    style={{ paintOrder: "stroke", stroke: "#000a", strokeWidth: 3 }}>
                {Math.round(envKm)} km today
              </text>
            </>
          ) : null}

          {/* THE RADAR SCOPE. Rings, bearing graticule, and the one line an
              operator actually reads: where the aircraft is relative to the
              station that has to get it back. Drawn UNDER the route.
              RED BY THE OPERATOR'S CHOICE: thin cyan dashes vanished on the
              light terrain tiles. Every line sits on a dark underlay so it
              reads on light and dark imagery alike. Red is otherwise kept for
              WARNING; the scope is only drawn while RADAR is switched on, so
              it is never mistaken for an alert that appeared by itself. */}
          {radar && station && (() => {
            const x0 = p.x(station.lon_deg), y0 = p.y(station.lat_deg);
            const RED = "var(--alert-warn)";
            const halo = { paintOrder: "stroke", stroke: "#000e",
                           strokeWidth: 4 } as const;
            // Ring labels go on the side of each ring facing the middle of
            // the map: at the top of the ring they fell off the map whenever
            // the station was near the top edge, which is most routes. They
            // sit midway between two bearing ticks, and never on the first
            // leg of the route, which leaves the station in that same
            // direction more often than not.
            const ang = (a: number) => Math.atan2(Math.sin(a), Math.cos(a));
            const toMid = Math.hypot(w / 2 - x0, h / 2 - y0) < 20
              ? -Math.PI / 4 : Math.atan2(h / 2 - y0, w / 2 - x0);
            const next = wps.find((q) => Math.hypot(p.x(q.lon_deg) - x0,
                                                    p.y(q.lat_deg) - y0) > 20);
            const leg = next ? Math.atan2(p.y(next.lat_deg) - y0,
                                          p.x(next.lon_deg) - x0) : null;
            const slots = Array.from({ length: 12 },
                                     (_, k) => ((-75 + 30 * k) * Math.PI) / 180);
            const clear = slots.filter((a) => leg === null
              || Math.abs(ang(a - leg)) > (20 * Math.PI) / 180);
            const lab = (clear.length ? clear : slots).reduce((b, a) =>
              Math.abs(ang(a - toMid)) < Math.abs(ang(b - toMid)) ? a : b);
            return (
              <g>
                {[1, 2, 3, 4].map((i) => {
                  const r = (ringKm * i) / kmPerPx;
                  return (
                    <g key={i}>
                      <circle cx={x0} cy={y0} r={r} fill="none" stroke="#000"
                              strokeWidth={4} opacity={0.45} />
                      <circle cx={x0} cy={y0} r={r} fill="none" stroke={RED}
                              strokeWidth={2} strokeDasharray="8 5" />
                      <text x={x0 + Math.cos(lab) * r}
                            y={y0 + Math.sin(lab) * r + 4} fontSize={13}
                            fontWeight={700} fill={RED} textAnchor="middle"
                            style={halo}>
                        {ringKm * i} km
                      </text>
                    </g>
                  );
                })}
                {/* Bearing graticule every 30 degrees, labelled in the three
                    figures a bearing is always spoken in. */}
                {Array.from({ length: 12 }, (_, i) => i * 30).map((deg) => {
                  const r = (ringKm * 4) / kmPerPx;
                  const rad = ((deg - 90) * Math.PI) / 180;
                  const c = Math.cos(rad), sn = Math.sin(rad);
                  return (
                    <g key={deg}>
                      <line x1={x0 + c * r * 0.9} y1={y0 + sn * r * 0.9}
                            x2={x0 + c * r} y2={y0 + sn * r}
                            stroke="#000" strokeWidth={4.5} opacity={0.45} />
                      <line x1={x0 + c * r * 0.9} y1={y0 + sn * r * 0.9}
                            x2={x0 + c * r} y2={y0 + sn * r}
                            stroke={RED} strokeWidth={2.2} />
                      <text x={x0 + c * r * 1.06} y={y0 + sn * r * 1.06 + 4}
                            fontSize={12} fontWeight={700} fill={RED}
                            textAnchor="middle" style={halo}>
                        {String(deg).padStart(3, "0")}
                      </text>
                    </g>
                  );
                })}
                <circle cx={x0} cy={y0} r={5} fill={RED}
                        stroke="#fff" strokeWidth={1.5} />
                {/* Station to aircraft: the range and bearing themselves. */}
                {here && scope && (
                  <>
                    <line x1={x0} y1={y0} x2={p.x(here.lon_deg)} y2={p.y(here.lat_deg)}
                          stroke="#000" strokeWidth={4.5} opacity={0.45} />
                    <line x1={x0} y1={y0} x2={p.x(here.lon_deg)} y2={p.y(here.lat_deg)}
                          stroke={RED} strokeWidth={2.2} strokeDasharray="8 5" />
                    <text x={(x0 + p.x(here.lon_deg)) / 2 + 6}
                          y={(y0 + p.y(here.lat_deg)) / 2}
                          fontSize={13} fontWeight={700} fill={RED} style={halo}>
                      {String(Math.round(scope.brg)).padStart(3, "0")}° ·{" "}
                      {scope.km < 10 ? scope.km.toFixed(1) : Math.round(scope.km)} km
                    </text>
                  </>
                )}
              </g>
            );
          })()}

          {/* The PLANNED route, which is what was asked for. */}
          {route.length > 1 && (
            <>
              <polyline points={route.join(" ")} fill="none" stroke="#000"
                        strokeWidth={5} opacity={0.45} strokeLinejoin="round" />
              <polyline points={route.join(" ")} fill="none"
                        stroke="var(--ref-selected)" strokeWidth={2.6}
                        strokeLinejoin="round"
                        strokeDasharray={flight?.length ? "7 5" : undefined} />
            </>
          )}

          {/* The FLOWN track, which is what the engine actually did. Drawn
              over the plan and solid, because where the aircraft went is a
              result and where it was planned to go is an input. */}
          {flight && flight.length > 1 && (
            <>
              <polyline points={pts(ahead)} fill="none" stroke="#ffffff"
                        strokeWidth={1.4} opacity={0.35} strokeLinejoin="round" />
              <polyline points={pts(flown)} fill="none" stroke="#000"
                        strokeWidth={6} opacity={0.5} strokeLinejoin="round" />
              <polyline points={pts(flown)} fill="none"
                        stroke="var(--state-normal)" strokeWidth={3}
                        strokeLinejoin="round" strokeLinecap="round" />
            </>
          )}

          {/* Where something happened, on the ground it happened over. */}
          {events?.map((e, i) => (
            <circle key={i} cx={p.x(e.lon_deg)} cy={p.y(e.lat_deg)} r={5}
                    fill="none" strokeWidth={2.4}
                    stroke={e.severity === "WARNING" ? "var(--alert-warn)"
                            : e.severity === "CAUTION" ? "var(--alert-caut)"
                            : "var(--alert-advis)"}>
              <title>{e.message ?? e.code}</title>
            </circle>
          ))}

          {labels.map((l, i) => (
            <g key={i}>
              <circle cx={l.x} cy={l.y} r={6}
                      fill="#fff" stroke="var(--ref-selected)" strokeWidth={2.5}>
                <title>{l.full}</title>
              </circle>
              {l.text && (
                <text x={l.tx} y={l.ty} fontSize={13} textAnchor={l.anchor}
                      fill="#fff" style={{ paintOrder: "stroke", stroke: "#000b",
                                           strokeWidth: 3.5 }}>
                  {l.text}
                </text>
              )}
            </g>
          ))}

          {/* THE AIRCRAFT. Pointed the way it is going, because a symbol that
              does not carry heading is a dot, and a dot on a track tells an
              operator nothing they could not read from the track. */}
          {here && (
            <g transform={`translate(${p.x(here.lon_deg)},${p.y(here.lat_deg)}) rotate(${hdg})`}>
              <path d="M0,-11 L7,7 L0,3 L-7,7 Z" fill="var(--state-normal)"
                    stroke="#04222b" strokeWidth={1.2} strokeLinejoin="round" />
            </g>
          )}
          {here && (
            <text x={p.x(here.lon_deg) + 12} y={p.y(here.lat_deg) + 16}
                  fontSize={12} fill="#7ee787"
                  style={{ paintOrder: "stroke", stroke: "#000b", strokeWidth: 3.5 }}>
              {Math.round(here.altitude_ft).toLocaleString()} ft · {here.phase}
            </text>
          )}

          <g transform={`translate(12,${h - 30})`}>
            <rect x={-5} y={-13} width={barM / mPerPx + 66} height={21}
                  fill="#000000aa" rx={2} />
            <line x1={0} y1={0} x2={barM / mPerPx} y2={0} stroke="#fff" strokeWidth={2} />
            <line x1={0} y1={-4} x2={0} y2={4} stroke="#fff" strokeWidth={2} />
            <line x1={barM / mPerPx} y1={-4} x2={barM / mPerPx} y2={4}
                  stroke="#fff" strokeWidth={2} />
            <text x={barM / mPerPx + 7} y={4} fontSize={12} fill="#fff">{barLabel}</text>
          </g>
          <g transform={`translate(${w - 24},22)`}>
            <circle cx={0} cy={4} r={13} fill="#000000aa" />
            <line x1={0} y1={12} x2={0} y2={-6} stroke="#fff" strokeWidth={2} />
            <polygon points="0,-9 -4,-2 4,-2" fill="#fff" />
            <text x={-3} y={16} fontSize={10} fill="#fff">N</text>
          </g>
        </svg>

        {/* CAN IT FLY THIS, ON THE MAP OF THE THING IT WOULD BE FLYING.
            The same verdict the panel beside this carries, put where the
            operator is already looking. */}
        {verdict && (
          <div style={{
            position: "absolute", right: 8, top: 8, fontSize: 16,
            fontFamily: "var(--font-ui)", letterSpacing: "0.06em",
            padding: "5px 11px", borderRadius: "var(--radius)",
            background: "#000000cc", pointerEvents: "none",
            border: `1.5px solid ${verdictColour(verdict)}`,
            color: verdictColour(verdict) }}>
            {verdict === "GO" ? "GO"
             : verdict === "GO_WITH_LIMITS" ? "GO WITH LIMITS" : "NO-GO"}
          </div>
        )}

        {/* Said only when an unmodified wheel has just been ignored, so the
            map never looks broken for doing the right thing. */}
        {scrollHint && (
          <div style={{
            position: "absolute", left: "50%", top: "50%", fontSize: 16,
            transform: "translate(-50%,-50%)", background: "#000000dd",
            color: "#fff", padding: "8px 14px", borderRadius: "var(--radius)",
            pointerEvents: "none", textAlign: "center", lineHeight: 1.4 }}>
            Hold <b>Ctrl</b> and scroll to zoom the map,<br />
            or use the zoom slider beside it
          </div>
        )}

        {/* The position under the pointer, drawn ON the map so that it
            appearing and disappearing moves nothing else. */}
        {hover && (
          <div style={{ position: "absolute", left: 8, top: 8, fontSize: 16,
                        fontFamily: "var(--font-num)", color: "#fff",
                        background: "#000000aa", padding: "2px 8px",
                        borderRadius: 2, pointerEvents: "none",
                        whiteSpace: "nowrap" }}>
            {`${Math.abs(hover.lat).toFixed(3)}°${hover.lat >= 0 ? "N" : "S"}  `
             + `${Math.abs(hover.lon).toFixed(3)}°${hover.lon >= 0 ? "E" : "W"}`}
          </div>
        )}

        {/* Attribution is a CONDITION of using these layers, not a courtesy. */}
        <div style={{ position: "absolute", right: 4, bottom: 3, fontSize: 16,
                      color: "#fff", background: "#000000aa", padding: "1px 6px",
                      borderRadius: 2, pointerEvents: "none" }}>
          {layer.attribution}
        </div>

        {/* Said once, about the layer it applies to, and cleared by switching.
            Not a latched boolean shared by all five. */}
        {handover && (
          <div style={notice("var(--alert-caut)")}>{handover}</div>
        )}
        {!handover && health[layer.id] === "degraded" && (
          <div style={notice("var(--alert-caut)")}>
            {layer.label}: some tiles are not arriving. The route, the reach
            rings and the terrain check are computed here and are unaffected.
          </div>
        )}
        {!handover && health[layer.id] === "down"
          && LAYERS.every((l) => health[l.id] === "down") && (
          <div style={notice("var(--alert-caut)")}>
            No map imagery — this station has no route to any tile service.
            The route, the reach rings, the terrain check and the flight
            simulation all still work: those are computed here, not fetched.
          </div>
        )}
      </div>
    </div>
  );
}

/* The console's own three, not a fourth set invented for the map. */
export function verdictColour(v: string): string {
  return v === "GO" ? "var(--state-normal)"
       : v === "GO_WITH_LIMITS" ? "var(--alert-caut)"
       : "var(--alert-warn-ink)";
}

const zoomBtn: React.CSSProperties = {
  fontSize: 17, lineHeight: 1, padding: "3px 9px", cursor: "pointer",
  fontFamily: "var(--font-ui)", background: "var(--bg-raised)",
  color: "var(--ink)", border: "1px solid var(--line)",
  borderRadius: "var(--radius)",
};

const notice = (colour: string): React.CSSProperties => ({
  position: "absolute", left: 8, top: 8, maxWidth: 380, fontSize: 16,
  color: colour, background: "#000000cc", padding: "6px 10px",
  borderRadius: "var(--radius)", lineHeight: 1.4,
});
