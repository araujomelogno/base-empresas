"""Genera un juego de datos sintético pero realista para probar los experimentos de la fase 0.

Escribe en fase0/salida/ejemplo/ (ignorado por git):
  - lista_estudio.xlsx       lista de teléfonos de un estudio: ~300 empresas con RUT válido
  - cdr_septiembre.csv       ~3000 llamadas (campaña y manuales, internos, fuera de lista, ~97% cruzan)
  - parteA.sav               con el bloque estándar completo (EC_ID_ITEM…)
  - parteB.sav               sin EC_ID_ITEM (se asocia por RUT y teléfono)
  - referencia.xlsx          con la hoja "excluidos" (naturalezas jurídicas)
  - base_*.xlsx / .csv       3 bases propias con duplicados, RUTs inválidos, filas sin RUT y
                             teléfonos de estudios contables compartidos por 6–30 RUTs

Determinístico (semilla fija).

    python fase0/datos_ejemplo/generar.py [--salida DIR] [--semilla 2026]
"""
import argparse
import csv
import datetime as dt
import random
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402
from comun import rutmod, telmod  # noqa: E402

SEMILLA = 2026
TZ_UY = ZoneInfo("America/Montevideo")
RUBROS = ["Distribuidora", "Laboratorio", "Transportes", "Industrias", "Comercial", "Agropecuaria", "Constructora",
          "Servicios", "Importadora", "Panificadora", "Metalúrgica", "Imprenta", "Farmacia", "Taller", "Inmobiliaria",
          "Hotel", "Ferretería", "Frigorífico", "Textil", "Software", "Clínica", "Barraca", "Logística", "Vidriería"]
NOMBRES = ["del Sur", "Oriental", "Rambla", "Los Pinos", "Atlántida", "San José", "El Prado", "Colonia", "Artigas",
           "La Teja", "Pocitos", "Minas", "Tacuarembó", "Rivera", "Salto", "Paysandú", "Cerro Largo", "Florida",
           "Durazno", "Rocha", "Pérez", "Rodríguez", "González", "Fernández", "Silva", "Martínez", "Sosa", "Méndez",
           "Olivera", "Cardozo", "Delgado", "Acosta", "Benítez", "Núñez", "del Este", "Malvín", "Carrasco", "Cordón"]
FORMAS = ["S.A.", "S.R.L.", "SAS", "Ltda.", "", "S.A.", "S.R.L."]
DEPARTAMENTOS = ["Montevideo"] * 6 + ["Canelones", "Maldonado", "Colonia", "Salto", "Paysandú", "Rivera", "San José"]
PRIMEROS = ["Ana", "Laura", "Martín", "Diego", "Lucía", "Pablo", "Sofía", "Gonzalo", "Valeria", "Andrés", "Carolina"]
CARGOS = [("Gerente general", "Dirección"), ("Encargada de RRHH", "Recursos humanos"), ("Contador", "Administración"),
          ("Jefe de compras", "Compras"), ("Administrativa", "Administración"), ("Dueño", "Dirección")]
ENCUESTADORES = [f"SIP/enc{i:02d}" for i in range(1, 13)]


