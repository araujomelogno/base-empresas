"""Carga datos ficticios de demostración en una base vacía (desarrollo, capacitación y capturas del manual).

    DATABASE_URL=postgresql://postgres@localhost/empresas_demo python api/demo/sembrar_demo.py

Usa la propia API (en proceso, modo dev) para que los datos pasen por las mismas reglas:
carga de dos bases, intermediarios, estudio con dos partes, muestra estratificada,
un lote de CDR y la ingesta de un .sav. Todos los nombres y números son inventados.
"""
import io
import os
import random
import sys
import tempfile

os.environ.setdefault("AUTH_MODE", "dev")
os.environ["TASKS_MODE"] = "inline"
os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp(prefix="empresas-demo-"))
RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(RAIZ, "api"))
sys.path.insert(0, os.path.join(RAIZ, "db"))

import pandas as pd  # noqa: E402
import psycopg  # noqa: E402
import pyreadstat  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import migrate  # noqa: E402
from app import rut as rutmod  # noqa: E402
from app.main import app  # noqa: E402

R = random.Random(2026)
USUARIOS = [("admin@equipos.com.uy", "Germán Araújo", "admin"), ("steward@equipos.com.uy", "Lucía Fernández", "steward"),
            ("jefe@equipos.com.uy", "Martín Silva", "jefe"), ("coord@equipos.com.uy", "Valentina Rodríguez", "coordinador"),
            ("lectura@equipos.com.uy", "Dirección", "lectura")]
RUBROS = [("4711", "Supermercado"), ("5610", "Restaurante"), ("4520", "Taller mecánico"), ("6201", "Software"),
          ("4100", "Construcciones"), ("8610", "Clínica"), ("4930", "Transporte"), ("1071", "Panificadora"),
          ("6920", "Estudio contable"), ("4771", "Tienda de ropa"), ("5510", "Hotel"), ("0141", "Establecimiento ganadero")]
NOMBRES = ["Del Plata", "Oriental", "Rioplatense", "Los Robles", "San José", "Atlántida", "Bella Vista", "El Ceibo",
           "La Esperanza", "Norte", "Sur", "Pocitos", "Cordón", "Malvín", "Tres Cruces", "Prado", "Carrasco", "Colonia",
           "Artigas", "Rambla", "Los Pinos", "La Aguada", "Las Piedras", "Rocha", "El Faro", "Punta", "Del Este"]
DEPTOS = ["Montevideo"] * 6 + ["Canelones"] * 2 + ["Maldonado", "Salto", "Paysandú", "Colonia", "Rivera", "San José"]
TAMANOS = ["Micro"] * 3 + ["Pequeña"] * 3 + ["Mediana"] * 2 + ["Grande"]
NATS = ["SA"] * 5 + ["SRL"] * 3 + ["SAS", "UNI", "UNI", "COOP", "PUB"]
PERSONAS = ["Ana García", "Pablo Martínez", "Sofía López", "Diego Pereira", "Camila Rodríguez", "Javier Sosa",
            "Florencia Díaz", "Martín Núñez", "Carolina Suárez", "Federico Méndez", "Mariana Castro", "Santiago Romero"]
CARGOS = [("Gerente de RRHH", "RRHH"), ("Gerente general", "Dirección"), ("Encargada de administración", "Administración"),
          ("Jefe de personal", "RRHH"), ("Contador", "Finanzas")]


def ruts(n):
    salida, i = [], 200000
    while len(salida) < n:
        base = f"21{i:06d}001"
        if rutmod.digito_verificador(base) is not None:
            salida.append(rutmod.con_verificador(base))
        i += 7
    return salida


