# NASA and terrain data sources

## Official challenge Resources tab

The official [NASA Space Apps 2026 Lunar Landing Site Navigator Resources tab](https://www.spaceappschallenge.org/2026/challenges/lunar-landing-site-navigator/?tab=resources) was opened and inspected. It lists the following resources. NASA's page notes that it does not endorse non-U.S. Government entities and that participants must follow data-use parameters on non-U.S. Government websites.

| Listed resource | Provider / direct URL | What it provides | Person 01 relevance / integration status |
|---|---|---|---|
| QuickMap | Arizona State University / LROC: [https://quickmap.lroc.asu.edu/](https://quickmap.lroc.asu.edu/) (currently redirects to the ASU LROC `quickmap.lroc.im-ldi.com` site) | Interactive lunar map with LRO imagery, topographic data, and other layers. The challenge page identifies it as a way to inspect landing sites and south-polar terrain. | Useful for human visual cross-check. The challenge resource entry does not specify a machine data endpoint, downloadable DEM filename/format, reference frame, or resolution. QuickMap requires JavaScript in the browser inspection, so it is not used as a runtime dependency. Use the direct PDS LOLA archive below for reproducible raster measurements. |
| Moon Trek | NASA/JPL Solar System Treks: [https://trek.nasa.gov/moon/](https://trek.nasa.gov/moon/) | NASA lunar visualization and data portal; its official About page describes searching/viewing hundreds of lunar data products, with product metadata, visualization/download functions, elevation plots, slope, and lighting tools. | Relevant for visual/metadata validation. NASA documents an OGC REST WMTS tile service at [Moon Trek WMTS API docs](https://trek.nasa.gov/tiles/apidoc/trekAPI.html?body=moon), with tile URL template `https://{WMTS endpoint}/1.0.0/{Style}/{TileMatrixSet}/{TileMatrix}/{TileRow}/{TileCol}.{png|jpg}` and GetCapabilities metadata. These are rendered map tiles, not the raw numeric DEM interface used here. Available resolutions and formats vary by layer and are specified in each layer's capabilities/metadata; no one layer was downloaded or tested in this module. Some advanced analysis access may require a registered account. |
| Horizons System | NASA/JPL Solar System Dynamics: [web portal](https://ssd.jpl.nasa.gov/horizons/) and [official API documentation](https://ssd-api.jpl.nasa.gov/doc/horizons.html) | Ephemeris system; the challenge page describes Sun/Earth apparent positions from lunar sites. Direct query API is `GET https://ssd.jpl.nasa.gov/api/horizons.api`; JSON or text output is supported. | Not used by Person 01: celestial visibility belongs to Person 02. No key is documented for the public Horizons query API. |
| Moon Exploration | Canadian Space Agency: [https://www.asc-csa.gc.ca/eng/astronomy/moon-exploration/](https://www.asc-csa.gc.ca/eng/astronomy/moon-exploration/) | General Moon exploration, missions, science, and agency program information. | Background/reference only; the challenge entry does not identify a terrain DEM, data API, file format, resolution, or coordinate metadata for this portal. Not a module dependency. |

The challenge page itself is a reference directory, not a terrain API. The module's operational terrain source is the independently published NASA PDS LOLA GDR archive described below.

## Selected source: LRO LOLA Gridded Data Record (GDR)

| Attribute | Verified details |
|---|---|
| Resource | Lunar Reconnaissance Orbiter Lunar Orbiter Laser Altimeter (LOLA), Gridded Data Record; cylindrical DEM products such as `LDEM_16` |
| Provider | NASA Planetary Data System (PDS) Geosciences Node, with LOLA/LRO instrument team products |
| Direct directory | [PDS LOLA cylindrical IMG directory](https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/cylindrical/img/) |
| Example data | `https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/cylindrical/img/ldem_16.img` and matching `.lbl` |
| Format | PDS3 detached label `.lbl` plus uncompressed binary `.img`; selected loader supports 16-bit integer, honors label byte order, scale, dimensions, and map resolution |
| Map | Simple/equirectangular cylindrical, body-fixed rotating; longitude east-positive, 0–360° in the product; global latitude coverage -90° to +90° |
| Coordinate reference | Mean Earth / polar axis convention (the LOLA SIS sample identifies DE421); planetocentric latitude. API normalizes longitude to east-positive -180° to +180° |
| Units/datum | The LOLA SIS sample GDR label specifies `UNIT=METER`, `SCALING_FACTOR=0.5`, and `OFFSET=1737400 m`. Height is DN × scaling factor (m), relative to its reference sphere; the module does not apply a geoid correction. Runtime loader reads the actual supplied label values rather than assuming the example factor. |
| Resolution | `LDEM_16`: 16 pixels/degree, about 1.895 km/pixel at the equator; PDS directory lists 33,177,600 bytes (~31.64 MiB) for the IMG. Other products have different resolutions; the API reports equatorial pixel spacing computed from label resolution. |
| Access | Public HTTP directory; no API key was indicated in the PDS listing. |
| License/use | Public NASA/PDS science archive. Preserve product/label citation and metadata; follow the PDS data-use and citation guidance linked with the archive. NASA endorsement is not implied. |
| Module processing | PDS label is validated; raw signed 16-bit DNs are scaled to meters. Candidate points map to nearest pixels. Slope and local roughness are estimated from a 3×3 neighborhood and returned with raster resolution and product provenance. |

## Verification status

- **Verified source metadata:** PDS directory listing exposes `ldem_16.img` (33,177,600 bytes) and `ldem_16.lbl`; official LOLA RDR Software Interface Specification describes DEM IMG labels, integer sample type, scale factor, reference radius, cylindrical projection, east longitude, and mean-Earth/polar-axis frame. PDS data product records describe the LOLA GDR collection and multiple map resolutions.
- **Direct availability:** The PDS product directory and metadata were confirmed through official PDS listings and LOLA documentation. An attempted binary and label download from the published PDS URL failed in this environment with a Windows TLS credential error; no actual DEM file was downloaded into the project.
- **Successful real processing:** **Not yet verified.** Tests validate PDS parsing and sampling using a generated tiny PDS-format fixture; this fixture is not NASA data. To run real mode, download the PDS IMG and matching LBL and set `LUNA_DEM_PATH` / `LUNA_DEM_LABEL_PATH`.
- **NASA ancillary slope/roughness:** The PDS LOLA GDR archive also describes gridded slope and roughness products. This release computes local derivatives from its loaded DEM instead of loading those ancillary products. Output roughness is therefore a local 3×3 elevation standard deviation, not a claim of matching an official LOLA roughness layer.
- **Limits:** LDEM_16's roughly 1.9 km equatorial pixel spacing is far too coarse for a final landing hazard map. Polar ground spacing differs from the equatorial value, and this prototype's slope estimate approximates local metric spacing. DEM values, coverage, and source metadata are only as sound as the supplied label/product pair.

## References

- [Official Space Apps challenge](https://www.spaceappschallenge.org/2026/challenges/lunar-landing-site-navigator/?tab=resources)
- [Official Moon Trek About page](https://trek.nasa.gov/moon/jpl/config/textAbout.html)
- [Moon Trek WMTS API documentation](https://trek.nasa.gov/tiles/apidoc/trekAPI.html?body=moon)
- [JPL Horizons API documentation](https://ssd-api.jpl.nasa.gov/doc/horizons.html)
- [ASU LROC QuickMap](https://quickmap.lroc.asu.edu/)
- [NASA PDS LOLA cylindrical products directory](https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/cylindrical/img/)
- [LOLA RDR Software Interface Specification](https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/document/rdrsis.htm)
- [NASA PDS LOLA GDR data set record](https://pds.nasa.gov/ds-view/pds/viewDataset.jsp?dsid=LRO-L-LOLA-4-GDR-V1.0)
- [NASA LRO LOLA instrument overview](https://science.nasa.gov/mission/lro/lola/)

## Integration addition (2026-11-14): polar LOLA grid and elevated candidates (opt-in)

`load_pds_img` also reads NASA LOLA **polar stereographic** products such as `LDEM_75S_240M` (240 m/pixel, 75° S to the pole), using the PDS `DSMAP_POLAR.CAT` forward equations with the orientation Person 2 verified against Shackleton, Shoemaker and Cabeus. Slope and roughness come from the same 3×3 window at the true 240 m spacing. Setting `LUNA_P1_CANDIDATE_STRATEGY=elevated` (polar grids only) replaces the regular lat/lon candidate pattern with local high points: cells highest within 1 km, slope under the request limit, at least 3 km apart, ordered by elevation. Near the pole, higher ground stays sunlit longer; illumination itself is still computed by Person 2. With the variable unset, output is byte-identical to the original module (checked on mock requests).
