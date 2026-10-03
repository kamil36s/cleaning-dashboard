# Santiago route geometry QA

## Audit result

- Total route distance: **4294.18 km**
- Consecutive checkpoint straight-line sum: **3314.56 km**
- Aggregate routed/straight ratio: **1.296**
- Kraków → Saint-Jean-Pied-de-Port: **3366.75 km**
- Saint-Jean-Pied-de-Port → Santiago: **927.43 km**
- Main-route / variant checkpoints: **361 / 4**
- Suspicious legs: **48**
- Highly suspicious legs: **5**
- Fallback legs: **0**
- Road-tag verified flagged legs: **25**
- Motorway/ferry flags: **0 / 0**

The automatic flags are review prompts, not proof of error. Mountain passes, river crossings and road-only
cycling alternatives can legitimately exceed the straight-line threshold.

**Conclusion:** the relaxed order rule removes strong-confidence branch mixing and geographic loops while
preserving every checkpoint identity. Four alternative-route localities remain in the dataset as explicit
variant checkpoints and no longer force the main route to travel both mutually exclusive branches.

## Before / after

- Before order audit: **4409.19 km**
- After: **4294.18 km**
- Ordering reduction: **115.01 km**
- Cross-leg retrace sum: **277.41 → 162.84 km**
- Automatic ordering flags: **60 → 56**
- Earlier coordinate corrections retained: **1**

## Distance by country

Legs are attributed to the country of their starting checkpoint; border legs therefore belong to the
origin country.

| Country | Distance |
| --- | ---: |
| Poland | 185.66 km |
| Czechia | 339.26 km |
| Austria | 960.63 km |
| Liechtenstein | 43.35 km |
| Switzerland | 355.02 km |
| France | 1505.32 km |
| Spain | 904.93 km |

## Corrections

### Checkpoint #84: St. Anton am Arlberg

The Wikipedia municipality coordinate was on the ski slope south of the settlement and forced BRouter away from the paved Arlberg road corridor. The replacement is the geocoded official town-hall address in the settlement center.

Affected cache: `070-093.geojson`

| Leg | Before | After | Difference |
| --- | ---: | ---: | ---: |
| #83 → #84 | 34.474 km | 27.975 km | -6.499 km |
| #84 → #85 | 13.818 km | 6.020 km | -7.798 km |
| #85 → #86 | 4.631 km | 4.620 km | -0.011 km |