def bases():
    rr = ruts(260)
    contables = [f"2900 {R.randint(1000, 9999)}" for _ in range(3)]
    filas_a, filas_b = [], []
    for k, r in enumerate(rr[:240]):
        ciiu, rubro = R.choice(RUBROS)
        nombre = f"{rubro} {R.choice(NOMBRES)}"
        forma = R.choice(NATS)
        depto = R.choice(DEPTOS)
        pref = "2" if depto == "Montevideo" else "4"
        tel = f"{pref}{R.randint(1000000, 9999999)}"
        tels = [tel]
        if R.random() < 0.45:
            tels.append(f"09{R.randint(1, 9)} {R.randint(100, 999)} {R.randint(100, 999)}")
        if k % 13 == 0:
            tels.append(contables[k % 3])  # el número del estudio contable compartido
        p, (cargo, area) = R.choice(PERSONAS), R.choice(CARGOS)
        filas_a.append({"RUT": r, "Razón social": f"{nombre} {forma if forma in ('SA', 'SRL', 'SAS') else ''}".strip(),
                        "Nombre fantasía": nombre, "Naturaleza": forma, "CIIU": ciiu, "Tamaño": R.choice(TAMANOS),
                        "Departamento": depto, "Dirección": f"Calle {R.randint(1, 3000)}", "Teléfono": " / ".join(tels),
                        "Contacto": p if R.random() < 0.6 else "", "Cargo": cargo, "Área": area,
                        "Web": f"www.{nombre.lower().replace(' ', '')}.com.uy" if R.random() < 0.3 else ""})
    filas_a.append({**filas_a[0], "RUT": "210000000000"})  # RUT inválido
    filas_a.append({**filas_a[1], "RUT": ""})
    for r in rr[200:260]:  # segunda base: se solapa con la primera y trae algunas nuevas
        ciiu, rubro = R.choice(RUBROS)
        filas_b.append({"rut": r, "razon_social": f"{rubro} {R.choice(NOMBRES)} SRL", "telefono": f"2{R.randint(1000000, 9999999)}",
                        "departamento": R.choice(DEPTOS), "tramo": R.choice(TAMANOS)})
    return filas_a, filas_b


def csv_bytes(filas, sep=";"):
    return pd.DataFrame(filas).to_csv(sep=sep, index=False).encode("utf-8")


def xlsx_bytes(filas):
    buf = io.BytesIO()
    pd.DataFrame(filas).to_excel(buf, index=False)
    return buf.getvalue()


