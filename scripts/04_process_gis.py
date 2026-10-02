"""
Clip, simplify and join the MIMU layers, and run the spatial analysis the
dashboard reports.

Area of interest: the four townships of Dawei District, where nearly all the
reporting is, plus Palaw and Tanintharyi townships of Myeik District, which the
27 Sep - 1 Oct posts also cover (the Dawei-Myeik road and the Tanintharyi River), and
Bokpyin Township of Kawthoung District (one 28 Sep post, from Lay Hnya).

The dashboard draws these vectors itself -- MIMU is the basemap -- so these files
are the map. Admin polygons are simplified to ~40 m and coordinates rounded to
4-5 decimal places, well inside the 1:250,000 source accuracy. Distances and areas
are measured in UTM 47N (EPSG:32647).

Analysis written to data/processed/analysis.json:
  townships   per township: MIMU villages, schools, hospitals, land below 5 m,
              mapped mining, and reported sites by day and severity
  near_sites  schools and hospitals within 1 km of a reported site
  reach       what lies on the Launglon peninsula beyond the rescue convoy's
              furthest point on 27 Sep (the Poe Zar Pin slide), 28 Sep (Auk
              Yay Phyu), 29 Sep (Taw Kye) and 30 Sep - 1 Oct (the Taw Kye-Tha Win slide); road access from Dawei runs down the
              peninsula past all three
"""

import json
import os
import warnings

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, MultiPolygon, Point, box
from shapely.ops import unary_union

warnings.filterwarnings("ignore", message="Geometry is in a geographic CRS")

HERE = os.path.dirname(__file__)
RAW = os.path.join(HERE, "..", "data", "raw")
OUT = os.path.join(HERE, "..", "data", "processed")

DAWEI_DT = "MMR006D001"
AOI_TS = ["Dawei", "Launglon", "Thayetchaung", "Yebyu", "Palaw", "Tanintharyi", "Bokpyin"]
DAYS = [26, 27, 28, 29, 30, 31, 32]  # 31 = 1 Oct, 32 = 2 Oct
UTM = 32647
VIEW = box(97.45, 10.25, 99.8, 15.45)   # map canvas; context outside it is dropped
TOL_ADM = 0.0004                        # ~40 m
TOL_CTX = 0.002
NEAR_M = 1000


def load(name):
    return gpd.read_file(os.path.join(RAW, name))


def round_coords(obj, p):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(float(v), p) for v in obj]
        return [round_coords(v, p) for v in obj]
    return obj


def dump(gdf, name, keep, prec=4):
    feats = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        g = geom.__geo_interface__
        g = {"type": g["type"], "coordinates": round_coords(g["coordinates"], prec)}
        props = {}
        for k in keep:
            v = row.get(k)
            if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
                continue
            if hasattr(v, "item"):
                v = v.item()
            if isinstance(v, float):
                v = round(v, 3)
            props[k] = v
        feats.append({"type": "Feature", "properties": props, "geometry": g})
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f,
                  ensure_ascii=False, separators=(",", ":"))
    print(f"  -> {name:26s} {len(feats):5,d} features  {os.path.getsize(path)/1024:8.1f} KB")


def km2(g):
    s = g if isinstance(g, gpd.GeoSeries) else gpd.GeoSeries([g], crs=4326)
    return float(s.to_crs(UTM).area.sum() / 1e6)


