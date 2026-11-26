"""Estudios, partes, muestras y CSV para uContact (R1.5, R1.6, R1.7)."""
import csv as csvmod
import datetime as dt
import io
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .. import borrado, config, criterios as crit, exportacion, muestras, tamanos_excel, tareas, templates
from ..auth import Usuario, requiere, usuario_actual
from ..db import conexion, get_conn

router = APIRouter()


class NuevaParte(BaseModel):
    nombre: str
    survey_id: str | None = None
    link_base: str | None = None
    respondente_objetivo: str | None = None


class EdicionParte(BaseModel):
    nombre: str | None = None
    survey_id: str | None = None
    link_base: str | None = None
    respondente_objetivo: str | None = None


class NuevoEstudio(BaseModel):
    nombre: str
    cliente: str | None = None
    campo_desde: dt.date
    campo_hasta: dt.date
    partes: list[NuevaParte] = []


class EdicionEstudio(BaseModel):
    nombre: str | None = None
    cliente: str | None = None
    campo_desde: dt.date | None = None
    campo_hasta: dt.date | None = None


@router.get("/estudios")
def listar(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return conn.execute(
        "SELECT e.*, (SELECT count(*) FROM parte p WHERE p.estudio_id = e.id) AS n_partes,"
        " (SELECT count(*) FROM muestra m WHERE m.estudio_id = e.id) AS n_muestras,"
        " (SELECT count(*) FROM muestra m WHERE m.estudio_id = e.id AND m.estado = 'activa') AS muestras_activas"
        " FROM estudio e ORDER BY e.campo_desde DESC, e.id DESC").fetchall()


@router.post("/estudios")
def crear(body: NuevoEstudio, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return muestras.crear_estudio(conn, body.model_dump(), u.email)


@router.get("/estudios/{estudio_id}")
def detalle(estudio_id: int, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return muestras.estudio_detalle(conn, estudio_id)


@router.get("/estudios/{estudio_id}/borrado")
def conteos_borrado_estudio(estudio_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    """Lo que se borraría con el estudio (para el modal de confirmación)."""
    return borrado.conteos_estudio(conn, estudio_id)


@router.delete("/estudios/{estudio_id}")
def borrar_estudio(estudio_id: int, u: Usuario = Depends(requiere("admin"))):
    """Borrado definitivo del estudio con sus partes, muestras e ingestas .sav (corre como tarea)."""
    with conexion() as conn:
        tid = borrado.pedir_borrado_estudio(conn, estudio_id, u.email)
    tareas.despachar(tid)
    return {"tarea_id": tid}


@router.patch("/estudios/{estudio_id}")
def editar(estudio_id: int, body: EdicionEstudio, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return muestras.actualizar_estudio(conn, estudio_id, body.model_dump(exclude_none=True), u.email)


@router.post("/estudios/{estudio_id}/partes")
def crear_parte(estudio_id: int, body: NuevaParte, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return muestras.crear_parte(conn, estudio_id, body.model_dump(), u.email)


@router.patch("/partes/{parte_id}")
def editar_parte(parte_id: int, body: EdicionParte, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return muestras.actualizar_parte(conn, parte_id, body.model_dump(exclude_none=True), u.email)


@router.get("/partes")
def partes(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return conn.execute(
        "SELECT p.id, p.nombre, p.survey_id, p.estudio_id, e.nombre AS estudio_nombre, (p.plantilla_mapeo IS NOT NULL) AS tiene_plantilla"
        " FROM parte p JOIN estudio e ON e.id = p.estudio_id ORDER BY e.campo_desde DESC, p.id").fetchall()


class NuevaMuestra(BaseModel):
    estudio_id: int
    nombre: str
    criterios: dict
    template_id: int | None = None   # R2: de qué template partió (la muestra guarda su propia copia)


@router.post("/muestras")
def crear_muestra(body: NuevaMuestra, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return muestras.crear_muestra(conn, body.estudio_id, body.nombre, body.criterios, u.email, body.template_id)


# ── R4: datos disponibles para filtrar y estratificar ──

@router.get("/muestras/datos-sorteo")
def datos_sorteo(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    """Campos fijos y atributos de empresa activos (nunca de contacto), con su tipo y opciones."""
    defs = crit.definiciones(conn)
    _, cfg = config.vigente(conn)

    def distintos(sql):
        return [r["v"] for r in conn.execute(
            f"SELECT DISTINCT {sql} AS v FROM empresa e LEFT JOIN naturaleza_juridica n ON n.id = e.naturaleza_id"
            f" WHERE e.baja IS NULL AND {sql} IS NOT NULL AND {sql}::text <> '' ORDER BY 1 LIMIT 500")]
    datos = []
    for k, m in defs.items():
        d = {x: m.get(x) for x in ("clave", "nombre", "tipo", "grupo", "opciones")}
        if m["tipo"] == "lista" and d["opciones"] is None:
            d["opciones"] = distintos(m["sql"])
        datos.append(d)
    return {"datos": datos,
            "naturalezas": conn.execute("SELECT codigo, nombre, excluida FROM naturaleza_juridica ORDER BY nombre").fetchall(),
            "regla_sin_telefono": bool((cfg.get("reglas_disponibilidad") or {}).get("sin_telefono_discable", True))}


@router.get("/muestras/valores-dato")
def valores_dato(dato: str, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    """Para «Es uno de…»: los valores existentes de un dato de texto (sin mayúsculas ni tildes), con cuántas
    empresas tienen cada uno, hasta 200."""
    defs = crit.definiciones(conn)
    if dato not in defs:
        raise HTTPException(422, f"Dato desconocido: {dato}")
    q = crit.Consulta(defs)
    x = q.expr(dato)
    return conn.execute(
        f"SELECT mode() WITHIN GROUP (ORDER BY btrim({x}::text)) AS valor, count(*) AS empresas FROM empresa e"
        " LEFT JOIN naturaleza_juridica n ON n.id = e.naturaleza_id " + " ".join(q.joins.values())
        + f" WHERE e.baja IS NULL AND norm_txt({x}::text) IS NOT NULL GROUP BY norm_txt({x}::text)"
        " ORDER BY 2 DESC, 1 LIMIT 200").fetchall()


class Tramos(BaseModel):
    dato: str
    criterios: dict | None = None
    n: int = 4


@router.post("/muestras/tramos")
def tramos(body: Tramos, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    """Tramos sugeridos para estratificar un dato numérico: cuartiles del marco o tramos iguales."""
    defs = crit.definiciones(conn)
    if body.dato not in defs or defs[body.dato]["tipo"] != "numero":
        raise HTTPException(422, "Los tramos se sugieren para un dato numérico")
    c = muestras._validar_criterios(conn, {**(body.criterios or {}), "estratificar_por": []}, [], tamanos=False)
    universo = {f["id"] for f in muestras._universo(conn, c, defs)}
    q = crit.Consulta(defs)
    x = q.expr(body.dato)
    vals = sorted(r["v"] for r in conn.execute(
        f"SELECT {x} AS v FROM empresa e " + " ".join(q.joins.values()) + f" WHERE e.id = ANY(%s) AND {x} IS NOT NULL",
        (list(universo),)))
    if not vals:
        return {"cuartiles": [], "iguales": [], "min": None, "max": None, "n": 0}
    n = max(2, min(body.n, 10))
    cuant = sorted({vals[int(len(vals) * k / n)] for k in range(n)})
    lo, hi = vals[0], vals[-1]
    paso = (hi - lo) / n if hi > lo else 1
    iguales = sorted({lo + paso * k for k in range(n)})
    fmt = lambda v: format(v.normalize(), "f") if hasattr(v, "normalize") else str(v)  # noqa: E731
    redondear = lambda v: v.to_integral_value() if all(x == x.to_integral_value() for x in vals[:200]) else v  # noqa: E731
    return {"cuartiles": [fmt(redondear(v)) for v in cuant], "iguales": sorted({fmt(redondear(v)) for v in iguales}, key=float),
            "min": fmt(lo), "max": fmt(hi), "n": len(vals)}


# ── R2: templates de sorteo (jefe y administrador) ──

class Template(BaseModel):
    nombre: str | None = None
    descripcion: str | None = None
    criterios: dict | None = None
    activo: bool | None = None


@router.get("/muestra-templates")
def listar_templates(activos: bool | None = None, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return templates.listar(conn, activos)


@router.post("/muestra-templates")
def crear_template(body: Template, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return templates.crear(conn, body.nombre, body.descripcion, body.criterios or {}, u.email)


@router.get("/muestra-templates/{template_id}")
def ver_template(template_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return templates.obtener(conn, template_id)


@router.put("/muestra-templates/{template_id}")
def editar_template(template_id: int, body: Template, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return templates.editar(conn, template_id, body.model_dump(exclude_unset=True), u.email)


@router.post("/muestra-templates/{template_id}/duplicar")
def duplicar_template(template_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return templates.duplicar(conn, template_id, u.email)


@router.delete("/muestra-templates/{template_id}")
def borrar_template(template_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return templates.borrar(conn, template_id, u.email)


@router.post("/muestra-templates/{template_id}/aplicar")
def aplicar_template(template_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    """Criterios revalidados con las reglas actuales, avisos de lo que se sacó y el marco por estrato."""
    return templates.aplicar(conn, template_id)


class DesdeMuestra(BaseModel):
    nombre: str
    descripcion: str | None = None


@router.post("/muestras/{muestra_id}/template")
def template_desde_muestra(muestra_id: int, body: DesdeMuestra, conn=Depends(get_conn),
                           u: Usuario = Depends(requiere("jefe"))):
    """«Guardar configuración como template» desde el detalle de una muestra ya creada."""
    return templates.desde_muestra(conn, muestra_id, body.nombre, body.descripcion, u.email)


@router.post("/muestras/marco")
def marco(criterios: dict, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    """Previsualiza el marco sin sortear: por estrato, total, sorteables, no sorteables y motivos (D56)."""
    return muestras.previsualizar_marco(conn, criterios)


# ── D56 · Excel de tamaños, no sorteables y reemplazo de un titular ──

class PedidoExcel(BaseModel):
    criterios: dict
    estudio_id: int | None = None
    muestra_id: int | None = None
    nombre: str | None = None        # nombre de la muestra (o del template) para el archivo


def _excel(conn, criterios: dict, estratos: list[dict], estudio: str | None, nombre: str | None, meta: dict) -> Response:
    defs = crit.definiciones(conn)
    r = templates.resumen(criterios, defs)
    lineas = [f"Filtros: {', '.join(r['filtros']) or 'ninguno (toda la base)'}",
              f"Estratos: {' × '.join(r['estratos']) or 'un único estrato «Total»'}",
              "Incluye la base provisoria" if criterios.get("incluir_provisoria") else "Solo la base definitiva",
              "Como máximo una empresa por grupo económico" if criterios.get("una_por_grupo") else ""]
    tam = {e["estrato"]: (int(e.get("n", 0)), int(e.get("reemplazos", 0))) for e in criterios.get("estratos") or []}
    if not tam and criterios.get("n_por_estrato") is not None:
        tam = {e["estrato"]: (int(criterios["n_por_estrato"]), int(criterios.get("reemplazos_por_estrato") or 0))
               for e in estratos}
    contenido = tamanos_excel.armar(estratos, criterios, tam, meta, [x for x in lineas if x])
    return Response(content=contenido,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{tamanos_excel.nombre_archivo(estudio, nombre)}"'})


@router.post("/muestras/marco/tamanos.xlsx")
def tamanos_xlsx(body: PedidoExcel, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    """R2: el Excel del paso 3, con los criterios del asistente (aunque la muestra todavía no exista)."""
    prev = muestras.previsualizar_marco(conn, body.criterios)
    criterios = {**prev["criterios"], **{k: body.criterios[k] for k in ("estratos", "n_por_estrato", "reemplazos_por_estrato")
                                          if k in body.criterios}}
    estudio = None
    if body.estudio_id:
        e = conn.execute("SELECT nombre FROM estudio WHERE id = %s", (body.estudio_id,)).fetchone()
        estudio = e["nombre"] if e else None
    return _excel(conn, criterios, prev["estratos"], estudio, body.nombre,
                  {"estudio_id": body.estudio_id, "muestra_id": body.muestra_id})


@router.get("/muestras/{muestra_id}/tamanos.xlsx")
def tamanos_xlsx_muestra(muestra_id: int, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    """El Excel de una muestra (solo lectura una vez sorteada: los números son los del momento del sorteo)."""
    m = conn.execute("SELECT m.*, e.nombre AS estudio FROM muestra m JOIN estudio e ON e.id = m.estudio_id"
                     " WHERE m.id = %s", (muestra_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "Muestra inexistente")
    if m["resultado"]:
        estratos = [{"estrato": x["estrato"], "total": x.get("total", x.get("disponibles", 0)),
                     "sorteables": x.get("disponibles", 0)} for x in m["resultado"].get("estratos") or []]
    else:
        estratos = muestras.previsualizar_marco(conn, m["criterios"])["estratos"]
    return _excel(conn, m["criterios"], estratos, m["estudio"], m["nombre"],
                  {"estudio_id": m["estudio_id"], "muestra_id": muestra_id})


@router.post("/muestras/tamanos/importar")
def tamanos_importar(archivo: UploadFile = File(...), criterios: str = Form(...), conn=Depends(get_conn),
                     u: Usuario = Depends(usuario_actual)):
    """R2: lee el Excel y devuelve los tamaños para la pantalla. No guarda nada."""
    try:
        c = json.loads(criterios)
    except ValueError as e:
        raise HTTPException(422, "Criterios inválidos") from e
    prev = muestras.previsualizar_marco(conn, c)
    return tamanos_excel.importar(archivo.file.read(), {**prev["criterios"], "metodo": c.get("metodo")}, prev["estratos"])


@router.post("/muestras/marco/no-sorteables.csv")
def no_sorteables_csv(criterios: dict, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    """R3: las empresas del marco que no se pueden sortear, con su estrato y su motivo."""
    motivo = lambda x: muestras.MOTIVOS.get(x, x.replace("_", " "))  # noqa: E731
    filas = muestras.no_sorteables(conn, criterios)
    salida = io.StringIO()
    w = csvmod.writer(salida, delimiter=";")
    w.writerow(["rut", "razon_social", "departamento", "ciiu", "estrato", "motivo"])
    for f in filas:
        w.writerow([f["rut"], f["razon_social"], f["departamento"], f["ciiu"], f["estrato"],
                    ", ".join(motivo(x) for x in f["motivos"])])
    return Response(content=salida.getvalue().encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="no_sorteables_{dt.date.today():%Y%m%d}.csv"',
                             "X-Renglones": str(len(filas)), "Access-Control-Expose-Headers": "X-Renglones"})


class LiberarVecino(BaseModel):
    item_id: int
    motivo: str


@router.post("/muestras/{muestra_id}/liberar-vecino")
def liberar_vecino(muestra_id: int, body: LiberarVecino, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    """P1 (D56): libera el reemplazo asignado a un titular (sorteo sistemático)."""
    return muestras.liberar_vecino(conn, muestra_id, body.item_id, body.motivo, u.email)


@router.get("/muestras")
def listar_muestras(estado: str | None = None, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    """Lista de muestras; con estado=activa es la lista a la que lleva el contador de Inicio (F1.1)."""
    return conn.execute(
        "SELECT m.id, m.nombre, m.estado, m.semilla, m.config_version, m.sorteada, m.estudio_id, e.nombre AS estudio_nombre,"
        " (SELECT count(*) FROM muestra_item i WHERE i.muestra_id = m.id) AS n_items,"
        " (SELECT count(*) FROM muestra_item i WHERE i.muestra_id = m.id AND i.liberado) AS n_liberados,"
        " (SELECT t.estado FROM tarea t WHERE t.tipo = 'muestra.borrar' AND (t.payload->>'borrar_muestra_id')::int = m.id"
        "   ORDER BY t.id DESC LIMIT 1) AS tarea_borrado"
        " FROM muestra m JOIN estudio e ON e.id = m.estudio_id"
        " WHERE (%s::text IS NULL OR m.estado = %s) ORDER BY m.id DESC", (estado, estado)).fetchall()


@router.get("/muestras/{muestra_id}")
def detalle_muestra(muestra_id: int, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return muestras.detalle(conn, muestra_id)


@router.get("/muestras/{muestra_id}/borrado")
def conteos_borrado_muestra(muestra_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    """Lo que se borraría con la muestra (para el modal de confirmación)."""
    return borrado.conteos_muestra(conn, muestra_id)


@router.delete("/muestras/{muestra_id}")
def borrar_muestra(muestra_id: int, u: Usuario = Depends(requiere("admin"))):
    """Borrado definitivo de la muestra con sus ítems, intentos del CDR y filas del .sav (corre como tarea)."""
    with conexion() as conn:
        tid = borrado.pedir_borrado_muestra(conn, muestra_id, u.email)
    tareas.despachar(tid)
    return {"tarea_id": tid}


@router.get("/muestras/{muestra_id}/items")
def items(muestra_id: int, estrato: str | None = None, rol: str | None = None, liberado: bool | None = None,
          parte_id: int | None = None, estado: str | None = None, q: str | None = None, pagina: int = 1,
          por_pagina: int = muestras.POR_PAGINA, sin_telefono: bool | None = None, conn=Depends(get_conn),
          u: Usuario = Depends(usuario_actual)):
    return muestras.items(conn, muestra_id, estrato, rol, liberado, parte_id, estado, q, pagina, por_pagina, sin_telefono)


class Sorteo(BaseModel):
    semilla: int | None = None


@router.post("/muestras/{muestra_id}/sortear")
def sortear(muestra_id: int, body: Sorteo | None = None, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return muestras.sortear(conn, muestra_id, u.email, body.semilla if body else None)


@router.post("/muestras/{muestra_id}/verificar")
def verificar(muestra_id: int, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return muestras.verificar(conn, muestra_id)


class Liberacion(BaseModel):
    estrato: str
    cantidad: int = 1
    motivo: str


@router.post("/muestras/{muestra_id}/liberar")
def liberar(muestra_id: int, body: Liberacion, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return muestras.liberar(conn, muestra_id, body.estrato, body.cantidad, body.motivo, u.email)


@router.post("/muestras/{muestra_id}/cerrar")
def cerrar(muestra_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return muestras.cerrar(conn, muestra_id, u.email)


class Exportacion(BaseModel):
    origenes: list[str] | None = None
    orden: str | None = None
    numeros: str | None = None
    atributos_excluidos: list[str] | None = None
    contactos: bool | None = None
    contacto_campos: list[str] | None = None
    atributos_contacto_excluidos: list[str] | None = None


@router.put("/muestras/{muestra_id}/exportacion")
def exportacion_opciones(muestra_id: int, body: Exportacion, conn=Depends(get_conn),
                         u: Usuario = Depends(requiere("coordinador", "jefe"))):
    """Orígenes a exportar y orden de los teléfonos del CSV (queda guardado en la muestra)."""
    return muestras.guardar_exportacion(conn, muestra_id, body.model_dump(exclude_unset=True), u.email)


@router.get("/muestras/{muestra_id}/csv")
def csv(muestra_id: int, parte_id: int, formato: str = "ucontact", conn=Depends(get_conn),
        u: Usuario = Depends(requiere("coordinador", "jefe"))):
    nombre, contenido, resumen = exportacion.generar_csv(conn, muestra_id, parte_id, u, formato)
    return Response(
        content=contenido.encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"',
                 "X-Renglones": str(resumen["renglones"]), "X-Items-Sin-Telefono": str(resumen["items_sin_telefono"]),
                 "X-Contactos-Incluidos": "1" if resumen["con_contactos"] else "0",
                 "Access-Control-Expose-Headers": "X-Renglones, X-Items-Sin-Telefono, X-Contactos-Incluidos"})


@router.get("/muestras/{muestra_id}/csv/resumen")
def csv_resumen(muestra_id: int, parte_id: int, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    filas, ctx = exportacion.filas_csv(conn, muestra_id, parte_id, u.exportar_contactos)
    return {**ctx["resumen"], "columnas": ctx["cfg"]["csv_ucontact"]["columnas"],
            "puede_exportar_contactos": u.exportar_contactos}
