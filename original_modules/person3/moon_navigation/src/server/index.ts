import { createApp } from "./app.js";
import { loadLolaGrid } from "./lolaTerrain.js";

const port = Number(process.env.PORT ?? 3003);
// Real NASA terrain when LUNA_P3_LOLA_PATH points at LDEM_75S_240M.img; otherwise the labelled MOCK fixture.
const lolaPath = process.env.LUNA_P3_LOLA_PATH;
const grid = lolaPath
  ? loadLolaGrid(lolaPath, Number(process.env.LUNA_P3_HALF_EXTENT_M ?? 80_000), Number(process.env.LUNA_P3_STRIDE ?? 1))
  : undefined;
createApp({ grid }).listen(port, () => {
  const label = grid ? `${grid.source.name}, ${grid.cols}x${grid.rows} @ ${grid.cellSizeM} m (REAL)` : "MOCK fixture";
  console.log(`moon_navigation API listening on http://localhost:${port}/api/v1 (terrain: ${label})`);
});