def main():
    flood = json.load(open(os.path.join(OUT, "flood.json"), encoding="utf-8"))
    sites = [s for s in flood["sites"] if s.get("lon") is not None]
    sg = gpd.GeoDataFrame(sites, geometry=[Point(s["lon"], s["lat"]) for s in sites], crs=4326)

    # ------------------------------------------------------------ admin
    print("admin")
    ts_all = load("adm3_townships.geojson")
    ts = ts_all[ts_all.TS.isin(AOI_TS) & (ts_all.ST == "Tanintharyi")].copy()
    aoi = unary_union(ts.geometry)
    near = aoi.buffer(0.03)
    district = unary_union(ts[ts.DT_PCODE == DAWEI_DT].geometry)

    a1 = load("adm1_states.geojson")
    myanmar = unary_union(a1.geometry)
    ctx = ts_all[~ts_all.TS_PCODE.isin(ts.TS_PCODE) & ts_all.intersects(VIEW)].copy()
    ctx["geometry"] = ctx.geometry.intersection(VIEW.buffer(0.2)).simplify(TOL_CTX, preserve_topology=True)
    dump(ctx, "context_townships.geojson", ["TS", "DT", "ST"])

    # Thailand = the canvas minus Myanmar, keeping the pieces that reach the east edge
    rest = VIEW.buffer(0.2).difference(myanmar)
    parts = list(rest.geoms) if hasattr(rest, "geoms") else [rest]
    east = VIEW.buffer(0.2).bounds[2]
    thai = [p for p in parts if p.bounds[2] >= east - 1e-6 and p.area > 0.01]
    thai_g = gpd.GeoDataFrame({"name": ["Thailand"]}, geometry=[unary_union(thai).simplify(TOL_CTX)], crs=4326)
    dump(thai_g, "thailand.geojson", ["name"])

    ts["area_km2"] = (ts.to_crs(UTM).area / 1e6).round(0)
    rp = ts.geometry.representative_point()
    ts["lx"], ts["ly"] = rp.x.round(4), rp.y.round(4)

    # ------------------------------------------------------------ village tracts, wards
    vt = load("adm4_vt_tanintharyi.geojson")
    vt = vt[vt.TS_PCODE.isin(ts.TS_PCODE)].copy()
    hits = gpd.sjoin(sg[["id", "geometry"]], vt[["VT_PCODE", "geometry"]], predicate="within")
    hit_vt = hits.groupby("VT_PCODE").id.apply(list).to_dict()
    first = {s["id"]: s["first_day"] for s in sites}
    vt["sites"] = vt.VT_PCODE.map(lambda p: len(hit_vt.get(p, [])))
    vt["day"] = vt.VT_PCODE.map(lambda p: min((first[i] for i in hit_vt.get(p, [])), default=0))
    vt["geometry"] = vt.geometry.simplify(TOL_ADM, preserve_topology=True)
    dump(vt, "village_tracts.geojson", ["VT", "VT_MMR", "VT_PCODE", "TS", "sites", "day"])

    wards = load("adm5_wards.geojson")
    wards = wards[wards.TS_PCODE.isin(ts.TS_PCODE)].copy()
    # Thayetchaung: the official figure is five town wards flooded 6-8 ft, and MIMU maps
    # exactly five wards there, so the figure covers the whole town (27 Sep).
    # Dawei: wards named in the 27-30 Sep posts. Tanintharyi: the two town wards named on 2 Oct.
    ward_day = {}
    for w in wards[wards.TOWN == "Thayetchaung Town"].WARD_PCODE:
        ward_day[w] = 27
    for s in flood["sites"]:
        if s.get("pcode", "").startswith("MMR006") and s["area"] in ("Dawei town", "Tanintharyi") and "ward" in s["id"]:
            ward_day[s["pcode"]] = s["first_day"]
    wards["day"] = wards.WARD_PCODE.map(lambda p: ward_day.get(p, 0))
    wards["geometry"] = wards.geometry.simplify(0.0001, preserve_topology=True)
    dump(wards, "wards.geojson", ["WARD", "WARD_MMR", "TOWN", "TS", "day"], prec=5)

    # ------------------------------------------------------------ villages, towns
    print("villages")
    vp = load("village_points_tni.geojson")
    vp = vp[vp.TS_PCODE.isin(ts.TS_PCODE)].copy()
    rep_pc = {s.get("pcode") for s in sites}
    vp["rep"] = vp.VLG_PCODE.astype(str).isin(rep_pc).astype(int)
    dump(vp, "villages.geojson", ["VILLAGE", "VLG_MMR", "TS", "VT", "rep"], prec=5)

    towns = load("town_points.geojson")
    towns = towns[towns.intersects(VIEW)]
    dump(towns, "towns.geojson", ["Town", "Town_MMR4", "Township", "Level"], prec=5)

    # ------------------------------------------------------------ infrastructure
    print("infrastructure")
    rd = load("roads.geojson")
    rd = rd[rd.intersects(VIEW)].copy()
    rd["geometry"] = rd.geometry.intersection(VIEW).simplify(0.0003, preserve_topology=True)
    dump(rd, "roads.geojson", ["Road_Type"])

    rl = load("railways.geojson")
    rl["geometry"] = rl.geometry.intersection(VIEW).simplify(0.0003)
    dump(rl, "railway.geojson", ["Div_Name", "Track"])

    br = load("bridges.geojson")
    br = br[br.within(near)].copy()
    dump(br, "bridges.geojson", ["nmEng", "nmMya", "length_ft", "nmTsEng"], prec=5)

    hs = load("health_facilities.geojson")
    hs = hs[hs.TS_PCODE.isin(ts.TS_PCODE)].copy()
    dump(hs, "hospitals.geojson", ["nmHsp_eng", "nmHsp_mya", "lvlHsp_eng", "bedClass", "TS_en"], prec=5)

    sc = load("schools_lower.geojson")
    sc = sc[sc.mm_tscode.isin(ts.TS_PCODE)].copy()
    sc["geometry"] = sc.geometry.apply(lambda g: g.geoms[0] if g.geom_type == "MultiPoint" else g)
    dump(sc, "schools.geojson", ["schoolname", "urbanrural", "mm_tsname"], prec=5)

    sez = load("sez_polygons.geojson")
    sez = sez[sez.intersects(near)]
    dump(sez, "sez.geojson", ["nmEng", "nmMya", "zoneType"])

    # ------------------------------------------------------------ hydrography, terrain
    print("hydrography and land")
    rv = load("rivers_detail.geojson")
    rv = rv[rv.intersects(VIEW)].copy()
    rv["name"] = rv.NAME.replace({"TAVOY": "Dawei River", "GREAT TENASSERIM": "Tanintharyi River",
                                  "LENYA": "Lenya River", "INDAW LAKE": "", "UNK": ""})
    rv["geometry"] = rv.geometry.simplify(0.0003, preserve_topology=True)
    dump(rv, "rivers.geojson", ["name"])

    rvl = load("rivers_250k.geojson")
    rvl["geometry"] = rvl.geometry.intersection(VIEW).simplify(0.0005)
    dump(rvl, "river_lines.geojson", ["Name"])

    lo = load("below5m.geojson")
    lo_d = unary_union(lo.geometry.buffer(0)).intersection(aoi)
    dump(gpd.GeoDataFrame(geometry=[lo_d.simplify(0.0004)], crs=4326), "lowland.geojson", [])

    mn = load("mining_areas.geojson")
    mn = mn[mn.intersects(near)].copy()
    mn["Mineral1"] = mn.Mineral1.replace("", None)
    dump(mn, "mining.geojson", ["Township", "Notes", "Mineral1", "Area_hect", "Certainty", "ImageYear1"])

    # ------------------------------------------------------------ township analysis
    print("analysis")
    by_ts = {}
    for _, t in ts.iterrows():
        g = t.geometry
        lo_ts = lo_d.intersection(g)
        rep = [s for s in flood["sites"] if s["ts"] == t.TS]
        mine_in = mn[mn.within(g.buffer(0.001))]
        by_ts[t.TS] = dict(
            ts=t.TS, ts_mm=t.TS_MMR, pcode=t.TS_PCODE, district=t.DT, area_km2=int(t.area_km2),
            villages=int((vp.TS_PCODE == t.TS_PCODE).sum()),
            village_tracts=int((vt.TS_PCODE == t.TS_PCODE).sum()),
            schools=int((sc.mm_tscode == t.TS_PCODE).sum()),
            hospitals=int((hs.TS_PCODE == t.TS_PCODE).sum()),
            hospital_beds=int(pd.to_numeric(hs[hs.TS_PCODE == t.TS_PCODE].bedClass, errors="coerce").sum()),
            lowland_km2=round(km2(lo_ts), 1),
            lowland_pct=round(100 * km2(lo_ts) / km2(g), 1),
            mining_sites=len(mine_in), mining_ha=round(float(mine_in.Area_hect.sum()), 0),
            reported_sites=len(rep),
            by_day={str(d): dict(
                sites=sum(1 for s in rep if s["state"][str(d)]),
                fatal=sum(1 for s in rep if s["state"][str(d)] and s["state"][str(d)]["sev"] == "fatal"),
                severe=sum(1 for s in rep if s["state"][str(d)] and s["state"][str(d)]["sev"] == "severe"),
                new=sum(1 for s in rep if s["first_day"] == d),
            ) for d in DAYS},
            vt_hit=int((vt[vt.TS_PCODE == t.TS_PCODE].sites > 0).sum()),
        )
    ts["sites"] = ts.TS.map(lambda n: by_ts[n]["reported_sites"])
    ts["geometry"] = ts.geometry.simplify(TOL_ADM, preserve_topology=True)
    dump(ts, "townships.geojson", ["TS", "TS_MMR", "TS_PCODE", "DT", "area_km2", "lx", "ly", "sites"])
    dump(gpd.GeoDataFrame({"DT": ["Dawei"]}, geometry=[district.simplify(TOL_ADM)], crs=4326),
         "district.geojson", ["DT"])

    # ------------------------------------------------------------ facilities near sites
    sgu = sg[~sg.roles.map(lambda r: "observe" in r)].to_crs(UTM)
    near_rows = []
    for layer, name_col, kind in ((sc, "schoolname", "school"), (hs, "nmHsp_eng", "hospital")):
        lu = layer.to_crs(UTM)
        for idx, f in lu.iterrows():
            d = sgu.distance(f.geometry)
            i = d.idxmin()
            if d[i] <= NEAR_M:
                near_rows.append(dict(kind=kind, name=f[name_col], site=sgu.loc[i, "id"],
                                      site_en=sgu.loc[i, "en"], sev=sgu.loc[i, "sev"],
                                      dist_m=int(round(d[i])),
                                      lon=round(layer.loc[idx].geometry.x, 5),
                                      lat=round(layer.loc[idx].geometry.y, 5)))
    near_rows.sort(key=lambda r: (r["kind"], r["dist_m"]))

    # ------------------------------------------------------------ beyond the rescue's reach
    lg_full = ts_all[ts_all.TS == "Launglon"].geometry.iloc[0]
    parts = list(lg_full.geoms) if isinstance(lg_full, MultiPolygon) else [lg_full]
    mainland = max(parts, key=lambda p: p.area)
    by_id = {s["id"]: s for s in flood["sites"]}
    inc = {i["id"]: i for i in flood["incidents"]}
    reach = {}
    for day, key, label in ((27, "poe-zar-pin", "Poe Zar Pin slide"), (28, "auk-yay-phyu", "Auk Yay Phyu"),
                            (29, "taw-kye", "Taw Kye"), (30, "tha-win-road", "the Taw Kye–Tha Win slide"),
                            (31, "tha-win-road", "the Taw Kye–Tha Win slide"),
                            (32, "tha-win-road", "the Taw Kye–Tha Win slide")):
        p = inc.get(key) or by_id[key]
        south = mainland.intersection(box(97, 0, 100, p["lat"] - 0.002))
        v_s = vp[vp.within(south)]
        s_s, h_s = sc[sc.within(south)], hs[hs.within(south)]
        rep_s = [s for s in sites if s["ts"] == "Launglon" and s["state"][str(day)]
                 and south.contains(Point(s["lon"], s["lat"]))]
        reach[str(day)] = dict(
            limit=label, lat=p["lat"], lon=p["lon"],
            villages=len(v_s), village_tracts=int(vt[vt.representative_point().within(south)].shape[0]),
            schools=len(s_s), hospitals=len(h_s), hospital_names=h_s.nmHsp_eng.tolist(),
            reported_sites=len(rep_s), reported_ids=[s["id"] for s in rep_s],
            fatal=sum(1 for s in rep_s if s["state"][str(day)]["sev"] == "fatal"),
            red=sum(1 for s in rep_s if s["state"][str(day)]["red"]),
            area_km2=round(km2(south), 0),
        )
        dump(gpd.GeoDataFrame(geometry=[south.simplify(TOL_ADM)], crs=4326), f"beyond_{day}.geojson", [])
    reach["launglon_villages"] = by_ts["Launglon"]["villages"]
    reach["launglon_schools"] = by_ts["Launglon"]["schools"]

    # rescue route: schematic straight legs between the convoy's stops, split by day. A
    # stop with `frm_pt` starts its leg there (a later push along an earlier stretch).
    legs = []
    stops = flood["rescue"]
    for a, b in zip(stops, stops[1:]):
        start = b.get("frm_pt") or [a["lon"], a["lat"]]
        legs.append(dict(day=b["day"], mode=b["mode"], coords=[start, [b["lon"], b["lat"]]]))
    route_km = float(gpd.GeoSeries([LineString(l["coords"]) for l in legs], crs=4326).to_crs(UTM).length.sum() / 1000)

    aoi_tot = dict(
        villages=len(vp), village_tracts=len(vt), schools=len(sc), hospitals=len(hs),
        area_km2=int(round(km2(aoi))), lowland_km2=round(km2(lo_d), 0),
        mining_sites=int(len(mn[mn.within(aoi.buffer(0.001))])),
        mining_ha=round(float(mn[mn.within(aoi.buffer(0.001))].Area_hect.sum()), 0),
        district_villages=int((vp.DT_PCODE == DAWEI_DT).sum()),
        district_schools=int((sc.mm_dtcode == DAWEI_DT).sum()),
        district_hospitals=int((hs.DT_PCODE == DAWEI_DT).sum()),
    )
    analysis = dict(townships=by_ts, aoi=aoi_tot, near_sites=near_rows, near_m=NEAR_M, reach=reach,
                    route=dict(legs=legs, straight_km=round(route_km, 1)), ts_order=AOI_TS)
    with open(os.path.join(OUT, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=1)

    print("\nTownships:")
    for t in by_ts.values():
        print("  ", {k: t[k] for k in ("ts", "villages", "schools", "hospitals", "lowland_pct", "mining_ha",
                                       "reported_sites", "vt_hit")}, t["by_day"][str(DAYS[-1])])
    print("AOI:", aoi_tot)
    print(f"Near sites (<= {NEAR_M} m): {sum(r['kind']=='school' for r in near_rows)} schools, "
          f"{sum(r['kind']=='hospital' for r in near_rows)} hospitals")
    for d in ("27", "28", "29", "30", "31", "32"):
        print(f"Beyond reach day {d}:", {k: v for k, v in reach[d].items() if k != "reported_ids"})


if __name__ == "__main__":
    main()
