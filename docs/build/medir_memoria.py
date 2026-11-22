"""Mide la memoria de la carga de un archivo grande (SPEC_cargas_lotes_robustez, R1; D52).

Genera un .xlsx sintético de 200.000 filas con RUTs válidos y mide, cada fase en un proceso aparte, el pico de memoria
residente (RSS):

1. «lectura»: leer el archivo y guardar sus filas (lo que hace la tarea archivo.leer);
2. «lote preview» y «lote confirmación»: el primer lote de 5.000 filas del preview y de la confirmación.

Como comparación, mide también la lectura de la versión anterior (todas las filas en una lista).
Criterio: ninguna fase pasa de 600 MB.

Uso (con una base de prueba vacía y migrada, por ejemplo la de los tests):

    DATABASE_URL=postgresql://postgres@localhost/empresas_medir python docs/build/medir_memoria.py [filas]
"""
import json
import os
import pathlib
import resource
import subprocess
import sys
import tempfile
import time

RAIZ = pathlib.Path(__file__).resolve().parents[2]
LIMITE_MB = 600


def pico_mb() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024   # Linux: KB


def generar(ruta: str, n: int):
    sys.path.insert(0, str(RAIZ / "api"))
    from openpyxl import Workbook

    from app import rut as rutmod

    wb = Workbook(write_only=True)
    ws = wb.create_sheet()
    ws.append(["RUT", "Razón social", "Teléfono", "Departamento", "Dirección", "Tamaño"])
    i = k = 0
    while k < n:
        base = f"21{100000 + i:06d}001"
        i += 1
        dv = rutmod.digito_verificador(base)
        if dv is None:
            continue
        ws.append([base + str(dv), f"Empresa de prueba número {k}", f"2{4000000 + k:07d}", "Montevideo",
                   f"Calle {k % 900} esquina {k % 77}", "Pyme"])
        k += 1
    wb.save(ruta)


def fase(nombre: str, ruta: str):
    """Corre una fase en este proceso y devuelve su pico de memoria."""
    os.environ.setdefault("AUTH_MODE", "dev")
    os.environ["TASKS_MODE"] = "background"
    os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp(prefix="medir-"))
    sys.path.insert(0, str(RAIZ / "api"))
    from app import cargas, lectores, lotes, storage, tareas
    from app.db import conexion

    tareas.despachar = lambda tid, demora=0: None    # los pasos se corren a mano, de a uno
    datos = pathlib.Path(ruta).read_bytes()
    if nombre == "lectura anterior (lista entera)":
        lectores.leer_tabla(datos, "xlsx")
        return pico_mb()
    if nombre == "lectura":
        with conexion() as conn:
            a = storage.guardar(conn, "medir.xlsx", datos, "medicion")
        del datos
        with conexion() as conn:
            cargas.asegurar_filas(conn, a["id"])
        pathlib.Path(ruta + ".archivo").write_text(str(a["id"]))
        return pico_mb()
    del datos
    archivo_id = int(pathlib.Path(ruta + ".archivo").read_text())
    with conexion() as conn:
        an = cargas.analizar(conn, conn.execute("SELECT * FROM archivo WHERE id = %s", (archivo_id,)).fetchone(), None)
        m = {**an["mapeo"], "origen_defecto": "sin_dato"}
        r = cargas.crear(conn, archivo_id, "medición", "medición", "interna", None, None, m, False, "medicion")
    tid = r["tarea_id"]
    tareas.ejecutar(tid)          # armar los lotes
    tareas.ejecutar(tid)          # lote 1 del preview
    if nombre == "lote preview":
        return pico_mb()
    with conexion() as conn:      # la confirmación arranca por el lote 1 (no hace falta terminar el preview)
        conn.execute("UPDATE carga SET estado = 'en_proceso', operacion = 'confirmar' WHERE id = %s", (r["carga_id"],))
        conn.execute("UPDATE tarea SET tipo = 'carga.confirmar', estado = 'pendiente' WHERE id = %s", (tid,))
    tareas.ejecutar(tid)          # lote 1 de la confirmación
    return pico_mb()


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--fase":
        print(json.dumps({"mb": fase(sys.argv[2], sys.argv[3])}))
        return
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200000
    ruta = os.path.join(tempfile.mkdtemp(prefix="medir-"), f"sintetico_{n}.xlsx")
    t0 = time.monotonic()
    generar(ruta, n)
    print(f"Archivo sintético: {n:,} filas, {os.path.getsize(ruta) / 2 ** 20:.1f} MB ({time.monotonic() - t0:.0f} s)")
    ok = True
    for nombre in ("lectura anterior (lista entera)", "lectura", "lote preview", "lote confirmación"):
        t0 = time.monotonic()
        salida = subprocess.run([sys.executable, __file__, "--fase", nombre, ruta], capture_output=True, text=True,
                                env=os.environ)
        if salida.returncode:
            print(salida.stderr[-2000:])
            sys.exit(f"Falló la fase {nombre}")
        mb = json.loads(salida.stdout.strip().splitlines()[-1])["mb"]
        cumple = mb < LIMITE_MB or nombre.startswith("lectura anterior")
        ok = ok and cumple
        print(f"  {nombre:34s} pico {mb:5d} MB  {time.monotonic() - t0:5.0f} s  "
              f"{'' if nombre.startswith('lectura anterior') else ('ok' if cumple else f'PASA DE {LIMITE_MB} MB')}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