class Generador:
    def __init__(self, semilla=SEMILLA):
        self.rnd = random.Random(semilla)
        self.ruts = set()
        self.tels = set()

    # ─── Piezas ───

    def rut(self) -> str:
        while True:
            reg = self.rnd.choice(["21", "21", "21", "21", "21", "02", "01", "22"])
            try:
                r = rutmod.con_verificador(f"{reg}{self.rnd.randint(1, 999999):06d}001")
            except ValueError:
                continue
            if r not in self.ruts:
                self.ruts.add(r)
                return r

    def telefono(self, tipo=None) -> str:
        """Número nacional nuevo: fijo 2XXXXXXX / 4XXXXXXX o celular 09XXXXXXX."""
        tipo = tipo or self.rnd.choices(["mvd", "int", "cel"], [5, 2, 3])[0]
        while True:
            if tipo == "mvd":
                n = "2" + self.rnd.choice("3456789") + f"{self.rnd.randint(0, 999999):06d}"
            elif tipo == "int":
                n = "4" + self.rnd.choice(["22", "23", "33", "35", "36", "42", "47", "52", "62", "72", "73"]) \
                    + f"{self.rnd.randint(0, 99999):05d}"
            else:
                n = "09" + self.rnd.choice("1234589") + f"{self.rnd.randint(0, 999999):06d}"
            if n not in self.tels:
                self.tels.add(n)
                return n

    def crudo(self, nac: str) -> str:
        """Escribe un número nacional como lo escribiría una persona."""
        r = self.rnd.random()
        if nac.startswith("09"):
            opciones = [f"{nac[:3]} {nac[3:6]} {nac[6:]}", nac, f"+598 {nac[1:3]} {nac[3:6]} {nac[6:]}", nac[1:],
                        f"{nac[:3]}-{nac[3:6]}-{nac[6:]}"]
        else:
            opciones = [f"{nac[:4]} {nac[4:]}", nac, f"{nac[:4]}-{nac[4:]}", f"+598 {nac[:4]} {nac[4:]}",
                        f"(0{nac[0]}) {nac[1:4]} {nac[4:]}", f"598{nac}"]
            if r < 0.06:
                return f"{nac[:4]} {nac[4:]} int. {self.rnd.randint(10, 99)}"
        s = self.rnd.choice(opciones)
        assert telmod.normalizar(s).e164 == telmod.normalizar(nac).e164, (s, nac)
        return s

    def razon(self) -> str:
        forma = self.rnd.choice(FORMAS)
        return f"{self.rnd.choice(RUBROS)} {self.rnd.choice(NOMBRES)} {forma}".strip()

    def empresa(self) -> dict:
        tels = [self.telefono()]
        if self.rnd.random() < 0.4:
            tels.append(self.telefono("cel" if tels[0][0] != "0" else "mvd"))
        return {"rut": self.rut(), "razon": self.razon(), "tels": tels, "depto": self.rnd.choice(DEPARTAMENTOS)}

    def fecha_campo(self, desde: dt.date, dias: int) -> dt.datetime:
        while True:
            d = desde + dt.timedelta(days=self.rnd.randrange(dias))
            if d.isoweekday() <= 5 or (d.isoweekday() == 6 and self.rnd.random() < 0.3):
                break
        minutos = self.rnd.randint(10 * 60, 20 * 60 + 30) if d.isoweekday() <= 5 else self.rnd.randint(9 * 60, 13 * 60)
        return dt.datetime.combine(d, dt.time(minutos // 60, minutos % 60, self.rnd.randint(0, 59)))


def rut_escrito(rnd, r: str):
    """El RUT como aparece en planillas: compacto, con puntos o como número (Excel come el 0)."""
    x = rnd.random()
    if x < 0.2:
        return rutmod.formatear(r)
    if x < 0.35:
        return int(r)
    return r


def rut_invalido(rnd, r: str) -> str:
    x = rnd.random()
    if x < 0.5:
        return r[:11] + str((int(r[11]) + rnd.randint(1, 9)) % 10)      # verificador mal tipeado
    if x < 0.8:
        return r[:5] + r[6:]                                            # le falta un dígito
    return r[:3] + "O" + r[4:]                                          # letra O en vez de 0


# ─── Archivos ───

def lista_estudio(g: Generador, empresas, ruta: Path):
    filas = []
    for i, e in enumerate(empresas):
        t1 = g.crudo(e["tels"][0])
        t2 = g.crudo(e["tels"][1]) if len(e["tels"]) > 1 else None
        if t2 and g.rnd.random() < 0.3:          # dos números en la misma celda
            t1, t2 = f"{t1} / {t2}", None
        e["id_item"] = 1001 + i
        filas.append((e["id_item"], rut_escrito(g.rnd, e["rut"]), e["razon"], e["depto"], t1, t2))
    comun.escribir_tabla(ruta, ["id_item", "RUT", "Razón social", "Departamento", "Teléfono", "Teléfono 2"], filas)


USERFIELD = {"ANSWERED": [("Contesta|Completa", 3), ("Contesta|Rechazada", 2), ("Contesta|Agendada", 3),
                          ("Contesta|Interrumpida", 1), ("Contestador telefonico", 3), ("No volver a llamar", 1),
                          ("Contesta|No cumple una condicion filtro", 1)],
             "NO ANSWER": [("No contesta", 1)], "BUSY": [("Ocupado", 1)], "FAILED": [("Fuera de servicio", 1)]}


def cdr(g: Generador, empresas, ruta: Path, desde=dt.date(2026, 9, 1), dias=30) -> dict:
    rnd = g.rnd
    llamadas = []
    cuenta = {}

    def agregar(dst, tipo, campania=None, manual=False):
        disp = rnd.choices(["ANSWERED", "NO ANSWER", "BUSY", "FAILED"], [45, 40, 8, 7])[0]
        uf = rnd.choices([u for u, _ in USERFIELD[disp]], [w for _, w in USERFIELD[disp]])[0]
        billsec = rnd.randint(15, 900) if disp == "ANSWERED" else 0
        agente = rnd.choice(ENCUESTADORES)
        llamadas.append({"calldate": g.fecha_campo(desde, dias), "src": "2" + agente[-2:], "dst": dst,
                         "duration": billsec + rnd.randint(4, 30), "billsec": billsec, "disposition": disp,
                         "userfield": uf if tipo != "interno" else "", "peeraccount": agente,
                         "accountcode": "" if manual or tipo == "interno" else (campania or "EMP-2609")})
        cuenta[tipo] = cuenta.get(tipo, 0) + 1

    def nac_a_marcado(nac, manual):
        if not manual:
            return nac
        return rnd.choice([nac, nac, "+598" + nac.lstrip("0"), "598" + nac.lstrip("0"),
                           ("0" + nac) if nac[0] in "24" else nac])

    pesos = [rnd.uniform(0.5, 3) for _ in empresas]
    for _ in range(2767):
        e = rnd.choices(empresas, pesos)[0]
        manual = rnd.random() < 0.28
        agregar(nac_a_marcado(rnd.choice(e["tels"]), manual), "lista", manual=manual)
    for _ in range(150):
        agregar(rnd.choice(["201", "202", "305", "1005", "4501", "*97", "*98", "#31"]), "interno")
    for _ in range(10):
        agregar(rnd.choice(["08002020", "08001234", "09001777"]), "especial", manual=True)
    otros = [g.telefono() for _ in range(25)]
    for i in range(50):
        agregar(otros[i % 25] if i < 30 else rnd.choice(otros[:5]), "fuera_de_lista", manual=rnd.random() < 0.6)
    for _ in range(3):
        agregar("00541143211234", "internacional", manual=True)
    for _ in range(8):
        agregar(rnd.choice(["9011234", "7104455", "4223344"]), "siete_digitos", manual=True)
    for _ in range(12):   # la central agrega un 9 para tomar línea en algunas posiciones
        agregar("9" + rnd.choice(rnd.choice(empresas)["tels"]), "prefijo_9", manual=True)

    llamadas.sort(key=lambda x: x["calldate"])
    for i, ll in enumerate(llamadas):
        ll["uniqueid"] = f"{int(ll['calldate'].replace(tzinfo=TZ_UY).timestamp())}.{i + 1}"
    contestadas = [ll for ll in llamadas if ll["disposition"] == "ANSWERED" and ll["accountcode"]]
    duplicadas = [dict(ll, billsec=0, duration=3) for ll in rnd.sample(contestadas, 20)]   # tramos de la misma llamada
    filas = sorted(llamadas + duplicadas, key=lambda x: (x["calldate"], x["uniqueid"]))
    columnas = ["uniqueid", "calldate", "src", "dst", "duration", "billsec", "disposition", "userfield", "peeraccount",
                "accountcode"]
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, columnas)
        w.writeheader()
        for ll in filas:
            w.writerow({**ll, "calldate": ll["calldate"].strftime("%Y-%m-%d %H:%M:%S")})
    cuenta["tramos_duplicados"] = len(duplicadas)
    return cuenta


ETQ_CALIDAD = {1: "Corresponde a la empresa", 2: "No es de la empresa", 3: "Estudio contable o jurídico",
               4: "La empresa cerró", 5: "Número inexistente", 9: "No sabe"}
ETQ_RESULTADO = {1: "Completa", 2: "Rechazo", 3: "No corresponde", 4: "Agendada"}
ETQ_SATISF = {1: "Muy insatisfecho", 2: "Insatisfecho", 3: "Ni uno ni otro", 4: "Satisfecho", 5: "Muy satisfecho"}


def _respuesta(g: Generador, e, rid, con_id=True, con_area=True):
    rnd = g.rnd
    nombre, (cargo, area) = rnd.choice(PRIMEROS), rnd.choice(CARGOS)
    fila = {"responseid": float(rid), "status": "Complete",
            "datesubmitted": g.fecha_campo(dt.date(2026, 9, 1), 30).strftime("%Y-%m-%d %H:%M:%S")}
    if con_id:
        fila["EC_ID_ITEM"] = float(e["id_item"])
    fila.update({"EC_RUT": e["rut"], "EC_TEL_USADO": rnd.choice(e["tels"]),
                 "EC_CALIDAD_TEL": float(rnd.choices([1, 2, 3, 4, 5], [85, 5, 4, 3, 3])[0])})
    if con_id:
        fila["EC_TEL_ALT"] = g.telefono("cel") if rnd.random() < 0.1 else ""
    fila.update({"EC_RESP_NOMBRE": nombre, "EC_RESP_CARGO": cargo})
    if con_area:
        fila["EC_RESP_AREA"] = area
    fila["EC_RESULTADO"] = float(rnd.choices([1, 2, 3, 4], [80, 8, 7, 5])[0])
    fila["P1"] = float(rnd.randint(1, 5))
    fila["P2"] = rnd.choice(["", "Mejorar la atención", "Precios", "Nada", "Más plazo de entrega"])
    return fila


def escribir_sav(filas, ruta: Path, etiquetas_var: dict, valores: dict):
    import pandas as pd
    import pyreadstat

    df = pd.DataFrame(filas)
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].fillna("").astype(str)
    pyreadstat.write_sav(df, str(ruta), column_labels=[etiquetas_var.get(c, c) for c in df.columns],
                         variable_value_labels={k: v for k, v in valores.items() if k in df.columns})


