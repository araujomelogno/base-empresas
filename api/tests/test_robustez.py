"""SPEC_cargas_lotes_robustez (D52): lectura en streaming, tareas que se retoman solas (latido, dueño, reintentos de
Cloud Tasks, apagado ordenado), la reanudación automática y el aviso de migraciones faltantes."""
import threading
import time
import types

import pytest

from conftest import cargar, csv_bytes, rut_valido

TOKEN = {"X-Tarea-Token": "token-tarea"}


def fila(i, **extra):
    return {"RUT": rut_valido(i), "Razón social": f"Empresa {i}", "Teléfono": f"2900{i:04d}", "Departamento": "Salto",
            **extra}


def cuenta(sql, tabla, where="TRUE"):
    return sql.execute(f"SELECT count(*) AS n FROM {tabla} WHERE {where}").fetchone()["n"]


CLAVES = ("altas", "actualizaciones", "sin_cambios", "rechazos", "telefonos_nuevos", "vinculos_nuevos", "filas")


class Muerte(BaseException):
    """Simula que el proceso muere a mitad de un lote (falta de memoria, kill -9): nada lo atrapa."""


@pytest.fixture
def apagado():
    from app import tareas

    yield tareas
    tareas._apagando.clear()


def _en_el_lote(monkeypatch, numero, accion):
    """Llama accion() al empezar a aplicar el lote «numero» de la confirmación."""
    from app import cargas as cargas_mod

    original = cargas_mod.procesar
    vistos = []

    def procesar(conn, carga, filas, *a, **k):
        if k.get("real"):
            vistos.append(1)
            if len(vistos) == numero:
                accion()
        return original(conn, carga, filas, *a, **k)

    monkeypatch.setattr(cargas_mod, "procesar", procesar)


# ─── R1 · Lectura en streaming ───

def test_iterar_tabla_no_arma_la_lista_entera():
    import io

    from openpyxl import Workbook

    from app import lectores

    cols, filas = lectores.iterar_tabla(b"RUT;Nombre\n1;a\n\n2;b\n", "csv")
    assert isinstance(filas, types.GeneratorType) and cols == ["RUT", "Nombre"]
    assert list(filas) == [{"RUT": "1", "Nombre": "a"}, {"RUT": "2", "Nombre": "b"}]
    wb = Workbook()
    wb.active.append(["RUT", "Nombre"])
    wb.active.append(["1", "a"])
    buf = io.BytesIO()
    wb.save(buf)
    cols, filas = lectores.iterar_tabla(buf.getvalue(), "xlsx")
    assert isinstance(filas, types.GeneratorType) and list(filas) == [{"RUT": "1", "Nombre": "a"}]
    assert lectores.leer_tabla(buf.getvalue(), "xlsx")[1] == [{"RUT": "1", "Nombre": "a"}]


def test_memoria_del_proceso():
    from app import memoria

    assert memoria.rss_mb() > 0


# ─── R2 · Latido, dueño y retomar ───

def test_latido_mientras_corre(sql, monkeypatch):
    from app import settings, tareas
    from app.db import conexion

    monkeypatch.setattr(settings, "TAREA_LATIDO_SEGUNDOS", 0.05)
    liberar = threading.Event()

    @tareas.handler("prueba.lenta")
    def _lenta(conn, payload, tarea_id):
        liberar.wait(5)
        return {"ok": True}

    with conexion() as c:
        tid = tareas.crear(c, "prueba.lenta", {}, "prueba")
    hilo = threading.Thread(target=tareas.ejecutar, args=(tid,))
    hilo.start()
    time.sleep(0.15)
    t1 = sql.execute("SELECT actualizado, dueno FROM tarea WHERE id = %s", (tid,)).fetchone()
    time.sleep(0.25)
    t2 = sql.execute("SELECT actualizado, estado FROM tarea WHERE id = %s", (tid,)).fetchone()
    liberar.set()
    hilo.join(5)
    assert t1["dueno"] and t2["estado"] == "corriendo" and t2["actualizado"] > t1["actualizado"]   # una tarea viva late
    assert sql.execute("SELECT estado, dueno FROM tarea WHERE id = %s", (tid,)).fetchone() == {"estado": "ok", "dueno": None}


def test_retoma_una_tarea_sin_latido_y_no_una_viva(api, sql):
    from app import tareas
    from app.db import conexion

    @tareas.handler("prueba.eco")
    def _eco(conn, payload, tarea_id):
        return {"eco": payload["x"]}

    with conexion() as c:
        tid = tareas.crear(c, "prueba.eco", {"x": 7}, "prueba")
    sql.execute("UPDATE tarea SET estado = 'corriendo', actualizado = now() - interval '30 seconds' WHERE id = %s", (tid,))
    r = api.c.post(f"/api/tareas/{tid}/ejecutar", headers=TOKEN)
    assert r.status_code == 503                                   # viva: Cloud Tasks reintenta más tarde
    sql.execute("UPDATE tarea SET actualizado = now() - interval '4 minutes' WHERE id = %s", (tid,))
    r = api.c.post(f"/api/tareas/{tid}/ejecutar", headers=TOKEN)
    assert r.status_code == 200 and r.json()["resultado"] == {"eco": 7}   # sin latido hace 4 min: se retoma
    assert api.c.post(f"/api/tareas/{tid}/ejecutar", headers=TOKEN).json() == {"resultado": None}   # ya terminó


