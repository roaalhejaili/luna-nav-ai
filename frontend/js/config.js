// Backend locations. Override with ?api=...&nav=... (saved to localStorage) when ports differ.
const q = new URLSearchParams(location.search);
function pick(key, fallback) {
  const fromQuery = q.get(key);
  try {
    if (fromQuery) localStorage.setItem(`luna.${key}`, fromQuery);
    return fromQuery || localStorage.getItem(`luna.${key}`) || fallback;
  } catch { return fromQuery || fallback; }
}
export const CONFIG = {
  // Person 4 Mission Optimizer (FastAPI). Default CORS allows http://localhost:5173.
  apiBase: pick("api", "http://127.0.0.1:8000").replace(/\/$/, ""),
  // Person 3 moon_navigation (Express, CORS open). Optional: terrain layer + rover routes.
  navBase: pick("nav", "http://localhost:3003/api/v1").replace(/\/$/, ""),
};