Evidence:
- [Land Tirol lists the municipal address as Dorfstraße 46, 6580 St. Anton am Arlberg.](https://www.tirol.gv.at/gemeinden/gemeinde/70621/)
- [The official destination site describes road-cycling tours from St. Anton west over Arlberg.](https://www.stantonamarlberg.com/en/summer/road-biking)
- BRouter trekking comparison: 14.444 km from the old point to Arlberg Pass versus 6.249 km from the corrected town point.

Correction total: **-14.308 km**


## Broad corridor

Poland → Czechia → Austria → Liechtenstein → Switzerland → France → Spain

The checkpoint and snapped-route order is monotonic. The expected corridor is Kraków through Czechia,
Austria, Liechtenstein, Switzerland and France to Saint-Jean-Pied-de-Port, then the Camino Francés
localities across Spain to Santiago.

## Geometry integrity

- Route vertices: 13024
- Repeated coordinates: 323
- Consecutive repeated coordinates: 0
- Retrace-loop groups over 0.5 km: 56
- Monotonic checkpoint vertex indexes: true
- Route start offset: 0.009 km
- Route end offset: 0.000 km
- The compact route-part cache contains geometry only. `route-road-tags.json` therefore records a
  separate BRouter `trekking` verification for every leg flagged for ratio, length, intersection,
  fallback, backtracking, corridor deviation or border detour.

### Cross-leg retracing

| Checkpoint span | Maximum closed loop | Repeated coordinate pairs |
| --- | ---: | ---: |
| #38 Traismauer → #39 Krems an der Donau | 25.44 km | 41 |
| #3 Kalwaria Zebrzydowska → #4 Zator | 10.13 km | 23 |
| #156 Nevers → #157 La Charité-sur-Loire | 9.83 km | 7 |
| #302 Pereje → #304 Trabadelo | 9.09 km | 10 |
| #4 Zator → #5 Wadowice | 7.48 km | 4 |
| #131 Thann → #132 Masevaux-Niederbruck | 7.07 km | 12 |
| #311 Laguna de Castilla → #312 O Cebreiro | 7.07 km | 16 |
| #33 Wolkersdorf im Weinviertel → #34 Vienna | 6.67 km | 4 |
| #80 Mötz → #81 Imst | 6.64 km | 6 |
| #9 Jaworze → #10 Jasienica | 4.47 km | 3 |
| #101 Sargans → #102 Flums | 3.97 km | 2 |
| #67 Saalfelden → #68 Leogang | 3.80 km | 8 |
| #319 Triacastela → #320 A Balsa | 3.59 km | 7 |
| #65 Taxenbach → #66 Zell am See | 3.57 km | 6 |
| #266 Calzada del Coto → #267 Bercianos del Real Camino | 3.57 km | 4 |
| #318 Fillobal → #319 Triacastela | 3.21 km | 4 |
| #320 A Balsa → #321 San Cristovo do Real (Lusio) | 2.60 km | 5 |
| #253 Itero de la Vega → #254 Boadilla del Camino | 2.60 km | 4 |
| #238 Villafranca Montes de Oca → #239 San Juan de Ortega | 2.26 km | 2 |
| #26 Brno → #27 Rajhrad | 2.18 km | 3 |
| #136 L'Isle-sur-le-Doubs → #137 Baume-les-Dames | 2.09 km | 3 |
| #234 Belorado → #235 Tosantos | 1.82 km | 3 |
| #87 Klösterle → #88 Bludenz | 1.77 km | 6 |
| #18 Nový Jičín → #19 Hranice (Přerov District) | 1.67 km | 2 |
| #246 Rabé de las Calzadas → #247 Hornillos del Camino | 1.53 km | 1 |
| #125 Laufen, Switzerland → #126 Aesch, Basel-Landschaft | 1.50 km | 2 |
| #215 Azqueta → #216 Villamayor de Monjardín | 1.49 km | 2 |
| #321 San Cristovo do Real (Lusio) → #322 Samos | 1.41 km | 3 |
| #2 Skawina → #3 Kalwaria Zebrzydowska | 1.32 km | 2 |
| #42 Loosdorf → #43 Melk | 1.25 km | 2 |
| #74 Rattenberg, Austria → #75 Jenbach | 1.22 km | 1 |
| #199 Huarte → #200 Trinidad de Arre / Villava | 1.17 km | 2 |
| #294 Riego de Ambrós → #295 Molinaseca | 1.10 km | 2 |
| #305 La Portela de Valcarce → #306 Ambasmestas | 1.09 km | 1 |
| #312 O Cebreiro → #313 Linares | 1.06 km | 2 |
| #297 Columbrianos → #298 Camponaraya | 1.05 km | 1 |
| #323 Calvor → #324 San Mamede do Camino | 1.02 km | 1 |
| #245 Tardajos → #246 Rabé de las Calzadas | 0.99 km | 1 |
| #358 A Rua → #359 Pedrouze / Arca | 0.98 km | 1 |
| #258 Villacázar de Sirga → #259 Carrión de los Condes | 0.90 km | 2 |
| #263 Moratinos → #264 San Nicolás del Real Camino | 0.89 km | 1 |
| #243 Orbaneja Riopico → #244 Burgos | 0.88 km | 1 |
| #82 Zams → #83 Landeck | 0.86 km | 2 |
| #235 Tosantos → #236 Villambistia | 0.83 km | 1 |
| #184 Hontto → #185 Orisson | 0.82 km | 2 |
| #109 Rapperswil-Jona → #110 Pfäffikon, Schwyz | 0.81 km | 1 |
| #230 Redecilla del Camino → #231 Castildelgado | 0.79 km | 1 |
| #27 Rajhrad → #28 Židlochovice | 0.74 km | 1 |
| #247 Hornillos del Camino → #248 San Bol | 0.64 km | 1 |
| #121 Solothurn → #122 Grenchen | 0.62 km | 1 |
| #50 Wels → #51 Lambach | 0.61 km | 1 |
| #43 Melk → #44 Pöchlarn | 0.60 km | 1 |
| #34 Vienna → #35 Klosterneuburg | 0.56 km | 1 |
| #260 Calzadilla de la Cueza → #261 Ledigos | 0.51 km | 1 |
| #46 Amstetten → #47 Enns | 0.51 km | 1 |
| #40 Herzogenburg → #41 Sankt Pölten | 0.51 km | 1 |

The removed Bidache/Orthez, Valcarlos, Via Trajana, Rhine-valley, and Samos ordering loops no longer
dominate this table. Remaining entries are retained because the order evidence is ambiguous or the
geometry can be explained by the legal cycling network, river crossings, or mountain roads.

## Suspicious legs by potential impact

### #123 → #124: Biel/Bienne → Delémont

- Route: 51.64 km
- Straight line: 27.02 km
- Detour ratio: 1.91
- Excess over straight line: 24.62 km
- Vertices: 191
- Source: BRouter trekking (`116-139.geojson`)
- Flags: detour ratio > 1.8, proper self-intersection
- Geometry: max corridor deviation 7.31 km; projected reverse travel 3.06 km; max closed loop 0.00 km; self-intersections 2

Recommendation: Inspect the cached line on the QA map before treating the excess as a routing error.

### #131 → #132: Thann → Masevaux-Niederbruck

- Route: 18.27 km
- Straight line: 7.65 km
- Detour ratio: 2.39
- Excess over straight line: 10.63 km
- Vertices: 62
- Source: BRouter trekking (`116-139.geojson`)
- Flags: detour ratio > 1.8
- Geometry: max corridor deviation 5.50 km; projected reverse travel 2.09 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Inspect the cached line on the QA map before treating the excess as a routing error.

### #158 → #159: Bourges → Châteauroux

- Route: 72.90 km
- Straight line: 61.30 km
- Detour ratio: 1.19
- Excess over straight line: 11.60 km
- Vertices: 103
- Source: BRouter trekking (`139-162.geojson`)
- Flags: individual leg > 60 km
- Geometry: max corridor deviation 8.54 km; projected reverse travel 0.10 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Inspect the cached line on the QA map before treating the excess as a routing error.

### #157 → #158: La Charité-sur-Loire → Bourges

- Route: 60.66 km
- Straight line: 48.45 km
- Detour ratio: 1.25
- Excess over straight line: 12.22 km
- Vertices: 121
- Source: BRouter trekking (`139-162.geojson`)
- Flags: individual leg > 60 km
- Geometry: max corridor deviation 4.54 km; projected reverse travel 0.07 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Inspect the cached line on the QA map before treating the excess as a routing error.

### #322 → #323: Samos → Calvor

- Route: 13.75 km
- Straight line: 5.30 km
- Detour ratio: 2.60
- Excess over straight line: 8.45 km
- Vertices: 60
- Source: BRouter trekking (`300-323.geojson`)
- Flags: detour ratio > 1.8, detour ratio > 2.5, repeated coordinates
- Geometry: max corridor deviation 3.85 km; projected reverse travel 0.65 km; max closed loop 0.73 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #174 → #175: Mont-de-Marsan → Tartas

- Route: 32.77 km
- Straight line: 25.44 km
- Detour ratio: 1.29
- Excess over straight line: 7.33 km
- Vertices: 113
- Source: BRouter trekking (`162-185.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 2.86 km; projected reverse travel 0.39 km; max closed loop 0.08 km; self-intersections 0

Recommendation: Inspect the cached line on the QA map before treating the excess as a routing error.

### #321 → #322: San Cristovo do Real (Lusio) → Samos

- Route: 12.73 km
- Straight line: 5.95 km
- Detour ratio: 2.14
- Excess over straight line: 6.78 km
- Vertices: 62
- Source: BRouter trekking (`300-323.geojson`)
- Flags: detour ratio > 1.8
- Geometry: max corridor deviation 1.00 km; projected reverse travel 1.35 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #190 → #191: Espinal → Biskarreta

- Route: 9.20 km
- Straight line: 4.14 km
- Detour ratio: 2.22
- Excess over straight line: 5.06 km
- Vertices: 45
- Source: BRouter trekking (`185-208.geojson`)
- Flags: detour ratio > 1.8
- Geometry: max corridor deviation 2.32 km; projected reverse travel 0.83 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Pyrenees/Camino variant leg: inspect against both Route Napoléon and Valcarlos alternatives.

### #203 → #204: Zariquiegui → Uterga

- Route: 10.46 km
- Straight line: 5.77 km
- Detour ratio: 1.81
- Excess over straight line: 4.69 km
- Vertices: 42
- Source: BRouter trekking (`185-208.geojson`)
- Flags: detour ratio > 1.8
- Geometry: max corridor deviation 2.88 km; projected reverse travel 0.78 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #241 → #242: Atapuerca → Cardeñuela de Ríopico

- Route: 9.70 km
- Straight line: 4.72 km
- Detour ratio: 2.05
- Excess over straight line: 4.98 km
- Vertices: 39
- Source: BRouter trekking (`231-254.geojson`)
- Flags: detour ratio > 1.8
- Geometry: max corridor deviation 2.80 km; projected reverse travel 0.45 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #24 → #25: Rousínov → Slavkov u Brna

- Route: 9.92 km
- Straight line: 5.38 km
- Detour ratio: 1.84
- Excess over straight line: 4.54 km
- Vertices: 29
- Source: BRouter trekking (`024-047.geojson`)
- Flags: detour ratio > 1.8
- Geometry: max corridor deviation 3.18 km; projected reverse travel 0.20 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Inspect the cached line on the QA map before treating the excess as a routing error.

### #102 → #103: Flums → Walenstadt

- Route: 7.48 km
- Straight line: 3.92 km
- Detour ratio: 1.91
- Excess over straight line: 3.56 km
- Vertices: 28
- Source: BRouter trekking (`093-116.geojson`)
- Flags: detour ratio > 1.8
- Geometry: max corridor deviation 1.40 km; projected reverse travel 1.11 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Inspect the cached line on the QA map before treating the excess as a routing error.

### #302 → #303: Pereje → Pradela

- Route: 8.10 km
- Straight line: 4.25 km
- Detour ratio: 1.90
- Excess over straight line: 3.85 km
- Vertices: 37
- Source: BRouter trekking (`277-300.geojson`)
- Flags: detour ratio > 1.8
- Geometry: max corridor deviation 2.01 km; projected reverse travel 0.67 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #320 → #321: A Balsa → San Cristovo do Real (Lusio)

- Route: 7.28 km
- Straight line: 3.45 km
- Detour ratio: 2.11
- Excess over straight line: 3.83 km
- Vertices: 33
- Source: BRouter trekking (`300-323.geojson`)
- Flags: detour ratio > 1.8
- Geometry: max corridor deviation 1.49 km; projected reverse travel 0.74 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #318 → #319: Fillobal → Triacastela

- Route: 5.48 km
- Straight line: 2.16 km
- Detour ratio: 2.53
- Excess over straight line: 3.32 km
- Vertices: 27
- Source: BRouter trekking (`300-323.geojson`)
- Flags: detour ratio > 1.8, detour ratio > 2.5
- Geometry: max corridor deviation 1.16 km; projected reverse travel 0.82 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #68 → #69: Leogang → Hochfilzen

- Route: 14.85 km
- Straight line: 11.24 km
- Detour ratio: 1.32
- Excess over straight line: 3.61 km
- Vertices: 63
- Source: BRouter trekking (`047-070.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 1.57 km; projected reverse travel 0.35 km; max closed loop 0.75 km; self-intersections 0

Recommendation: Alpine leg: elevation, valleys, tunnels and legal cycling crossings can justify a high ratio.

### #311 → #312: Laguna de Castilla → O Cebreiro

- Route: 6.25 km
- Straight line: 2.79 km
- Detour ratio: 2.24
- Excess over straight line: 3.46 km
- Vertices: 29
- Source: BRouter trekking (`300-323.geojson`)
- Flags: detour ratio > 1.8
- Geometry: max corridor deviation 1.34 km; projected reverse travel 0.40 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #303 → #304: Pradela → Trabadelo

- Route: 5.22 km
- Straight line: 1.90 km
- Detour ratio: 2.75
- Excess over straight line: 3.32 km
- Vertices: 32
- Source: BRouter trekking (`277-300.geojson`)
- Flags: detour ratio > 1.8, detour ratio > 2.5
- Geometry: max corridor deviation 0.58 km; projected reverse travel 0.56 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #294 → #295: Riego de Ambrós → Molinaseca

- Route: 6.36 km
- Straight line: 3.26 km
- Detour ratio: 1.96
- Excess over straight line: 3.11 km
- Vertices: 35
- Source: BRouter trekking (`277-300.geojson`)
- Flags: detour ratio > 1.8
- Geometry: max corridor deviation 0.73 km; projected reverse travel 0.58 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #186 → #187: Lepoeder Peak → Roncesvalles

- Route: 5.45 km
- Straight line: 2.75 km
- Detour ratio: 1.98
- Excess over straight line: 2.70 km
- Vertices: 35
- Source: BRouter trekking (`162-185.geojson`)
- Flags: detour ratio > 1.8
- Geometry: max corridor deviation 1.10 km; projected reverse travel 0.28 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Pyrenees/Camino variant leg: inspect against both Route Napoléon and Valcarlos alternatives.

### #34 → #35: Vienna → Klosterneuburg

- Route: 13.82 km
- Straight line: 11.43 km
- Detour ratio: 1.21
- Excess over straight line: 2.39 km
- Vertices: 40
- Source: BRouter trekking (`024-047.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 1.86 km; projected reverse travel 0.33 km; max closed loop 0.06 km; self-intersections 0

Recommendation: Inspect the cached line on the QA map before treating the excess as a routing error.

### #211 → #212: Villatuerta → Estella

- Route: 4.91 km
- Straight line: 2.37 km
- Detour ratio: 2.07
- Excess over straight line: 2.54 km
- Vertices: 21
- Source: BRouter trekking (`208-231.geojson`)
- Flags: detour ratio > 1.8
- Geometry: max corridor deviation 0.58 km; projected reverse travel 0.34 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #184 → #185: Hontto → Orisson

- Route: 5.64 km
- Straight line: 3.63 km
- Detour ratio: 1.55
- Excess over straight line: 2.01 km
- Vertices: 24
- Source: BRouter trekking (`162-185.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 0.47 km; projected reverse travel 0.47 km; max closed loop 0.09 km; self-intersections 0

Recommendation: Inspect the cached line on the QA map before treating the excess as a routing error.

### #89 → #90: Nenzing → Feldkirch, Vorarlberg

- Route: 11.90 km
- Straight line: 9.78 km
- Detour ratio: 1.22
- Excess over straight line: 2.12 km
- Vertices: 40
- Source: BRouter trekking (`070-093.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 0.68 km; projected reverse travel 0.21 km; max closed loop 0.09 km; self-intersections 0

Recommendation: Alpine leg: elevation, valleys, tunnels and legal cycling crossings can justify a high ratio.

### #292 → #293: Manjarín → El Acebo

- Route: 7.28 km
- Straight line: 5.31 km
- Detour ratio: 1.37
- Excess over straight line: 1.97 km
- Vertices: 31
- Source: BRouter trekking (`277-300.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 1.03 km; projected reverse travel 0.20 km; max closed loop 0.40 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #48 → #49: Linz → Traun

- Route: 11.86 km
- Straight line: 9.98 km
- Detour ratio: 1.19
- Excess over straight line: 1.88 km
- Vertices: 36
- Source: BRouter trekking (`047-070.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 1.12 km; projected reverse travel 0.08 km; max closed loop 0.06 km; self-intersections 0

Recommendation: Inspect the cached line on the QA map before treating the excess as a routing error.

### #215 → #216: Azqueta → Villamayor de Monjardín

- Route: 2.79 km
- Straight line: 1.09 km
- Detour ratio: 2.55
- Excess over straight line: 1.69 km
- Vertices: 11
- Source: BRouter trekking (`208-231.geojson`)
- Flags: detour ratio > 1.8, detour ratio > 2.5
- Geometry: max corridor deviation 0.88 km; projected reverse travel 0.28 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #58 → #59: Salzburg → Hallein

- Route: 15.25 km
- Straight line: 13.57 km
- Detour ratio: 1.12
- Excess over straight line: 1.68 km
- Vertices: 29
- Source: BRouter trekking (`047-070.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 1.64 km; projected reverse travel 0.08 km; max closed loop 0.09 km; self-intersections 0

Recommendation: Inspect the cached line on the QA map before treating the excess as a routing error.

### #114 → #115: Dietikon → Baden, Switzerland

- Route: 12.38 km
- Straight line: 10.56 km
- Detour ratio: 1.17
- Excess over straight line: 1.82 km
- Vertices: 41
- Source: BRouter trekking (`093-116.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 0.44 km; projected reverse travel 0.21 km; max closed loop 0.06 km; self-intersections 0

Recommendation: Inspect the cached line on the QA map before treating the excess as a routing error.

### #200 → #201: Trinidad de Arre / Villava → Pamplona

- Route: 6.08 km
- Straight line: 4.34 km
- Detour ratio: 1.40
- Excess over straight line: 1.74 km
- Vertices: 28
- Source: BRouter trekking (`185-208.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 1.11 km; projected reverse travel 0.10 km; max closed loop 0.07 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #163 → #164: Limoges → Aixe-sur-Vienne

- Route: 12.22 km
- Straight line: 10.68 km
- Detour ratio: 1.14
- Excess over straight line: 1.53 km
- Vertices: 44
- Source: BRouter trekking (`162-185.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 1.89 km; projected reverse travel 0.09 km; max closed loop 0.07 km; self-intersections 0

Recommendation: Inspect the cached line on the QA map before treating the excess as a routing error.

### #212 → #213: Estella → Ayegui

- Route: 3.07 km
- Straight line: 1.49 km
- Detour ratio: 2.06
- Excess over straight line: 1.58 km
- Vertices: 16
- Source: BRouter trekking (`208-231.geojson`)
- Flags: detour ratio > 1.8
- Geometry: max corridor deviation 0.94 km; projected reverse travel 0.18 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #205 → #206: Muruzábal → Obanos

- Route: 2.93 km
- Straight line: 1.36 km
- Detour ratio: 2.15
- Excess over straight line: 1.57 km
- Vertices: 9
- Source: BRouter trekking (`185-208.geojson`)
- Flags: detour ratio > 1.8
- Geometry: max corridor deviation 0.78 km; projected reverse travel 0.21 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #331 → #332: Vilachá → Portomarin

- Route: 3.15 km
- Straight line: 1.67 km
- Detour ratio: 1.89
- Excess over straight line: 1.48 km
- Vertices: 16
- Source: BRouter trekking (`323-346.geojson`)
- Flags: detour ratio > 1.8
- Geometry: max corridor deviation 0.89 km; projected reverse travel 0.01 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #193 → #194: Zubiri → Urdániz

- Route: 3.88 km
- Straight line: 2.62 km
- Detour ratio: 1.48
- Excess over straight line: 1.26 km
- Vertices: 24
- Source: BRouter trekking (`185-208.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 0.61 km; projected reverse travel 0.29 km; max closed loop 0.06 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #263 → #264: Moratinos → San Nicolás del Real Camino

- Route: 3.15 km
- Straight line: 2.04 km
- Detour ratio: 1.55
- Excess over straight line: 1.11 km
- Vertices: 9
- Source: BRouter trekking (`254-277.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 0.48 km; projected reverse travel 0.46 km; max closed loop 0.07 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #306 → #307: Ambasmestas → Vega de Valcarce

- Route: 1.50 km
- Straight line: 0.41 km
- Detour ratio: 3.63
- Excess over straight line: 1.08 km
- Vertices: 11
- Source: BRouter trekking (`300-323.geojson`)
- Flags: detour ratio > 1.8, detour ratio > 2.5, repeated coordinates
- Geometry: max corridor deviation 0.49 km; projected reverse travel 0.26 km; max closed loop 0.06 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #127 → #128: Basel → Saint-Louis, Haut-Rhin

- Route: 5.40 km
- Straight line: 4.21 km
- Detour ratio: 1.28
- Excess over straight line: 1.19 km
- Vertices: 19
- Source: BRouter trekking (`116-139.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 0.43 km; projected reverse travel 0.10 km; max closed loop 0.10 km; self-intersections 0

Recommendation: Inspect the cached line on the QA map before treating the excess as a routing error.

### #225 → #226: Nájera → Azofra

- Route: 6.89 km
- Straight line: 5.84 km
- Detour ratio: 1.18
- Excess over straight line: 1.04 km
- Vertices: 20
- Source: BRouter trekking (`208-231.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 0.83 km; projected reverse travel 0.13 km; max closed loop 0.33 km; self-intersections 3

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #260 → #261: Calzadilla de la Cueza → Ledigos

- Route: 6.69 km
- Straight line: 5.66 km
- Detour ratio: 1.18
- Excess over straight line: 1.03 km
- Vertices: 16
- Source: BRouter trekking (`254-277.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 0.37 km; projected reverse travel 0.18 km; max closed loop 0.09 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #344 → #345: Pontecampaña → Casanova

- Route: 2.04 km
- Straight line: 1.06 km
- Detour ratio: 1.92
- Excess over straight line: 0.98 km
- Vertices: 8
- Source: BRouter trekking (`323-346.geojson`)
- Flags: detour ratio > 1.8
- Geometry: max corridor deviation 0.67 km; projected reverse travel 0.13 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #119 → #120: Egerkingen → Oensingen

- Route: 8.34 km
- Straight line: 7.30 km
- Detour ratio: 1.14
- Excess over straight line: 1.05 km
- Vertices: 21
- Source: BRouter trekking (`116-139.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 0.44 km; projected reverse travel 0.05 km; max closed loop 0.10 km; self-intersections 0

Recommendation: Inspect the cached line on the QA map before treating the excess as a routing error.

### #248 → #249: San Bol → Hontanas

- Route: 4.28 km
- Straight line: 3.63 km
- Detour ratio: 1.18
- Excess over straight line: 0.65 km
- Vertices: 13
- Source: BRouter trekking (`231-254.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 0.45 km; projected reverse travel 0.14 km; max closed loop 0.11 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #13 → #14: Cieszyn → Český Těšín

- Route: 1.10 km
- Straight line: 0.57 km
- Detour ratio: 1.93
- Excess over straight line: 0.53 km
- Vertices: 6
- Source: BRouter trekking (`001-024.geojson`)
- Flags: detour ratio > 1.8
- Geometry: max corridor deviation 0.36 km; projected reverse travel 0.08 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Inspect the cached line on the QA map before treating the excess as a routing error.

### #197 → #198: Zuriain → Zabaldika

- Route: 3.46 km
- Straight line: 2.92 km
- Detour ratio: 1.18
- Excess over straight line: 0.54 km
- Vertices: 17
- Source: BRouter trekking (`185-208.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 0.50 km; projected reverse travel 0.02 km; max closed loop 0.13 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #272 → #273: Puente Villarente → Arcahueja

- Route: 4.36 km
- Straight line: 3.96 km
- Detour ratio: 1.10
- Excess over straight line: 0.40 km
- Vertices: 11
- Source: BRouter trekking (`254-277.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 0.23 km; projected reverse travel 0.07 km; max closed loop 0.07 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #219 → #220: Sansol → Torres del Rio

- Route: 0.77 km
- Straight line: 0.38 km
- Detour ratio: 2.00
- Excess over straight line: 0.38 km
- Vertices: 3
- Source: BRouter trekking (`208-231.geojson`)
- Flags: detour ratio > 1.8
- Geometry: max corridor deviation 0.20 km; projected reverse travel 0.07 km; max closed loop 0.00 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

### #288 → #289: Santa Catalina de Somoza → El Ganso

- Route: 4.06 km
- Straight line: 4.12 km
- Detour ratio: 0.99
- Excess over straight line: 0.00 km
- Vertices: 8
- Source: BRouter trekking (`277-300.geojson`)
- Flags: repeated coordinates
- Geometry: max corridor deviation 0.12 km; projected reverse travel 0.01 km; max closed loop 0.08 km; self-intersections 0

Recommendation: Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads.

## Camino cycling notes

BRouter's trekking profile connects the main-route localities on rideable mapped geometry and is not
required to trace the pedestrian Camino line. High-ratio Camino legs still require special care because
road switchbacks, river crossings, and avoiding foot-only paths can be valid. Valcarlos and Calzadilla de
los Hermanillos are retained as explicit alternative-route checkpoints associated with the point where
their branches rejoin; they do not create physical detours or appear as the next main-route destination.

## Reproduction

```powershell
python scripts/audit_santiago_route.py
python scripts/validate_santiago_dataset.py
```

The full 364-leg record is in `data/journeys/santiago/route-qa.json`. Open
`santiago-route-qa.html` through the local Vite server for the developer map.
