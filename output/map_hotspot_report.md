# Map hotspot report

Скопировано из поставки агента карты (`Desktop/test/output/`). JSON: там же `map_hotspot_report.json`.

CRS EPSG:3825, meters, Y north. Vegetation F `9fa777810c3a`.
Roads kept: 1476. Buildings: 3601 OSM + 7498 modeled, dropped overlaps 0.

## Champions

- draw_calls whole: L/L4 Magong (310128, 2606885) → 4273 calls, 23366 verts
- vertices whole: L/L3 Magong → 24860 verts
- clipped buildings L6/L7: M/L6 Qimei → 515 building draws

## Matrix top-1

- S/L0 Magong whole 55c/869v clip 3382c/719v risk high
- S/L1 Magong whole 148c/1516v clip 677c/1509v risk medium
- S/L2 Magong whole 1206c/12827v clip 1745c/12751v risk high
- S/L3 Magong whole 1587c/13729v clip 1913c/13264v risk high
- S/L4 Magong whole 2606c/16667v clip 2811c/15552v risk high
- S/L5 Magong whole 1102c/8534v clip 1139c/5657v risk high
- S/L6 Qimei whole 516c/5660v clip 531c/2547v risk medium
- S/L7 Qimei whole 147c/3809v clip 150c/704v risk low
- M/L0 Magong whole 57c/877v clip 3386c/727v risk high
- M/L1 Magong whole 164c/1565v clip 695c/1559v risk medium
- M/L2 Magong whole 1313c/13177v clip 1852c/13101v risk high
- M/L3 Magong whole 2736c/18763v clip 3101c/18300v risk high
- M/L4 Magong whole 3989c/22226v clip 4236c/21111v risk high
- M/L5 Magong whole 1103c/8538v clip 1140c/5660v risk high
- M/L6 Qimei whole 518c/5668v clip 533c/2553v risk medium
- M/L7 Qimei whole 147c/3809v clip 150c/704v risk low
- L/L0 Magong whole 57c/877v clip 3386c/727v risk high
- L/L1 Magong whole 180c/1608v clip 712c/1602v risk medium
- L/L2 Magong whole 1371c/13363v clip 1911c/13287v risk high
- L/L3 Magong whole 4226c/24860v clip 4634c/24398v risk high
- L/L4 Magong whole 4273c/23366v clip 4524c/22246v risk high
- L/L5 Magong whole 1105c/8546v clip 1142c/5666v risk high
- L/L6 Qimei whole 518c/5668v clip 533c/2553v risk medium
- L/L7 Qimei whole 147c/3809v clip 150c/704v risk low
