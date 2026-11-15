import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import proj4 from "proj4";
import Map from "ol/Map";
import View from "ol/View";
import Feature from "ol/Feature";
import Point from "ol/geom/Point";
import LineString from "ol/geom/LineString";
import ImageLayer from "ol/layer/Image";
import VectorLayer from "ol/layer/Vector";
import VectorSource from "ol/source/Vector";
import ImageStatic from "ol/source/ImageStatic";
import { register } from "ol/proj/proj4";
import { fromLonLat, get as getProjection, toLonLat } from "ol/proj";
import { Circle as CircleStyle, Fill, Stroke, Style, Text } from "ol/style";
import type { Location, RouteOutput, RouteStrategy, Site } from "../shared/types";
import { api, ApiClientError, type TerrainGridResponse } from "./apiClient";

// Same definition the API publishes at GET /api/v1/meta/frame (south-polar stereographic, Moon sphere).
const PROJ_ID = "LUNA_SP_STEREO";
const PROJ_DEF = "+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 +R=1737400 +units=m +no_defs";
proj4.defs(PROJ_ID, PROJ_DEF);
register(proj4);
const projection = getProjection(PROJ_ID)!;

const toMap = (lat: number, lon: number) => fromLonLat([lon, lat], projection);
const fromMap = (c: number[]) => {
  const [lon, lat] = toLonLat(c, projection);
  return { lat_deg: lat, lon_deg: lon };
};

const STRATEGY_COLOR: Record<RouteStrategy, string> = {
  shortest: "#5aa9ff",
  balanced: "#f2b84b",
  gentle: "#4cd08a",
};

type LayerMode = "elevation" | "slope" | "none";

function lerp(a: number[], b: number[], t: number) {
  return a.map((v, i) => Math.round(v + (b[i] - v) * t));
}
function elevationColor(t: number): number[] {
  const stops = [
    [20, 30, 70],
    [40, 110, 130],
    [190, 170, 120],
    [245, 245, 240],
  ];
  const x = Math.min(0.9999, Math.max(0, t)) * (stops.length - 1);
  const k = Math.floor(x);
  return lerp(stops[k], stops[k + 1], x - k);
}
function slopeColor(deg: number, limit = 15): number[] {
  if (deg > limit) return [150, 20, 30];
  const t = deg / limit;
  return t < 0.5 ? lerp([30, 150, 90], [240, 210, 60], t / 0.5) : lerp([240, 210, 60], [225, 70, 50], (t - 0.5) / 0.5);
}

