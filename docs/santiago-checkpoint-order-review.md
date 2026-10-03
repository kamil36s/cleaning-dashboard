# Santiago checkpoint order review

## Decision

The source identity set remains exactly 365 checkpoints. `originalIndex` preserves the supplied order;
runtime `index` is the optimized journey order. Only strong-confidence geographic corrections are accepted.

## Baseline

- Route distance: **4409.19 km**
- Sum of detected cross-leg closed loops over 0.5 km: **277.41 km**
- Automatic retrace/order flags: **60**

## Applied result

- Route distance: **4294.18 km**
- Distance reduction: **115.01 km**
- Cross-leg retrace sum: **162.84 km**
- Cross-leg retrace reduction: **114.57 km**
- Remaining automatic ordering flags: **56**

## Accepted order changes

| Checkpoint | Original | Old neighbors | New neighbors | Estimated saving | Reason |
| --- | ---: | --- | --- | ---: | --- |
| Balzers | 98 | Triesen → Sargans | Triesen → Maienfeld | 23.94 km | The existing Balzers → Sargans → Bad Ragaz → Maienfeld order crosses the Rhine valley twice. Balzers → Maienfeld → Bad Ragaz → Sargans continues toward Flums without the detected closed loop. |
| Sargans | 99 | Balzers → Bad Ragaz | Bad Ragaz → Flums | 0.00 km | The existing Balzers → Sargans → Bad Ragaz → Maienfeld order crosses the Rhine valley twice. Balzers → Maienfeld → Bad Ragaz → Sargans continues toward Flums without the detected closed loop. |
| Bad Ragaz | 100 | Sargans → Maienfeld | Maienfeld → Sargans | 0.00 km | The existing Balzers → Sargans → Bad Ragaz → Maienfeld order crosses the Rhine valley twice. Balzers → Maienfeld → Bad Ragaz → Sargans continues toward Flums without the detected closed loop. |
| Maienfeld | 101 | Bad Ragaz → Flums | Balzers → Bad Ragaz | 0.00 km | The existing Balzers → Sargans → Bad Ragaz → Maienfeld order crosses the Rhine valley twice. Balzers → Maienfeld → Bad Ragaz → Sargans continues toward Flums without the detected closed loop. |
| Orthez | 179 | Bidache → Sauveterre-de-Béarn | Saint-Palais, Pyrénées-Atlantiques → Sauveterre-de-Béarn | 0.00 km | Orthez and Sauveterre form the eastern approach to Saint-Palais, while the active journey arrives through Peyrehorade and Bidache. Keeping both approaches in the physical line causes the 46.86 km Bidache retrace plus the following 7.73 km repeated corridor. |
| Sauveterre-de-Béarn | 180 | Orthez → Saint-Palais, Pyrénées-Atlantiques | Orthez → Larceveau-Arros-Cibits | 0.00 km | Orthez and Sauveterre form the eastern approach to Saint-Palais, while the active journey arrives through Peyrehorade and Bidache. Keeping both approaches in the physical line causes the 46.86 km Bidache retrace plus the following 7.73 km repeated corridor. |
| Saint-Palais, Pyrénées-Atlantiques | 181 | Sauveterre-de-Béarn → Larceveau-Arros-Cibits | Bidache → Orthez | 54.59 km | Orthez and Sauveterre form the eastern approach to Saint-Palais, while the active journey arrives through Peyrehorade and Bidache. Keeping both approaches in the physical line causes the 46.86 km Bidache retrace plus the following 7.73 km repeated corridor. |
| Valcarlos | 186 | Orisson → Lepoeder Peak | Roncesvalles → Auritz / Burguete | 0.00 km | Valcarlos is the valley alternative to the Hontto → Orisson → Lepoeder Route Napoléon. It is associated with Roncesvalles, where both approaches rejoin, instead of forcing both branches. |
| Lepoeder Peak | 187 | Valcarlos → Roncesvalles | Orisson → Roncesvalles | 7.37 km | Valcarlos is the valley alternative to the Hontto → Orisson → Lepoeder Route Napoléon. It is associated with Roncesvalles, where both approaches rejoin, instead of forcing both branches. |
| Roncesvalles | 188 | Lepoeder Peak → Auritz / Burguete | Lepoeder Peak → Valcarlos | 0.00 km | Valcarlos is the valley alternative to the Hontto → Orisson → Lepoeder Route Napoléon. It is associated with Roncesvalles, where both approaches rejoin, instead of forcing both branches. |
| Calzadilla de los Hermanillos | 268 | Bercianos del Real Camino → El Burgo Ranero | El Burgo Ranero → Reliegos | 0.00 km | Calzadilla de los Hermanillos belongs to the Via Trajana alternative after Calzada del Coto; Bercianos del Real Camino belongs to the main Camino branch. It remains a milestone associated with the nearby main-route position at El Burgo Ranero. |
| El Burgo Ranero | 269 | Calzadilla de los Hermanillos → Reliegos | Bercianos del Real Camino → Calzadilla de los Hermanillos | 11.63 km | Calzadilla de los Hermanillos belongs to the Via Trajana alternative after Calzada del Coto; Bercianos del Real Camino belongs to the main Camino branch. It remains a milestone associated with the nearby main-route position at El Burgo Ranero. |
| San Cristovo do Real (Lusio) | 320 | Triacastela → A Balsa | A Balsa → Samos | 0.00 km | From Triacastela the coordinates place A Balsa before San Cristovo do Real on the selected Samos branch. Their previous order creates the detected north/south return before continuing to Samos. |
| A Balsa | 321 | San Cristovo do Real (Lusio) → Samos | Triacastela → San Cristovo do Real (Lusio) | 14.67 km | From Triacastela the coordinates place A Balsa before San Cristovo do Real on the selected Samos branch. Their previous order creates the detected north/south return before continuing to Samos. |

## Variant checkpoints

- **Orthez** (original #179) → associated with **Saint-Palais, Pyrénées-Atlantiques**: Eastern Orthez/Sauveterre approach; associated where it rejoins at Saint-Palais.
- **Sauveterre-de-Béarn** (original #180) → associated with **Saint-Palais, Pyrénées-Atlantiques**: Eastern Orthez/Sauveterre approach; associated where it rejoins at Saint-Palais.
- **Valcarlos** (original #186) → associated with **Roncesvalles**: Valcarlos approach; associated where it rejoins the Route Napoléon at Roncesvalles.
- **Calzadilla de los Hermanillos** (original #268) → associated with **El Burgo Ranero**: Via Trajana branch; associated with the nearby main Camino position at El Burgo Ranero.

## Manual review retained

- **Krems an der Donau / Herzogenburg / Sankt Pölten:** Krems is a genuine Danube milestone and Herzogenburg lies on the southbound transition. The 25.44 km retrace is real, but none of the alternative orders is clearly more coherent.
- Every baseline cross-leg retrace remains listed with an explicit decision in
  `data/journeys/santiago/checkpoint-order-review.json`.

## Persistence

Committed journey progress remains a kilometre value. Rebuilding the route does not rewrite or reset
`committed_distance_km`; only percentage, interpolated position, and future checkpoint timing can change.