def main():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("Falta DATABASE_URL")
    migrate.aplicar(dsn)
    with psycopg.connect(dsn, autocommit=True) as c:
        if c.execute("SELECT count(*) FROM empresas.empresa").fetchone()[0]:
            sys.exit("La base ya tiene empresas: la demo se carga sobre una base vacía")
        for email, nombre, rol in USUARIOS:
            c.execute("INSERT INTO empresas.usuario (email, nombre, rol, exportar_contactos) VALUES (%s,%s,%s,%s)"
                      " ON CONFLICT (email) DO NOTHING", (email, nombre, rol, rol in ("admin", "coordinador")))
    api = TestClient(app)
    H = {r: {"X-Dev-User": e} for e, _, r in USUARIOS}

    def ok(resp):
        if resp.status_code >= 300:
            raise SystemExit(f"{resp.request.method} {resp.request.url}: {resp.status_code} {resp.text}")
        return resp.json()

    def cargar(nombre, contenido, tipo, fuente, licencia, confianza):
        a = ok(api.post("/api/cargas/analizar", headers=H["steward"], files={"archivo": (nombre, contenido)}, data={"tipo_fuente": tipo}))
        c = ok(api.post("/api/cargas", headers=H["steward"], json={"archivo_id": a["archivo_id"], "fuente": fuente, "tipo_fuente": tipo,
                                                                   "licencia": licencia, "confianza": confianza, "mapeo": a["mapeo"]}))
        ok(api.post(f"/api/cargas/{c['carga_id']}/confirmar", headers=H["steward"]))
        return c["carga_id"]

    filas_a, filas_b = bases()
    cargar("base_estudios_2025.xlsx", xlsx_bytes(filas_a), "base propia de estudios", "Estudios a empresas 2025",
           "Base propia de Equipos, uso interno", 60)
    # Padrón con razón social igual a una empresa existente y otro RUT: va a la bandeja de revisión
    otro = ruts(300)[290:293]
    padron = [{"RUT": otro[0], "Razón social": filas_a[10]["Razón social"].upper().replace(" SA", " S.A."), "Teléfono": "2604 1111"},
              {"RUT": otro[1], "Razón social": "Consultora Andina SRL", "Teléfono": "2604 2222"},
              {"RUT": otro[2], "Razón social": filas_a[20]["Razón social"], "Teléfono": "2604 3333"}]
    a = ok(api.post("/api/cargas/analizar", headers=H["steward"], files={"archivo": ("padron_parcial.csv", csv_bytes(padron))},
                    data={"tipo_fuente": "padrón"}))
    c = ok(api.post("/api/cargas", headers=H["steward"], json={"archivo_id": a["archivo_id"], "fuente": "Padrón parcial 2026", "tipo_fuente": "padrón",
                                                              "licencia": "Datos públicos", "regla_fusion": "razon_social", "confianza": 70, "mapeo": a["mapeo"]}))
    ok(api.post(f"/api/cargas/{c['carga_id']}/confirmar", headers=H["steward"]))
    # Segunda base: queda en preview para mostrar la pantalla de confirmación
    a = ok(api.post("/api/cargas/analizar", headers=H["steward"], files={"archivo": ("directorio_camaras.csv", csv_bytes(filas_b))},
                    data={"tipo_fuente": "directorio de cámaras"}))
    ok(api.post("/api/cargas", headers=H["steward"], json={"archivo_id": a["archivo_id"], "fuente": "Directorio de cámaras empresariales",
                                                          "tipo_fuente": "directorio de cámaras", "licencia": "Convenio 2026, uso para investigación",
                                                          "regla_fusion": "telefono", "confianza": 40, "mapeo": a["mapeo"]}))
    ok(api.post("/api/naturalezas", headers=H["admin"], json={"codigo": "PUB", "nombre": "Organismo público o ente estatal", "excluida": True}))
    p = ok(api.get("/api/config", headers=H["admin"]))["parametros"]
    p["meses_enfriamiento"] = 12
    ok(api.put("/api/config", headers=H["admin"], json={"parametros": p, "comentario": "Enfriamiento de 12 meses (dirección)"}))
    # Liberar uno de los teléfonos compartidos y dejar los otros como sospechosos
    sosp = ok(api.get("/api/telefonos/sospechosos", headers=H["steward"]))["telefonos"]
    if sosp:
        ok(api.post(f"/api/telefonos/{sosp[0]['id']}/resolver", headers=H["steward"],
                    json={"accion": "confirmar", "motivo": "Estudio contable Pérez & Asociados"}))
    ok(api.post("/api/no-llamar", headers=H["admin"], json={"alcance": "empresa", "rut": filas_a[5]["RUT"],
                                                           "motivo": "Pidió no ser contactada (correo del 12/10)", "solicitante": "Gerencia de la empresa"}))
    est = ok(api.post("/api/estudios", headers=H["jefe"], json={
        "nombre": "Clima laboral en empresas 2026", "cliente": "Cámara de Industrias (ficticio)",
        "campo_desde": "2026-10-19", "campo_hasta": "2026-11-27",
        "partes": [{"nombre": "Parte A — RRHH", "survey_id": "8012345", "respondente_objetivo": "RRHH",
                    "link_base": "https://survey.alchemer.com/s3/8012345/clima-a"},
                   {"nombre": "Parte B — Dirección", "survey_id": "8012346", "respondente_objetivo": "Gerente general",
                    "link_base": "https://survey.alchemer.com/s3/8012346/clima-b"}]}))
    m = ok(api.post("/api/muestras", headers=H["jefe"], json={"estudio_id": est["id"], "nombre": "Muestra principal", "criterios": {
        "filtros": {}, "estratificar_por": ["tamano"],
        "estratos": [{"estrato": "Grande", "n": 10, "reemplazos": 5}, {"estrato": "Mediana", "n": 15, "reemplazos": 6},
                     {"estrato": "Pequeña", "n": 20, "reemplazos": 8}, {"estrato": "Micro", "n": 20, "reemplazos": 8}]}}))
    ok(api.post(f"/api/muestras/{m['id']}/sortear", headers=H["jefe"], json={"semilla": 20261029}))
    parte_a = ok(api.get(f"/api/estudios/{est['id']}", headers=H["jefe"]))["partes"][0]
    items = ok(api.get(f"/api/muestras/{m['id']}/items", headers=H["jefe"]))
    ok(api.post(f"/api/muestras/{m['id']}/liberar", headers=H["jefe"], json={"estrato": "Grande", "cantidad": 2,
                                                                              "motivo": "Dos rechazos en la primera semana"}))
    # Llamadas del CDR: teléfonos de la muestra, internos y números fuera de la base
    with psycopg.connect(dsn, autocommit=True) as c:
        tels = [r[0] for r in c.execute(
            "SELECT t.e164 FROM empresas.muestra_item i JOIN empresas.telefono_vinculo v ON v.empresa_id = i.empresa_id"
            " JOIN empresas.telefono t ON t.id = v.telefono_id WHERE i.muestra_id = %s AND i.liberado", (m["id"],))]
    llamadas = []
    encuestadores = ["SIP/agustina", "SIP/bruno", "SIP/carla", "SIP/damian"]
    disp = ["ANSWER|COMPLETA", "NO ANSWER|", "BUSY|", "ANSWER|RECHAZO", "ANSWER|AGENDA", "ANSWER|"]
    for k in range(420):
        dia = 19 + (k % 10)
        hora = R.choice([10, 11, 12, 13, 14, 15, 16, 17, 18])
        destino = R.choice(tels)[4:] if R.random() < 0.85 else R.choice(["4501", "4502", f"09{R.randint(10000000, 99999999)}"[:9]])
        if destino.startswith("9"):
            destino = "0" + destino
        llamadas.append({"cdr_id": f"demo-{k}", "inicio": f"2026-10-{dia:02d}T{hora:02d}:{R.randint(0, 59):02d}:00-03:00",
                         "destino": destino, "encuestador": R.choice(encuestadores), "duracion": R.randint(0, 600),
                         "userfield": R.choice(disp), "campania": "Clima 2026" if R.random() < 0.6 else None})
    os.environ["JOB_TOKEN"] = os.environ.get("JOB_TOKEN") or "demo"
    from app import settings
    settings.JOB_TOKEN = os.environ["JOB_TOKEN"]
    ok(api.post("/api/intentos/lote", headers={"X-Job-Token": settings.JOB_TOKEN}, json={"origen": "uContact", "llamadas": llamadas}))
    # .sav de la parte A con el bloque estándar
    filas = []
    for k, it in enumerate([i for i in items if i["liberado"]][:30]):
        tel = next((t for t in tels), "")
        res = R.choice([1, 1, 1, 2, 3, 4])
        cal = 1 if res != 3 else R.choice([2, 3, 4])
        p_, (cargo, area) = R.choice(PERSONAS), R.choice(CARGOS)
        filas.append({"responseid": 5000 + k, "EC_ID_ITEM": it["id"] if k != 7 else 999999, "EC_RUT": it["rut"],
                      "EC_TEL_USADO": "", "EC_CALIDAD_TEL": cal if k != 3 else 9,
                      "EC_TEL_ALT": f"09{R.randint(1, 9)}{R.randint(100000, 999999)}" if k % 6 == 0 else "",
                      "EC_RESP_NOMBRE": p_ if res in (1, 2) else "", "EC_RESP_CARGO": cargo if res in (1, 2) else "",
                      "EC_RESP_AREA": area if res in (1, 2) else "", "EC_RESULTADO": res,
                      "status": "Complete" if res == 1 else "Partial", "datesubmitted": f"2026-10-{20 + k % 8} 1{k % 8}:15:00"})
    with psycopg.connect(dsn, autocommit=True) as c:
        for f in filas:
            r = c.execute("SELECT t.e164 FROM empresas.muestra_item i JOIN empresas.telefono_vinculo v ON v.empresa_id = i.empresa_id"
                          " JOIN empresas.telefono t ON t.id = v.telefono_id WHERE i.id = %s LIMIT 1", (f["EC_ID_ITEM"],)).fetchone()
            f["EC_TEL_USADO"] = r[0].lstrip("+") if r else ""
    df = pd.DataFrame(filas)
    fd, ruta = tempfile.mkstemp(suffix=".sav")
    os.close(fd)
    pyreadstat.write_sav(df, ruta, variable_value_labels={
        "EC_CALIDAD_TEL": {1: "Corresponde", 2: "No es de la empresa", 3: "Estudio contable o jurídico", 4: "La empresa cerró", 5: "Inexistente"},
        "EC_RESULTADO": {1: "Completa", 2: "Rechazo", 3: "No corresponde", 4: "Agendada"}},
        column_labels={"EC_ID_ITEM": "Identificador del ítem", "EC_CALIDAD_TEL": "Calidad del teléfono", "EC_RESULTADO": "Resultado"})
    with open(ruta, "rb") as f:
        sav = f.read()
    a = ok(api.post(f"/api/partes/{parte_a['id']}/sav/analizar", headers=H["coordinador"], files={"archivo": ("clima_parte_a_ola1.sav", sav)}))
    a["mapeo"]["valores"]["calidad_tel"]["9"] = "ignorar"
    ok(api.post(f"/api/partes/{parte_a['id']}/sav", headers=H["coordinador"], json={"ingesta_id": a["ingesta_id"], "mapeo": a["mapeo"]}))
    with open(os.path.join(os.path.dirname(__file__), "clima_parte_a_ola1.sav"), "wb") as f:
        f.write(sav)
    from app.db import cerrar
    cerrar()
    print("Demo cargada. Usuarios:", ", ".join(e for e, _, _ in USUARIOS))


if __name__ == "__main__":
    main()