function renderGridToDataUrl(g: TerrainGridResponse, mode: LayerMode): string {
  const canvas = document.createElement("canvas");
  canvas.width = g.cols;
  canvas.height = g.rows;
  const ctx = canvas.getContext("2d")!;
  const img = ctx.createImageData(g.cols, g.rows);
  const lo = Math.min(...g.elevation_m);
  const hi = Math.max(...g.elevation_m);
  for (let j = 0; j < g.rows; j++) {
    for (let i = 0; i < g.cols; i++) {
      const src = j * g.cols + i;
      const dst = ((g.rows - 1 - j) * g.cols + i) * 4; // canvas top = max projected y
      const c =
        mode === "slope" ? slopeColor(g.slope_deg[src]) : elevationColor((g.elevation_m[src] - lo) / (hi - lo || 1));
      img.data[dst] = c[0];
      img.data[dst + 1] = c[1];
      img.data[dst + 2] = c[2];
      img.data[dst + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  return canvas.toDataURL("image/png");
}

const fmtM = (m: number) => (m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${m.toFixed(0)} m`);

export function App() {
  const mapEl = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const terrainLayerRef = useRef<ImageLayer<ImageStatic> | null>(null);
  const siteSrc = useRef(new VectorSource());
  const routeSrc = useRef(new VectorSource());
  const measureSrc = useRef(new VectorSource());
  const searchSrc = useRef(new VectorSource());

  const [sites, setSites] = useState<Site[]>([]);
  const [sitesMeta, setSitesMeta] = useState<{ data_status: string; upstream: string; warnings: string[] }>();
  const [grid, setGrid] = useState<TerrainGridResponse | null>(null);
  const [layerMode, setLayerMode] = useState<LayerMode>("elevation");
  const [startId, setStartId] = useState("");
  const [targetId, setTargetId] = useState("");
  const [maxSlope, setMaxSlope] = useState(15);
  const [algorithm, setAlgorithm] = useState<"astar" | "dijkstra">("astar");
  const [route, setRoute] = useState<RouteOutput | null>(null);
  const [selAlt, setSelAlt] = useState<string>("");
  const [measureOn, setMeasureOn] = useState(false);
  const [measurePts, setMeasurePts] = useState<Array<{ lat_deg: number; lon_deg: number }>>([]);
  const [measureRes, setMeasureRes] = useState<{ distance_m: number; surface_distance_m: number } | null>(null);
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<{ lat_deg: number; lon_deg: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  // refs so OpenLayers handlers always see fresh state
  const stateRef = useRef({ measureOn, startId, targetId, selAlt, sites });
  stateRef.current = { measureOn, startId, targetId, selAlt, sites };

  const showError = (e: unknown) => setError(e instanceof ApiClientError ? `${e.code}: ${e.message}` : String(e));

  // ---------- map init ----------
  useEffect(() => {
    const terrainLayer = new ImageLayer<ImageStatic>({});
    terrainLayerRef.current = terrainLayer;

    const siteLayer = new VectorLayer({
      source: siteSrc.current,
      zIndex: 30,
      style: (f) => {
        const id = f.get("site_id") as string;
        const { startId: s, targetId: t } = stateRef.current;
        const color = id === s ? "#4cd08a" : id === t ? "#ff6b6b" : "#5aa9ff";
        return new Style({
          image: new CircleStyle({
            radius: id === s || id === t ? 9 : 7,
            fill: new Fill({ color }),
            stroke: new Stroke({ color: "#fff", width: 2 }),
          }),
          text: new Text({
            text: id,
            offsetY: -16,
            font: "12px system-ui",
            fill: new Fill({ color: "#fff" }),
            stroke: new Stroke({ color: "#000", width: 3 }),
          }),
        });
      },
    });

    const routeLayer = new VectorLayer({
      source: routeSrc.current,
      zIndex: 20,
      style: (f) => {
        const strat = f.get("strategy") as RouteStrategy;
        const selected = f.get("alt_id") === stateRef.current.selAlt;
        return new Style({
          stroke: new Stroke({
            color: STRATEGY_COLOR[strat],
            width: selected ? 5 : 2.5,
            lineDash: selected ? undefined : [8, 6],
          }),
          zIndex: selected ? 2 : 1,
        });
      },
    });

    const measureLayer = new VectorLayer({
      source: measureSrc.current,
      zIndex: 40,
      style: (f) =>
        f.getGeometry() instanceof LineString
          ? new Style({ stroke: new Stroke({ color: "#ffffff", width: 2, lineDash: [4, 4] }) })
          : new Style({
              image: new CircleStyle({
                radius: 4,
                fill: new Fill({ color: "#fff" }),
                stroke: new Stroke({ color: "#000", width: 1 }),
              }),
            }),
    });

    const searchLayer = new VectorLayer({
      source: searchSrc.current,
      zIndex: 35,
      style: new Style({
        image: new CircleStyle({
          radius: 8,
          fill: new Fill({ color: "rgba(255,255,255,0.15)" }),
          stroke: new Stroke({ color: "#fff", width: 2 }),
        }),
      }),
    });

    const map = new Map({
      target: mapEl.current!,
      layers: [terrainLayer, routeLayer, searchLayer, siteLayer, measureLayer],
      view: new View({ projection, center: [0, 0], resolution: 130, minResolution: 2, maxResolution: 400 }),
    });
    mapRef.current = map;

    map.on("pointermove", (e) => setCursor(fromMap(e.coordinate)));
    map.on("click", (e) => {
      const st = stateRef.current;
      if (st.measureOn) {
        setMeasurePts((p) => [...p, fromMap(e.coordinate)]);
        return;
      }
      const hit = map.forEachFeatureAtPixel(e.pixel, (f) => f, { layerFilter: (l) => l === siteLayer });
      if (hit) {
        const id = hit.get("site_id") as string;
        if (!st.startId || (st.startId && st.targetId)) {
          setStartId(id);
          setTargetId("");
        } else if (id !== st.startId) {
          setTargetId(id);
        }
      }
    });

    return () => {
      map.setTarget(undefined);
      mapRef.current = null;
    };
  }, []);

  // ---------- load data ----------
  const load = useCallback(async () => {
    setError(null);
    try {
      const [s, g] = await Promise.all([api.sites(), api.grid(2)]);
      setSites(s.sites);
      setSitesMeta({ data_status: s.data_status, upstream: s.upstream, warnings: s.warnings });
      setGrid(g);
      if (s.sites.length >= 2) {
        setStartId((v) => v || s.sites[0].site_id);
        setTargetId((v) => v || s.sites[2 % s.sites.length].site_id);
      }
    } catch (e) {
      showError(e);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  // sites -> pins
  useEffect(() => {
    siteSrc.current.clear();
    for (const s of sites) {
      const f = new Feature({ geometry: new Point(toMap(s.location.lat_deg, s.location.lon_deg)) });
      f.set("site_id", s.site_id);
      siteSrc.current.addFeature(f);
    }
  }, [sites]);

  // restyle pins when start/target change; clear stale route
  useEffect(() => {
    siteSrc.current.changed();
    routeSrc.current.clear();
    setRoute(null);
  }, [startId, targetId]);

  // terrain layer
  const extent = useMemo(() => {
    if (!grid) return null;
    const half = grid.cell_size_m / 2;
    return [
      grid.origin_x_m - half,
      grid.origin_y_m - half,
      grid.origin_x_m + (grid.cols - 1) * grid.cell_size_m + half,
      grid.origin_y_m + (grid.rows - 1) * grid.cell_size_m + half,
    ] as [number, number, number, number];
  }, [grid]);

  const firstFit = useRef(true);
  useEffect(() => {
    const layer = terrainLayerRef.current;
    if (!layer || !grid || !extent) return;
    if (layerMode === "none") {
      layer.setVisible(false);
      return;
    }
    layer.setVisible(true);
    layer.setSource(new ImageStatic({ url: renderGridToDataUrl(grid, layerMode), imageExtent: extent, projection }));
    if (firstFit.current && mapRef.current) {
      mapRef.current.getView().fit(extent, { size: mapRef.current.getSize() });
      firstFit.current = false;
    }
  }, [grid, extent, layerMode]);

  // route features
  useEffect(() => {
    routeSrc.current.clear();
    if (!route) return;
    for (const alt of route.alternatives) {
      const f = new Feature({
        geometry: new LineString(alt.waypoints.map((w) => toMap(w.lat_deg, w.lon_deg))),
      });
      f.set("alt_id", alt.alt_id);
      f.set("strategy", alt.strategy);
      routeSrc.current.addFeature(f);
    }
  }, [route]);
  useEffect(() => {
    routeSrc.current.changed();
  }, [selAlt]);

  // measure features + API distance
  useEffect(() => {
    measureSrc.current.clear();
    const coords = measurePts.map((p) => toMap(p.lat_deg, p.lon_deg));
    coords.forEach((c) => measureSrc.current.addFeature(new Feature(new Point(c))));
    if (coords.length >= 2) measureSrc.current.addFeature(new Feature(new LineString(coords)));
    if (measurePts.length < 2) {
      setMeasureRes(null);
      return;
    }
    let cancelled = false;
    api
      .distance(measurePts)
      .then((r) => !cancelled && setMeasureRes(r))
      .catch((e) => !cancelled && showError(e));
    return () => {
      cancelled = true;
    };
  }, [measurePts]);

  // ---------- actions ----------
  const siteById = (id: string) => sites.find((s) => s.site_id === id);

  const flyTo = (loc: Pick<Location, "lat_deg" | "lon_deg">) =>
    mapRef.current?.getView().animate({ center: toMap(loc.lat_deg, loc.lon_deg), resolution: 60, duration: 400 });

  const onSearch = async () => {
    setError(null);
    setInfo(null);
    searchSrc.current.clear();
    const q = search.trim();
    if (!q) return;
    const m = q.match(/^(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)$/);
    if (m) {
      const lat = Number(m[1]);
      const lon = Number(m[2]);
      try {
        const r = await api.sample(lat, lon);
        searchSrc.current.addFeature(new Feature(new Point(toMap(lat, lon))));
        flyTo({ lat_deg: lat, lon_deg: lon });
        setInfo(`(${lat}, ${lon}): elevation ${r.terrain.elevation_m} m, slope ${r.terrain.slope_deg} deg`);
      } catch (e) {
        showError(e);
      }
      return;
    }
    const hit = sites.find(
      (s) => s.name.toLowerCase().includes(q.toLowerCase()) || s.site_id.toLowerCase().includes(q.toLowerCase()),
    );
    if (hit) {
      flyTo(hit.location);
      setInfo(`${hit.site_id}: ${hit.name} - slope ${hit.terrain.slope_deg ?? "n/a"} deg`);
    } else setInfo("No matching site. Try a site id or 'lat, lon' like -89.2, 15.");
  };

  const onRoute = async () => {
    const a = siteById(startId);
    const b = siteById(targetId);
    if (!a || !b) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.routes(a.location, b.location, maxSlope, algorithm);
      setRoute(r);
      setSelAlt(r.alternatives[0]?.alt_id ?? "");
    } catch (e) {
      showError(e);
      setRoute(null);
    } finally {
      setBusy(false);
    }
  };

  const status = sitesMeta?.data_status ?? "UNAVAILABLE";

  return (
    <div className="app">
      <aside className="side">
        <div>
          <h1>Moon Explorer</h1>
          <div className="row">
            <span className="muted">LUNA NAV AI - Module 03</span>
            <span className={`badge ${status === "REAL" ? "real" : ""}`}>{status}</span>
          </div>
        </div>

        {status !== "REAL" && grid && (
          <div className="banner">
            Terrain is a synthetic fixture ({grid.terrain_source.data_status}), not NASA data. Routes are exploratory
            and not operationally validated.
          </div>
        )}
        {sitesMeta?.warnings.map((w) => (
          <div className="banner" key={w}>{w}</div>
        ))}
        {error && (
          <div className="error">
            {error} <button onClick={() => void load()}>Retry</button>
          </div>
        )}

        <section>
          <h2>Search</h2>
          <div className="row">
            <input
              value={search}
              placeholder="Site id or lat, lon"
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void onSearch()}
            />
            <button onClick={() => void onSearch()}>Go</button>
          </div>
          {info && <div className="muted" style={{ marginTop: 6 }}>{info}</div>}
        </section>

        <section>
          <h2>Terrain layer</h2>
          <div className="row">
            {(["elevation", "slope", "none"] as LayerMode[]).map((m) => (
              <button key={m} className={layerMode === m ? "on" : ""} onClick={() => setLayerMode(m)}>
                {m}
              </button>
            ))}
          </div>
        </section>

        <section>
          <h2>Route</h2>
          <div className="row" style={{ flexDirection: "column", alignItems: "stretch" }}>
            <label className="muted">Start</label>
            <select value={startId} onChange={(e) => setStartId(e.target.value)}>
              <option value="">-</option>
              {sites.map((s) => (
                <option key={s.site_id} value={s.site_id}>{s.site_id} - {s.name}</option>
              ))}
            </select>
            <label className="muted">Target</label>
            <select value={targetId} onChange={(e) => setTargetId(e.target.value)}>
              <option value="">-</option>
              {sites.map((s) => (
                <option key={s.site_id} value={s.site_id}>{s.site_id} - {s.name}</option>
              ))}
            </select>
            <label className="muted">Max slope: {maxSlope} deg</label>
            <input type="range" min={5} max={30} value={maxSlope} onChange={(e) => setMaxSlope(Number(e.target.value))} />
            <div className="row">
              <select value={algorithm} onChange={(e) => setAlgorithm(e.target.value as "astar" | "dijkstra")}>
                <option value="astar">A*</option>
                <option value="dijkstra">Dijkstra</option>
              </select>
              <button className="primary" disabled={!startId || !targetId || startId === targetId || busy} onClick={() => void onRoute()}>
                {busy ? "Computing..." : "Plan route"}
              </button>
            </div>
            <span className="muted">Tip: click two pins on the map to set start, then target.</span>
          </div>
        </section>

        {route && (
          <section>
            <h2>Alternatives</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {route.alternatives.map((a) => (
                <div key={a.alt_id} className={`alt ${a.alt_id === selAlt ? "sel" : ""}`} onClick={() => setSelAlt(a.alt_id)}>
                  <span className="dot" style={{ background: STRATEGY_COLOR[a.strategy] }} />
                  <b>{a.strategy}</b>
                  <div className="stats">
                    <span>Distance: {fmtM(a.distance_m)}</span>
                    <span>Max slope: {a.max_slope_deg} deg</span>
                    <span>Mean slope: {a.mean_slope_deg} deg</span>
                    <span>Climb: {a.elevation_gain_m} m</span>
                  </div>
                  {a.warnings.slice(1).map((w) => (
                    <div className="muted" key={w}>! {w}</div>
                  ))}
                </div>
              ))}
              <div className="muted">{route.disclaimers[0]}</div>
            </div>
          </section>
        )}

        <section>
          <h2>Measure distance</h2>
          <div className="row">
            <button className={measureOn ? "on" : ""} onClick={() => setMeasureOn((v) => !v)}>
              {measureOn ? "Measuring: click map" : "Start measuring"}
            </button>
            <button onClick={() => setMeasurePts([])} disabled={measurePts.length === 0}>Clear</button>
          </div>
          {measureRes && (
            <div className="muted" style={{ marginTop: 6 }}>
              Great-circle: {fmtM(measureRes.distance_m)} - surface: {fmtM(measureRes.surface_distance_m)}
            </div>
          )}
        </section>
      </aside>

      <main className="mapwrap">
        <div id="map" ref={mapEl} />
        <div className="hud">
          {cursor ? `lat ${cursor.lat_deg.toFixed(4)}°  lon ${cursor.lon_deg.toFixed(4)}°` : "IAU_MOON_ME - south polar stereographic"}
        </div>
        {layerMode !== "none" && (
          <div className="legend">
            {layerMode === "slope" ? "Slope (deg)" : "Elevation (relative)"}
            <div
              className="bar"
              style={{
                background:
                  layerMode === "slope"
                    ? "linear-gradient(90deg, rgb(30,150,90), rgb(240,210,60), rgb(225,70,50))"
                    : "linear-gradient(90deg, rgb(20,30,70), rgb(40,110,130), rgb(190,170,120), rgb(245,245,240))",
              }}
            />
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span>{layerMode === "slope" ? "0" : "low"}</span>
              <span>{layerMode === "slope" ? ">15 blocked" : "high"}</span>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
