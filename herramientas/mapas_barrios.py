"""
Arma los mapas de barrios de las ciudades de Argentina para que la app los baje.

Lo corre GitHub Actions (workflow "Mapas de barrios"), que tiene internet completo:
  1. baja OpenStreetMap de Argentina (Geofabrik) y lo filtra con osmium-tool;
  2. baja las divisiones de Overture Maps de Argentina;
  3. corre esto: python mapas_barrios.py filtrado.osm.pbf overture.geojson carpeta_salida

Qué hace:
  - Ciudades: todos los nodos place=city y los place=town de 20.000 habitantes o más.
    Radio según la población (de 4 a 15 km). Provincia: el límite de nivel 4 donde cae.
  - Barrios de cada ciudad, sin repetir nombres:
      a) polígonos de OSM (admin_level 9/10 y place=suburb/neighbourhood/quarter);
      b) polígonos de Overture (neighborhood/macrohood/microhood) que no estén ya;
      c) donde solo hay un punto (OSM), una forma aproximada (Voronoi), marcada "aprox".
  - Formas simplificadas (~4 m) y coordenadas con 5 decimales, para que pesen poco.
  - Salida: barrios/<slug>.geojson por ciudad + ciudades.json (índice para la app).
Córdoba y CABA no se arman: la app trae los mapas oficiales.
Datos © colaboradores de OpenStreetMap (ODbL) y Overture Maps Foundation (ODbL).
"""
import datetime, json, math, os, re, sys, unicodedata, warnings
warnings.filterwarnings("ignore")
import osmium
import shapely.wkb
from shapely.geometry import MultiPoint, Point, mapping, shape
from shapely.ops import transform, unary_union, voronoi_diagram
from shapely.prepared import prep

BARRIO = {"suburb", "neighbourhood", "quarter"}
SUBTIPOS_OVERTURE = {"neighborhood", "macrohood", "microhood"}
MIN_POBLACION_PUEBLO = 20_000
MIN_BARRIOS = int(os.environ.get("MIN_BARRIOS", "8"))


