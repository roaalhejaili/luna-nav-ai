// Spacecraft command-cabin opening. The cabin is drawn in SVG; the Moon behind the window is the shared
// shader canvas (#moon) and Earth is a small artistic canvas. Status screens show REAL service checks.

const SVG = `
<svg viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
  <defs>
    <linearGradient id="hull" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1b2638"/><stop offset=".55" stop-color="#101a29"/><stop offset="1" stop-color="#070c15"/></linearGradient>
    <linearGradient id="strut" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#0b111c"/><stop offset=".45" stop-color="#2b3a52"/><stop offset=".55" stop-color="#34465f"/><stop offset="1" stop-color="#0b111c"/></linearGradient>
    <linearGradient id="rim" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#3b4d68"/><stop offset="1" stop-color="#16202f"/></linearGradient>
    <linearGradient id="console" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1d2a3e"/><stop offset=".25" stop-color="#121c2b"/><stop offset="1" stop-color="#05080e"/></linearGradient>
    <radialGradient id="glow" cx=".5" cy="1" r=".8"><stop offset="0" stop-color="#69C6EE" stop-opacity=".18"/><stop offset="1" stop-color="#69C6EE" stop-opacity="0"/></radialGradient>
    <mask id="win"><rect width="1600" height="900" fill="#fff"/>
      <path d="M250 96 L1350 96 L1490 250 L1440 560 L160 560 L110 250 Z" fill="#000"/></mask>
  </defs>
  <rect width="1600" height="900" fill="url(#hull)" mask="url(#win)"/>
  <path d="M250 96 L1350 96 L1490 250 L1440 560 L160 560 L110 250 Z" fill="none" stroke="url(#rim)" stroke-width="22" stroke-linejoin="round"/>
  <path d="M250 96 L1350 96 L1490 250 L1440 560 L160 560 L110 250 Z" fill="none" stroke="#5c7090" stroke-opacity=".35" stroke-width="2"/>
  <path d="M600 96 L560 560" stroke="url(#strut)" stroke-width="30"/><path d="M1000 96 L1040 560" stroke="url(#strut)" stroke-width="30"/>
  <g fill="#4a5d7a">${[[262, 108], [1338, 108], [1476, 252], [1428, 548], [172, 548], [124, 252], [600, 110], [1000, 110], [563, 545], [1037, 545]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="4"/>`).join("")}</g>
  <path d="M0 0 H1600 V60 L1350 70 H250 L0 60 Z" fill="#0c131f"/>
  <g>${Array.from({ length: 14 }, (_, i) => `<rect x="${330 + i * 68}" y="22" width="34" height="12" rx="3" fill="${i % 5 === 1 ? "#F2C35B" : i % 3 === 0 ? "#69C6EE" : "#22324a"}" opacity="${i % 5 === 1 || i % 3 === 0 ? .8 : 1}"/>`).join("")}</g>
  <path d="M0 610 L230 590 L1370 590 L1600 610 V900 H0 Z" fill="url(#console)"/>
  <path d="M230 590 L1370 590" stroke="#3c4f6c" stroke-width="2"/>
  <rect x="0" y="590" width="1600" height="310" fill="url(#glow)"/>
  <g fill="#1a2536" stroke="#2e405a">${[[70, 680], [1420, 680]].map(([x, y]) => `<rect x="${x}" y="${y}" width="110" height="150" rx="10"/>`).join("")}</g>
  <g>${Array.from({ length: 12 }, (_, i) => `<circle cx="${95 + (i % 3) * 30 + (i > 5 ? 1350 : 0)}" cy="${705 + Math.floor((i % 6) / 3) * 34 + (i % 2) * 0}" r="6" fill="${i % 4 === 0 ? "#A9C99A" : "#2c3b52"}"/>`).join("")}</g>
  <path d="M0 0 L120 0 L60 900 L0 900 Z" fill="#070b13" opacity=".9"/><path d="M1600 0 L1480 0 L1540 900 L1600 900 Z" fill="#070b13" opacity=".9"/>
</svg>`;

export function mountCabin(root, { onStart, status }) {
  root.insertAdjacentHTML("afterbegin", `<div class="cabin-svg">${SVG}</div><canvas class="earth" width="160" height="160" aria-hidden="true"></canvas>`);
  drawEarth(root.querySelector(".earth"));
  const clock = root.querySelector("#cabin-clock");
  const tick = () => { if (clock) clock.textContent = new Date().toISOString().replace("T", "  ").slice(0, 20) + " UTC"; };
  tick(); setInterval(tick, 1000);
  // gentle parallax: cabin moves more than the far Moon
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduce) root.addEventListener("pointermove", (e) => {
    const x = e.clientX / innerWidth - 0.5, y = e.clientY / innerHeight - 0.5;
    root.style.setProperty("--px", `${(-x * 14).toFixed(1)}px`); root.style.setProperty("--py", `${(-y * 10).toFixed(1)}px`);
    root.style.setProperty("--mx", `${(-x * 4).toFixed(1)}px`); root.style.setProperty("--my", `${(-y * 3).toFixed(1)}px`);
  });
  root.querySelector("#start-mission").addEventListener("click", () => { root.classList.add("launch"); setTimeout(onStart, reduce ? 0 : 900); });
  return { setStatus: status };
}

function drawEarth(c) {
  const x = c.getContext("2d"), r = 70, cx = 80, cy = 80;
  const g = x.createRadialGradient(cx - 22, cy - 18, 6, cx, cy, r); g.addColorStop(0, "#9fd3f2"); g.addColorStop(0.55, "#2f6fae"); g.addColorStop(1, "#0b2547");
  x.fillStyle = g; x.beginPath(); x.arc(cx, cy, r, 0, 7); x.fill();
  x.save(); x.beginPath(); x.arc(cx, cy, r, 0, 7); x.clip(); let s = 3; const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647);
  x.fillStyle = "rgba(120,150,90,.55)"; for (let i = 0; i < 7; i++) { x.beginPath(); x.ellipse(cx - 40 + rnd() * 80, cy - 40 + rnd() * 80, 8 + rnd() * 18, 5 + rnd() * 12, rnd() * 3, 0, 7); x.fill(); }
  x.fillStyle = "rgba(255,255,255,.55)"; for (let i = 0; i < 14; i++) { x.beginPath(); x.ellipse(cx - 60 + rnd() * 120, cy - 60 + rnd() * 120, 10 + rnd() * 22, 2 + rnd() * 4, rnd() * 3, 0, 7); x.fill(); }
  const sh = x.createLinearGradient(cx - r, 0, cx + r, 0); sh.addColorStop(0.45, "rgba(0,0,0,0)"); sh.addColorStop(1, "rgba(0,0,0,.85)"); x.fillStyle = sh; x.fillRect(0, 0, 160, 160); x.restore();
  x.strokeStyle = "rgba(150,200,255,.35)"; x.lineWidth = 2; x.beginPath(); x.arc(cx, cy, r + 1, 0, 7); x.stroke();
}