ETIQUETAS_VAR = {"responseid": "Response ID", "status": "Status", "datesubmitted": "Date Submitted",
                 "EC_ID_ITEM": "Ítem de muestra", "EC_RUT": "RUT", "EC_TEL_USADO": "Teléfono usado",
                 "EC_CALIDAD_TEL": "Calidad del teléfono", "EC_TEL_ALT": "Teléfono alternativo",
                 "EC_RESP_NOMBRE": "Nombre del respondente", "EC_RESP_CARGO": "Cargo", "EC_RESP_AREA": "Área",
                 "EC_RESULTADO": "Resultado", "P1": "Satisfacción general", "P2": "Qué mejoraría"}


def savs(g: Generador, empresas, ruta_a: Path, ruta_b: Path) -> dict:
    rnd = g.rnd
    elegidas = rnd.sample(empresas, 200)
    a = [_respuesta(g, e, 5000 + i) for i, e in enumerate(elegidas[:120])]
    for f in a[:2]:                      # id_item mal cargado: se recupera por RUT
        f["EC_ID_ITEM"] = float(9000 + int(f["EC_ID_ITEM"]) % 100)
    for f in a[2:4]:                     # respuestas de prueba del link sin URL variables
        f.update(EC_ID_ITEM=float("nan"), EC_RUT="", EC_TEL_USADO="")
    for f in a[10:13]:                   # código fuera del bloque estándar (queda sin mapear)
        f["EC_CALIDAD_TEL"] = 9.0
    valores = {"EC_CALIDAD_TEL": ETQ_CALIDAD, "EC_RESULTADO": ETQ_RESULTADO, "P1": ETQ_SATISF}
    escribir_sav(a, ruta_a, ETIQUETAS_VAR, valores)

    b = [_respuesta(g, e, 7000 + i, con_id=False, con_area=False) for i, e in enumerate(elegidas[120:])]
    for f in b[:2]:                      # RUT mal tipeado: se recupera por el teléfono usado
        f["EC_RUT"] = rut_invalido(random.Random(1), f["EC_RUT"])
    b[2]["EC_RUT"] = rutmod.formatear(b[2]["EC_RUT"])                  # con puntos y guion
    b[3].update(EC_RUT=g.rut(), EC_TEL_USADO=g.telefono())              # empresa que no está en la lista
    escribir_sav(b, ruta_b, ETIQUETAS_VAR, valores)
    return {"parteA": len(a), "parteB": len(b)}


