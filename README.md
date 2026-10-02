# Dawei floods and landslides, 26 September – 2 October 2026

Interactive situation dashboard built from the 88 posts **Dawei Watch**
(<https://web.facebook.com/DaweiWatch>) published from 26 Sep to 2 Oct 2026, with every
place they name geocoded onto **MIMU** (Myanmar Information Management Unit) geography.

**Live dashboard:** <https://geonet-myanmar.github.io/dawei-flood-dashboard-v6/>

Or open `index.html` locally. It is self-contained (data inline; Leaflet from cdnjs) and the
MIMU vectors are the basemap; optional satellite/topographic tiles work when the
page is served normally. Earlier editions: 26 Sep – 1 Oct at
<https://geonet-myanmar.github.io/dawei-flood-dashboard-v5/>, 26–30 Sep at
<https://geonet-myanmar.github.io/dawei-flood-dashboard-v4/>, 26–29 Sep at
<https://geonet-myanmar.github.io/dawei-flood-dashboard-v3/>, 26–28 Sep at
<https://geonet-myanmar.github.io/dawei-flood-dashboard-v2/>.

## What is on the page

- Headline figures as of 2 Oct: at least 41 dead, Dawei Watch's own place-by-place count to 1 Oct (31 Launglon,
  8 Thayetchaung, 2 Dawei) plus a Ti Zit death it counts apart; four bodies still under the earth on 1 Oct;
  red-level villages, houses buried or wrecked, people in shelters, and the Tanintharyi River at 30 ft 2 in
  (2 Oct morning, over 6 ft above its danger mark).
- Map with a **26 / 27 / 28 / 29 / 30 Sep / 1 / 2 Oct switch**: each of 145 places shows what had been
  reported by the end of that day (colour = what happened to people, shape = hazard,
  ring = red level, blue arrow = water reported falling). Also: cut or flooded roads and
  bridges, junta troop movements and the 29 Sep SEZ fighting the posts report, the rescue convoy's route, the area
  beyond its furthest point, flooded wards, and MIMU villages, hospitals, schools, roads,
  bridges, rivers, land below 5 m, mine sites and the Dawei SEZ.
- Posts tab: the Dawei Watch feed newest first; opening a post shows only the places it named.
- Charts and tables: places by township and day first named; the death count as reported
  (Launglon and the whole area); where the 41 dead were (Dawei Watch's 2 Oct
  round-up); the Tanintharyi River against its alert and danger marks and the 2024 flood, 30 ft 2 in
  on 2 Oct; flooded villages along it as the count grew; outside donations; rescue progress and
  what lay beyond it (MIMU analysis); lifelines board; September and storm rainfall
  (Open-Meteo model plus the two DMH records); the explainer's storm sequence; toll ledger;
  seven-township comparison; facilities within 1 km; red-level villages; timeline; quotes
  (Myanmar + English).

## Rebuild

```
pip install -r requirements.txt
python scripts/01_download_mimu.py    # MIMU GeoServer WFS -> data/raw/ (gitignored)
python scripts/02_fetch_rainfall.py   # Open-Meteo -> data/source/rainfall_openmeteo.json
python scripts/03_build_reports.py    # posts -> data/processed/flood.json (geocoded, by day)
python scripts/04_process_gis.py      # clip/simplify + analysis -> data/processed/
python scripts/05_build_html.py       # src/template.html + data -> index.html, dist/
```

Script 01 skips layers already in `data/raw/`; delete a file to fetch it again. Script 02
caches its result (last fetched 29 Sep, 12:29 UTC); model hours are replaced by analysis
values over time, so re-running it later changes the rainfall numbers. Skip it to keep the
published figures. Never hand-edit `index.html`; edit `src/template.html` and re-run script 05.

## Sources and limits

- Posts: `data/source/dawei_watch_2026-09-26_10-02.docx`, flattened to
  `dawei_watch_2026-09-26_10-02.txt` (one paragraph per line, newest post first). Every place,
  figure, quote, event and lifeline cell in `flood.json` cites a line of that file; script 03
  checks the post boundaries, every cited line and every quote against it. Lines 68–1181 are
  the 26 Sep – 1 Oct edition's file unchanged; lines 3–67 are the seven posts of 2 Oct (lines 1–2 are
  separator rules in the docx). Days are numbered on from September, so 1 Oct is day 31 and 2 Oct day 32. Myanmar names are compared
  after putting the dot-below and asat marks (U+1037, U+103A) in one order, as the posts and MIMU differ.
- Launglon's toll: on 1 Oct one post said 26 and a later one 31. The 26 Sep – 1 Oct edition took the 31 to
  count Taw Kye's five twice and used 26. Dawei Watch's 2 Oct round-up confirms 31 place by place (Kadet Nge
  Htein 15, Taw Kye 5, Tha Byar 3, Kadet Gyi, Nyaw Pyin and Kyauk Ni Maw 2 each, Za Lut Pyin Gyi and Min Yat 1
  each), so this edition uses its 41 for the whole area and shows the Ti Zit death, which it counts apart, separately.
- Figures are as reported while many villages were still cut off; unverified, and they
  disagree between posts (Kyauk Ni Maw most of all). The dashboard shows the latest and notes
  the conflicts.
- The 17 ft mark on the Tanintharyi River is its alert level and 24 ft its danger level
  (29 Sep post); the 26–28 Sep edition called 17 ft the danger mark.
- Geocoding grades (in `flood.json`): 115 exact, 9 variant, 4 probable, 7 approximate,
  10 not found in MIMU.
- MIMU: boundaries v9.4, village points, wards v9.4, health facilities 2020 (hospitals
  only), formal schools 2019, roads 1:250k, bridges, mining areas, land below 5 m,
  industrial zones 2024. Area of interest: Dawei District, Palaw, Tanintharyi and Bokpyin.
- Ka Det Nge (ကဒက်ငယ်) in the posts is Ka Det Nge Htein (ကဒက်ငယ်ထိန်), as local residents confirmed; its
  reports are merged into that village at its MIMU point.
- Rainfall curves are Open-Meteo model output, not gauges.

## Deployment

GitHub Pages serves `index.html` from the root of the `main` branch of
`geonet-myanmar/dawei-flood-dashboard-v6` (`.nojekyll` skips the Jekyll build). To publish a
change: re-run `scripts/05_build_html.py` (its `SITE` constant sets the canonical URL), commit
`index.html` together with the source change, and push. `data/processed/` and
`data/source/` are committed so step 5 runs without re-downloading MIMU data.