def clave(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"^(barrio|b\.?|bº|b°)\s+", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def slug(s):
    return clave(s).replace(" ", "-")


def poblacion(t):
    m = re.sub(r"[^\d]", "", t or "")
    return int(m) if m else 0


class Juntar(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.wkb = osmium.geom.WKBFactory()
        self.poligonos, self.puntos, self.ciudades, self.provincias = [], [], [], []

    def node(self, n):
        t = n.tags
        nombre = t.get("name")
        if not nombre:
            return
        lugar = t.get("place")
        if lugar in BARRIO:
            self.puntos.append((nombre, n.location.lon, n.location.lat))
        elif lugar == "city" or (lugar == "town" and poblacion(t.get("population")) >= MIN_POBLACION_PUEBLO):
            self.ciudades.append((nombre, poblacion(t.get("population")), n.location.lon, n.location.lat))

    def area(self, a):
        t = a.tags
        nombre = t.get("name")
        if not nombre:
            return
        nivel = t.get("admin_level")
        es_barrio = (t.get("boundary") == "administrative" and nivel in ("9", "10")) or t.get("place") in BARRIO
        es_provincia = t.get("boundary") == "administrative" and nivel == "4"
        if not (es_barrio or es_provincia):
            return
        try:
            g = shapely.wkb.loads(self.wkb.create_multipolygon(a), hex=True)
        except Exception:
            return
        if g.is_empty or not g.is_valid:
            return
        if es_barrio:
            self.poligonos.append((nombre, g))
        else:
            self.provincias.append((nombre, prep(g.simplify(0.01))))


def a_metros(lat0):
    kx = 111_320 * math.cos(math.radians(lat0))
    return (lambda x, y, z=None: (x * kx, y * 110_540)), (lambda x, y, z=None: (x / kx, y / 110_540))


def redondear(g):
    return transform(lambda x, y, z=None: (round(x, 5), round(y, 5)), g)


def overture(ruta):
    salida = []
    if not ruta or not os.path.exists(ruta):
        return salida
    for f in json.load(open(ruta, encoding="utf-8"))["features"]:
        p = f["properties"]
        if p.get("subtype") not in SUBTIPOS_OVERTURE:
            continue
        n = p.get("names") or {}
        if isinstance(n, str):
            n = json.loads(n)
        nombre = n.get("primary")
        if not nombre:
            continue
        try:
            g = shape(f["geometry"])
            if g.is_valid and not g.is_empty:
                salida.append((nombre, g))
        except Exception:
            pass
    return salida


def main(pbf, ruta_overture, salida):
    os.makedirs(os.path.join(salida, "barrios"), exist_ok=True)
    h = Juntar()
    h.apply_file(pbf, locations=True)
    ov = overture(ruta_overture)
    print(f"OSM: {len(h.poligonos)} polígonos, {len(h.puntos)} puntos, {len(h.ciudades)} ciudades, "
          f"{len(h.provincias)} provincias. Overture: {len(ov)} barrios.")
    indice, usados = [], set()
    for nombre, pob, lon, lat in sorted(h.ciudades, key=lambda c: -c[1]):
        provincia = next((pn for pn, pg in h.provincias if pg.contains(Point(lon, lat))), "")
        if clave(provincia).startswith("ciudad autonoma") or (clave(nombre) == "cordoba" and clave(provincia) == "cordoba"):
            continue  # vienen dentro de la app, con el mapa oficial
        radio = max(4.0, min(15.0, 3 + math.sqrt(max(pob, 1)) / 60))
        ida, vuelta = a_metros(lat)
        centro_m = Point(*ida(lon, lat))
        circulo = transform(vuelta, centro_m.buffer(radio * 1000, 64))
        caja = circulo.bounds

        def adentro(g):
            if g.bounds[2] < caja[0] or g.bounds[0] > caja[2] or g.bounds[3] < caja[1] or g.bounds[1] > caja[3]:
                return False
            return g.intersects(circulo) and g.intersection(circulo).area > 0.5 * g.area

        elegidos = {}  # clave → (nombre, fuente, geometría)
        for n, g in h.poligonos:
            k = clave(n)
            if adentro(g) and (k not in elegidos or g.area > elegidos[k][2].area):
                elegidos[k] = (n, "osm", g)
        tapado = unary_union([g for _, _, g in elegidos.values()]) if elegidos else None
        for n, g in ov:
            k = clave(n)
            if k in elegidos or not adentro(g):
                continue
            if tapado is not None and g.intersection(tapado).area > 0.6 * g.area:
                continue  # es un barrio que ya está, con otro nombre
            elegidos[k] = (n, "overture", g)
        tapado = unary_union([g for _, _, g in elegidos.values()]) if elegidos else None
        pts = {}
        for n, x, y in h.puntos:
            p = Point(x, y)
            k = clave(n)
            if k not in elegidos and k not in pts and circulo.contains(p) and (tapado is None or not tapado.contains(p)):
                pts[k] = (n, p)
        aprox = []
        if len(pts) >= 2:
            claves = list(pts)
            mp = MultiPoint([Point(*ida(pts[k][1].x, pts[k][1].y)) for k in claves])
            borde = centro_m.buffer(radio * 1000, 64)
            limite = borde.intersection(mp.buffer(1500))
            if tapado is not None:
                limite = limite.difference(transform(ida, tapado))
            for celda in voronoi_diagram(mp, envelope=borde).geoms:
                k = next((kk for kk, p in zip(claves, mp.geoms) if celda.contains(p)), None)
                if k is None:
                    continue
                g = celda.intersection(limite)
                if not g.is_empty:
                    aprox.append((pts[k][0], "aprox", transform(vuelta, g)))
        todos = list(elegidos.values()) + aprox
        if len(todos) < MIN_BARRIOS:
            continue
        s = slug(nombre)
        if s in usados:
            s = f"{s}-{slug(provincia)}"
        if s in usados:
            continue
        usados.add(s)
        features = []
        for n, fuente, g in sorted(todos, key=lambda t: clave(t[0])):
            gm = transform(ida, g).simplify(4, preserve_topology=True)
            if gm.is_empty:
                continue
            features.append({"type": "Feature", "properties": {"nombre": n, "fuente": fuente},
                             "geometry": mapping(redondear(transform(vuelta, gm)))})
        ruta = os.path.join(salida, "barrios", s + ".geojson")
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False, separators=(",", ":"))
        cuenta = {k: sum(1 for _, fu, _ in todos if fu == k) for k in ("osm", "overture", "aprox")}
        indice.append({"slug": s, "nombre": nombre, "provincia": provincia, "lat": round(lat, 5), "lon": round(lon, 5),
                       "radioKm": round(radio, 1), "barrios": len(features), "bytes": os.path.getsize(ruta), "fuentes": cuenta})
        print(f"{nombre} ({provincia}): {len(features)} barrios {cuenta}")
    indice.sort(key=lambda c: clave(c["nombre"]))
    with open(os.path.join(salida, "ciudades.json"), "w", encoding="utf-8") as f:
        json.dump({"version": datetime.date.today().isoformat(),
                   "atribucion": "© colaboradores de OpenStreetMap y Overture Maps Foundation (ODbL)",
                   "ciudades": indice}, f, ensure_ascii=False, separators=(",", ":"))
    total = sum(c["bytes"] for c in indice)
    print(f"Listo: {len(indice)} ciudades, {total / 1e6:.1f} MB en total")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