EXCLUIDOS = [("PUB", "Organismo público o ente estatal", "No se encuesta al Estado"),
             ("GD", "Gobierno departamental", "No se encuesta al Estado"),
             ("PPNE", "Persona pública no estatal", "Fuera del universo"),
             (None, "Embajada u organismo internacional", "Fuera del universo"),
             (None, "Sucesión", "Sin actividad")]


def referencia(ruta: Path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Rubros"
    ws.append(["CIIU", "Rubro"])
    for fila in [("1071", "Panaderías"), ("4520", "Talleres mecánicos"), ("6920", "Estudios contables")]:
        ws.append(fila)
    ws2 = wb.create_sheet("excluidos")
    ws2.append(["Código", "Naturaleza jurídica", "Motivo"])
    for fila in EXCLUIDOS:
        ws2.append(list(fila))
    wb.save(ruta)


def bases_propias(g: Generador, lista, destino: Path) -> dict:
    rnd = g.rnd
    universo = lista + [g.empresa() for _ in range(600)]
    specs = [("base_2024_industria.xlsx", 340), ("base_2025_servicios.csv", 380), ("base_2025_comercio.xlsx", 300)]
    bases = []
    for nombre, n in specs:
        elegidas = rnd.sample(universo, n)
        filas = [{"e": e, "rut": e["rut"], "razon": e["razon"], "tels": list(e["tels"])} for e in elegidas]
        for x in rnd.sample(filas, 12):                               # repetidas dentro de la base
            filas.append(dict(x, tels=list(x["tels"])))
        bases.append((nombre, filas))
    todas = [f for _, fs in bases for f in fs]
    ruts = sorted({f["rut"] for f in todas})
    # Teléfonos compartidos: estudios contables (6, 12, 30 RUTs) y grupos de empresas (2–4)
    grupos = [6, 12, 30] + [2] * 8 + [3] * 3 + [4] * 2
    elegidos = rnd.sample(ruts, sum(grupos))
    compartidos = {}
    i = 0
    for tam in grupos:
        tel = g.telefono("mvd")
        for r in elegidos[i:i + tam]:
            compartidos[r] = tel
        i += tam
    for f in todas:
        if f["rut"] in compartidos:
            f["tels"] = [compartidos[f["rut"]]] + f["tels"][:1]
    cuenta = {"compartidos": {tam: grupos.count(tam) for tam in set(grupos)}}
    for nombre, filas in bases:
        rnd.shuffle(filas)
        for f in filas[:12]:                                          # razón social distinta para el mismo RUT
            f["razon"] = f"{rnd.choice(RUBROS)} {rnd.choice(NOMBRES)}"
        for f in filas[12:22]:
            f["rut"] = rut_invalido(rnd, f["rut"])
        for f in filas[22:36]:
            f["rut"] = ""
    for nombre, filas in bases:
        ruta = destino / nombre
        if nombre.endswith("industria.xlsx"):
            comun.escribir_tabla(ruta, ["RUT", "Razón social", "Teléfono", "Departamento"],
                                 [(rut_escrito(rnd, f["rut"]) if f["rut"] and rutmod.es_valido(f["rut"]) else f["rut"],
                                   f["razon"], g.crudo(f["tels"][0]), f["e"]["depto"]) for f in filas])
        elif nombre.endswith(".csv"):
            with open(ruta, "w", encoding="cp1252", newline="") as fh:
                w = csv.writer(fh, delimiter=";")
                w.writerow(["Rut empresa", "Empresa", "Tel 1", "Tel 2", "Email"])
                for f in filas:
                    w.writerow([f["rut"], f["razon"], g.crudo(f["tels"][0]),
                                g.crudo(f["tels"][1]) if len(f["tels"]) > 1 else "", "info@empresa.com.uy"])
        else:
            comun.escribir_tabla(ruta, ["rut", "razon_social", "telefonos", "rubro"],
                                 [(f["rut"], f["razon"], " / ".join(g.crudo(t) for t in f["tels"]),
                                   f["razon"].split()[0]) for f in filas])
        cuenta[nombre] = len(filas)
    return cuenta


def generar(destino=comun.EJEMPLO, semilla=SEMILLA) -> dict:
    """Genera todos los archivos y devuelve sus rutas y algunos conteos esperados."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    g = Generador(semilla)
    empresas = [g.empresa() for _ in range(300)]
    rutas = {"lista": destino / "lista_estudio.xlsx", "cdr": destino / "cdr_septiembre.csv",
             "sav_a": destino / "parteA.sav", "sav_b": destino / "parteB.sav", "excluidos": destino / "referencia.xlsx"}
    lista_estudio(g, empresas, rutas["lista"])
    conteos = {"cdr": cdr(g, empresas, rutas["cdr"])}
    conteos["sav"] = savs(g, empresas, rutas["sav_a"], rutas["sav_b"])
    referencia(rutas["excluidos"])
    conteos["bases"] = bases_propias(g, empresas, destino)
    rutas["bases"] = [destino / n for n in ("base_2024_industria.xlsx", "base_2025_servicios.csv", "base_2025_comercio.xlsx")]
    return {"rutas": rutas, "conteos": conteos}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--salida", default=str(comun.EJEMPLO), help="Carpeta de salida")
    p.add_argument("--semilla", type=int, default=SEMILLA)
    a = p.parse_args(argv)
    r = generar(a.salida, a.semilla)
    for k, v in r["rutas"].items():
        for x in (v if isinstance(v, list) else [v]):
            print(f"{k:10} {comun.rel(x)}")
    print("CDR por tipo de destino:", r["conteos"]["cdr"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
