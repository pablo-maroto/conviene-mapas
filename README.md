# Conviene · mapas de barrios

Mapas de barrios de las ciudades de Argentina que usa la app **Conviene** (para conductores de apps de viajes).
La app baja solo el mapa de la ciudad que elige el conductor.

- `ciudades.json`: la lista de ciudades con su mapa (nombre, provincia, centro, cantidad de barrios).
- `barrios/<ciudad>.geojson`: los barrios de cada ciudad (propiedad `nombre`; `fuente` = `osm`, `overture` o `aprox`).
  `aprox` = forma aproximada armada a partir de un punto (celdas de Voronoi), donde el mapa solo tiene el nombre y no el límite.

Se actualiza solo una vez por mes (workflow **Mapas de barrios**, en `.github/workflows/mapas.yml`), con
`herramientas/mapas_barrios.py`, a partir de:

- **OpenStreetMap**: © colaboradores de OpenStreetMap — https://www.openstreetmap.org/copyright
- **Overture Maps** (tema *divisions*): © Overture Maps Foundation — https://overturemaps.org

## Licencia
Estos datos son una base de datos derivada de OpenStreetMap y de Overture Maps y se publican bajo la
**Open Database License (ODbL) 1.0**: https://opendatacommons.org/licenses/odbl/1-0/
Podés usarlos, copiarlos y adaptarlos citando la fuente ("© colaboradores de OpenStreetMap y Overture Maps
Foundation") y compartiendo bajo la misma licencia las bases de datos que derives de ellos.

Contacto: appconviene@gmail.com