def test_si_muere_el_proceso_en_el_lote_3_sigue_sola(api, sql, monkeypatch):
    """Criterio R2: se mata el proceso que corre el lote 3 de 10; el reintento de Cloud Tasks lo retoma y la carga
    termina con los mismos conteos que sin corte."""
    c = cargar(api, [fila(i) for i in range(20)], confirmar=False)
    assert c["lotes"] == 10

    def morir():
        raise Muerte()
    _en_el_lote(monkeypatch, 3, morir)
    with pytest.raises(Muerte):
        api.post(f"/cargas/{c['id']}/confirmar", rol="steward")
    monkeypatch.undo()
    tid = api.get(f"/cargas/{c['id']}").json()["tarea"]["id"]
    assert sql.execute("SELECT estado FROM tarea WHERE id = %s", (tid,)).fetchone()["estado"] == "corriendo"
    assert cuenta(sql, "carga_lote", f"carga_id = {c['id']} AND estado = 'aplicado'") == 2   # el lote 3 se revirtió
    assert api.c.post(f"/api/tareas/{tid}/ejecutar", headers=TOKEN).status_code == 503        # reintento temprano
    sql.execute("UPDATE tarea SET actualizado = now() - interval '4 minutes' WHERE id = %s", (tid,))
    assert api.c.post(f"/api/tareas/{tid}/ejecutar", headers=TOKEN).status_code == 200        # reintento que la retoma
    x = api.get(f"/cargas/{c['id']}").json()
    assert x["estado"] == "confirmada" and x["lotes_detalle"]["aplicados"] == 10
    assert {k: x["conteos"].get(k) for k in CLAVES} == {k: c["conteos"].get(k) for k in CLAVES}
    assert cuenta(sql, "empresa") == 20 and cuenta(sql, "telefono_vinculo") == 20


def test_un_despliegue_no_deja_la_carga_interrumpida(api, sql, monkeypatch, apagado):
    """SIGTERM a mitad del lote 3: el lote se revierte, la tarea vuelve a la cola y la toma la revisión nueva."""
    tareas = apagado
    c = cargar(api, [fila(i) for i in range(20)], confirmar=False)
    _en_el_lote(monkeypatch, 3, tareas.apagar)
    r = api.post(f"/cargas/{c['id']}/confirmar", rol="steward")
    assert r.status_code == 200
    monkeypatch.undo()
    x = api.get(f"/cargas/{c['id']}").json()
    assert x["estado"] == "en_proceso" and x["lotes_detalle"]["aplicados"] == 2
    t = sql.execute("SELECT estado, dueno, reintentos_auto FROM tarea WHERE id = %s", (x["tarea"]["id"],)).fetchone()
    assert t == {"estado": "pendiente", "dueno": None, "reintentos_auto": 0}   # libre para que la tome otra instancia
    tareas._apagando.clear()                                            # la revisión nueva
    tareas.despachar(x["tarea"]["id"])
    x = api.get(f"/cargas/{c['id']}").json()
    assert x["estado"] == "confirmada" and {k: x["conteos"].get(k) for k in CLAVES} == {k: c["conteos"].get(k) for k in CLAVES}


def test_un_lote_largo_con_latido_no_esta_trabado(api, sql, monkeypatch):
    from app import lotes, tareas

    c = cargar(api, [fila(i) for i in range(4)], confirmar=False)
    monkeypatch.setattr(tareas, "despachar", lambda tid, demora=0: None)
    tid = api.post(f"/cargas/{c['id']}/confirmar", rol="steward").json()["tarea_id"]
    monkeypatch.undo()
    # un lote que empezó hace 8 minutos y sigue latiendo
    sql.execute("UPDATE tarea SET estado = 'corriendo', paso_inicio = now() - interval '8 minutes', actualizado = now()"
                " WHERE id = %s", (tid,))
    assert lotes.revisar_trabadas() == []
    assert api.get(f"/cargas/{c['id']}").json()["estado"] == "en_proceso"
    t = api.get(f"/tareas/{tid}").json()
    assert 470 <= t["segundos_paso"] <= 600                              # R4: la pantalla muestra cuánto lleva


def test_avance_fila_a_fila_dentro_del_lote(api, monkeypatch):
    from app import settings, tareas

    monkeypatch.setattr(settings, "CARGAS_TAMANO_LOTE", 600)
    vistos = []
    original = tareas.mensaje
    monkeypatch.setattr(tareas, "mensaje", lambda tid, texto: vistos.append(texto) or original(tid, texto))
    cargar(api, [fila(i) for i in range(502)])
    assert "Lote 1 de 1 · fila 500 de 502" in vistos


# ─── R3 · Migraciones ───

def test_aviso_de_migraciones_faltantes(api, sql):
    from app import migraciones

    assert migraciones.faltantes(cache_segundos=0) == []
    assert "aviso_migraciones" not in api.get("/me").json()
    sql.execute("DELETE FROM public.empresas_migraciones WHERE nombre LIKE '0017%%'")
    falta = migraciones.faltantes(cache_segundos=0)
    assert falta == [n for n in migraciones.del_codigo() if n.startswith("0017")]
    me = api.get("/me").json()
    assert me["migraciones_faltantes"] == falta and "Faltan migraciones: 0017" in me["aviso_migraciones"]
    assert "aviso_migraciones" not in api.get("/me", rol="steward").json()   # solo a los administradores
    migraciones._cache = (0.0, [])
