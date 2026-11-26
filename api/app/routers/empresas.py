"""Empresas: buscador, ficha, edición manual, teléfonos, intermediarios y fusiones (R1.1, R1.2, R1.11)."""
import base64
import json
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import actividad, auditoria, borrado, catalogos, config, contactos, disponibilidad, empresas, intermediarios, resumen, rut as rutmod
from ..auth import Usuario, requiere, usuario_actual
from ..db import get_conn

router = APIRouter()


@router.get("/me")
def me(u: Usuario = Depends(usuario_actual)):
    datos = dict(u.__dict__)
    if u.rol == "admin":  # R3 (D52): la web les muestra una franja roja si la base no tiene todas las migraciones
        from .. import migraciones

        faltan = migraciones.faltantes()
        if faltan:
            datos["migraciones_faltantes"] = faltan
            datos["aviso_migraciones"] = migraciones.mensaje(faltan)
    return datos


def join_disponibilidad(guardada: bool) -> str:
    """D55: la disponibilidad guardada (empresa_disponibilidad) o, mientras no está lista, el cálculo anterior."""
    return (" LEFT JOIN empresa_disponibilidad d ON d.empresa_id = e.id" if guardada
            else " JOIN v_empresa_disponible d ON d.empresa_id = e.id")


def filtros_busqueda(conn, q=None, departamento=None, tamano=None, naturaleza=None, disponible=None,
                     base="definitiva", sin_telefono=None, sin_web=None,
                     rut_verificado=None, guardada: bool = False) -> tuple[list[str], list, int | None]:
    """WHERE del buscador de Empresas (lo reusa «Enriquecer estas N empresas»). Devuelve (where, args, ítem).
    «d» es la disponibilidad (join_disponibilidad)."""
    where, args = ["e.baja IS NULL"], []
    prov = empresas.CODIGO_PROVISORIO.match(q or "")
    if base in ("definitiva", "provisoria") and not prov and _item_buscado(q) is None:
        # F6.1: por defecto, solo la base definitiva; «ambas» no filtra. Un código P- o un #ítem van directo.
        where.append("e.base = %s")
        args.append(base)
    if prov:
        where.append("e.id = %s AND e.rut IS NULL")
        args.append(int(prov.group(1)))
        q = None
    item = _item_buscado(q)
    if item is not None:
        # F1.4: «#1234» o «item:1234» busca por EC_ID_ITEM; si la empresa se fusionó, lleva a la que la absorbió
        fila = conn.execute(
            "WITH RECURSIVE c AS (SELECT e.id, e.fusionada_en, 0 AS n FROM muestra_item i JOIN empresa e ON e.id = i.empresa_id"
            "  WHERE i.id = %s UNION ALL SELECT e.id, e.fusionada_en, c.n + 1 FROM c JOIN empresa e ON e.id = c.fusionada_en"
            "  WHERE c.n < 20) SELECT id FROM c ORDER BY n DESC LIMIT 1", (item,)).fetchone()
        where.append("e.id = %s")
        args.append(fila["id"] if fila else -1)
        q = None
    if q:
        digitos = "".join(ch for ch in q if ch.isdigit())
        if len(digitos) >= 4 and len(digitos) == len(q.replace(".", "").replace("-", "").replace(" ", "")):
            where.append("e.rut LIKE %s")
            args.append(f"%{digitos}%")
        else:
            where.append("(e.razon_social ILIKE %s OR e.fantasia ILIKE %s)")
            args += [f"%{q}%", f"%{q}%"]
    if departamento:
        where.append("e.departamento = %s")
        args.append(departamento)
    if tamano:
        where.append("e.tamano = %s")
        args.append(tamano)
    if naturaleza:
        where.append("n.codigo = %s")
        args.append(naturaleza)
    if disponible is not None:
        where.append("d.disponible = %s")
        args.append(disponible)
    if sin_telefono is not None and guardada:  # D55: la cantidad guardada, sin recorrer los vínculos
        where.append("coalesce(d.telefonos_discables, 0) " + ("= 0" if sin_telefono else "> 0"))
    elif sin_telefono is not None:  # Fase 2: para enriquecer una lista filtrada
        where.append(("NOT " if sin_telefono else "") + "EXISTS (SELECT 1 FROM v_vinculo_discable x WHERE x.empresa_id = e.id)")
    if sin_web is not None:
        where.append("coalesce(e.web, '') = ''" if sin_web else "coalesce(e.web, '') <> ''")
    if rut_verificado is not None:  # D54: RUT de 12 dígitos validado o identificador aceptado sin validar
        where.append("e.rut_verificado = %s")
        args.append(rut_verificado)
    return where, args, item


POR_PAGINA = 50
# Orden del buscador; el índice empresa_orden_buscador_idx (0021) lo sigue, y la paginación por clave lo compara
_ORDEN = "(e.razon_social IS NULL), coalesce(e.razon_social, ''), e.codigo"
TOTAL_EXACTO_HASTA = 5000   # con un estimado menor, el total exacto es barato y se cuenta


def _cursor(fila: dict) -> str:
    clave = [fila["razon_social"] is None, fila["razon_social"] or "", fila["rut"]]
    return base64.urlsafe_b64encode(json.dumps(clave).encode()).decode().rstrip("=")


def _leer_cursor(texto: str) -> list:
    try:
        clave = json.loads(base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4)))
        assert isinstance(clave, list) and len(clave) == 3
        return [bool(clave[0]), str(clave[1]), str(clave[2])]
    except Exception as e:
        raise HTTPException(422, "Página inválida: volvé a buscar") from e


def estimar(conn, sql: str, args) -> int:
    """Filas que el planificador espera para la consulta (sin ejecutarla)."""
    plan = conn.execute("EXPLAIN (FORMAT JSON) " + sql, args).fetchone()
    plan = plan[next(iter(plan))]
    return int((plan[0] if isinstance(plan, list) else json.loads(plan)[0])["Plan"]["Plan Rows"])


def _total(conn, desde: str, where: list[str], args: list, base: str, filas: int, primera: bool, hay_mas: bool,
           exacto: bool) -> tuple[int, bool]:
    """P-3 (D55): sin count(*) OVER (). Exacto cuando es barato (una sola página, un estimado chico o lo pide el
    botón); si no, el contador guardado (sin filtros) o el estimado del planificador, marcados como aproximados."""
    if primera and not hay_mas:
        return filas, False
    sql = f"SELECT 1 {desde} WHERE {' AND '.join(where)}"
    if not exacto:
        n = None
        if where == ["e.baja IS NULL", "e.base = %s"] and base in ("definitiva", "provisoria"):
            n = (resumen.leer(conn, "inicio")["valor"] or {}).get("empresas" if base == "definitiva" else "provisorias")
        n = int(n) if n is not None else estimar(conn, sql, args)
        if n > TOTAL_EXACTO_HASTA:
            return n, True
    return conn.execute(f"SELECT count(*) AS n FROM ({sql}) x", args).fetchone()["n"], False


@router.get("/empresas")
def buscar(q: str | None = None, departamento: str | None = None, tamano: str | None = None,
           naturaleza: str | None = None, disponible: bool | None = None, pagina: int = 1, base: str = "definitiva",
           sin_telefono: bool | None = None, sin_web: bool | None = None, rut_verificado: bool | None = None,
           despues: str | None = None, exacto: bool = False,
           conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    """Buscador (D55): disponibilidad guardada, teléfonos discables guardados, página siguiente por clave («despues»,
    igual de rápida en la página 50 que en la 1) y total exacto solo cuando es barato o con «exacto»."""
    guardada = disponibilidad.asegurar(conn)
    where, args, item = filtros_busqueda(conn, q, departamento, tamano, naturaleza, disponible, base, sin_telefono, sin_web,
                                         rut_verificado, guardada=guardada)
    pagina = max(1, pagina)
    desde = " FROM empresa e LEFT JOIN naturaleza_juridica n ON n.id = e.naturaleza_id" + join_disponibilidad(guardada)
    tels = ("coalesce(d.telefonos_discables, 0)" if guardada
            else "(SELECT count(*) FROM v_vinculo_discable x WHERE x.empresa_id = e.id)")
    w, a, offset = list(where), list(args), (pagina - 1) * POR_PAGINA
    if despues:
        w.append(f"({_ORDEN}) > (%s, %s, %s)")
        a += _leer_cursor(despues)
        offset = 0
    filas = conn.execute(
        "SELECT e.id, e.codigo AS rut, e.base, e.rut_verificado, e.razon_social, e.fantasia, e.departamento, e.tamano,"
        " e.ciiu, e.estado, n.codigo AS naturaleza, e.ultimo_contacto_efectivo, d.disponible, d.reglas, d.hasta,"
        f" {tels} AS telefonos_discables{desde} WHERE {' AND '.join(w)} ORDER BY {_ORDEN} LIMIT %s OFFSET %s",
        (*a, POR_PAGINA + 1, offset)).fetchall()
    hay_mas = len(filas) > POR_PAGINA
    filas = filas[:POR_PAGINA]
    total, aproximado = _total(conn, desde, where, args, base, len(filas), pagina == 1 and not despues, hay_mas, exacto)
    return {"total": total, "aproximado": aproximado, "pagina": pagina, "empresas": filas, "item": item,
            "siguiente": _cursor(filas[-1]) if hay_mas else None, "disponibilidad_al_dia": guardada}


def _item_buscado(q: str | None) -> int | None:
    m = re.fullmatch(r"\s*(?:#|item:)\s*(\d{1,9})\s*", q or "", re.IGNORECASE)
    return int(m.group(1)) if m else None


@router.get("/empresas/valores")
def valores_filtro(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    """Valores distintos para los filtros de búsqueda y de muestra. D55: precalculados (resumen_base), con la cantidad
    de empresas de cada uno y la fecha en que se calcularon."""
    r = resumen.leer(conn, "valores")
    v = r["valor"]
    salida = {k: [x["valor"] for x in v.get(k, [])] for k in ("departamento", "tamano", "ciiu2", "localidad")}
    salida["cantidades"] = {k: {x["valor"]: x["n"] for x in v.get(k, [])} for k in ("departamento", "tamano", "ciiu2")}
    salida["naturaleza"] = conn.execute("SELECT codigo, nombre, excluida FROM naturaleza_juridica ORDER BY nombre").fetchall()
    salida["actualizado"], salida["al_dia"] = r["actualizado"], r["al_dia"]
    return salida


@router.delete("/empresas/{rut}")
def borrar(rut: str, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    """Borrado definitivo (solo administrador). Queda solo el registro en Auditoría."""
    return borrado.borrar_empresa(conn, rut, u.email)


@router.get("/empresas/{rut}")
def ficha(rut: str, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    e = empresas.obtener_o_404(conn, rut)
    eid = e["id"]
    e["naturaleza"] = conn.execute("SELECT codigo, nombre, excluida FROM naturaleza_juridica WHERE id = %s",
                                   (e["naturaleza_id"],)).fetchone() if e["naturaleza_id"] else None
    if e["fusionada_en"]:
        e["fusionada_en_rut"] = conn.execute("SELECT codigo FROM empresa WHERE id = %s", (e["fusionada_en"],)).fetchone()["codigo"]
    # D55: las mismas reglas que bloqueos(cfg), calculadas al momento solo para esta empresa
    d = disponibilidad.calcular(conn, [eid])
    e["disponibilidad"] = {k: d[0][k] for k in ("disponible", "reglas", "hasta")} if d else None
    e["historia"] = conn.execute(
        "SELECT h.id, h.campo, h.valor, h.fuente_tipo, h.fuente_id, h.confianza, h.actor, h.fecha, h.detalle,"
        " (coalesce(" + empresas.CARGA_SIN_EFECTO + ", false) OR f.deshecha IS NOT NULL OR ec.deshecha IS NOT NULL) AS anulada,"
        " (h.fuente_tipo IN ('sav', 'sala') AND h.fuente_id IS NOT NULL"
        "  AND NOT EXISTS (SELECT 1 FROM sav_ingesta s WHERE s.id = h.fuente_id)) AS ingesta_borrada"
        " FROM empresa_campo_historia h LEFT JOIN carga c ON h.fuente_tipo = 'carga' AND c.id = h.fuente_id"
        " LEFT JOIN empresa_fusion f ON h.fuente_tipo = 'fusion' AND f.id = h.fuente_id"
        " LEFT JOIN enriquecimiento_corrida ec ON h.fuente_tipo IN ('enriquecimiento', 'descubrimiento') AND ec.id = h.fuente_id"
        " WHERE h.empresa_id = %s ORDER BY h.campo, h.fecha DESC, h.id DESC", (eid,)).fetchall()
    # Fase 2 (B4): grupo económico y las otras empresas que lo forman
    e["grupo"] = None
    if e.get("grupo_economico_id"):
        from .. import duplicados
        e["grupo"] = duplicados.grupo(conn, e["grupo_economico_id"])
    vig = empresas.vigentes(conn, eid)
    for h in e["historia"]:
        h["vigente"] = bool(vig.get(h["campo"]) and vig[h["campo"]]["id"] == h["id"])
    e["telefonos"] = conn.execute(
        "SELECT v.id AS vinculo_id, t.id AS telefono_id, t.e164, t.crudo, t.tipo, t.estado AS estado_telefono,"
        " t.intermediario, v.estado, v.fuente_tipo, v.fecha, c.nombre AS contacto,"
        " (SELECT count(DISTINCT v2.empresa_id) FROM telefono_vinculo v2 WHERE v2.telefono_id = t.id) AS n_empresas,"
        " (SELECT count(*) FROM intento i WHERE i.telefono_id = t.id) AS intentos,"
        " (SELECT max(inicio) FROM intento i WHERE i.telefono_id = t.id) AS ultimo_intento,"
        " EXISTS (SELECT 1 FROM v_vinculo_discable d WHERE d.vinculo_id = v.id) AS discable,"
        " EXISTS (SELECT 1 FROM no_llamar n WHERE n.activo AND n.alcance = 'telefono' AND n.objeto_id = t.id) AS no_llamar,"
        " (SELECT coalesce(json_agg(json_build_object('codigo', o.codigo, 'nombre', o.nombre, 'fuente_tipo', x.fuente_tipo,"
        "   'fuente_id', x.fuente_id, 'fecha', x.fecha,"
        # D57: la página fuente de un teléfono enriquecido (búsqueda web con Claude o sitio web)
        "   'url', (SELECT h.detalle->>'url' FROM telefono_vinculo_historia h WHERE h.vinculo_id = v.id"
        "     AND h.fuente_tipo = x.fuente_tipo AND h.fuente_id IS NOT DISTINCT FROM x.fuente_id AND h.detalle ? 'url'"
        "     ORDER BY h.id DESC LIMIT 1)) ORDER BY o.prioridad), '[]'::json)"
        "   FROM telefono_vinculo_origen x JOIN origen_telefono o ON o.id = x.origen_id WHERE x.vinculo_id = v.id) AS origenes"
        " FROM telefono_vinculo v JOIN telefono t ON t.id = v.telefono_id LEFT JOIN contacto c ON c.id = v.contacto_id"
        " WHERE v.empresa_id = %s ORDER BY discable DESC, t.e164", (eid,)).fetchall()
    if u.rol == "lectura":
        e["contactos"] = [{"id": None, "nombre": "(dato personal oculto)", "cargo": None, "area": None, "email": None,
                           "telefonos": [], "atributos": []}
                          for _ in conn.execute("SELECT 1 FROM contacto WHERE empresa_id = %s", (eid,))]
        for t in e["telefonos"]:
            t["contacto"] = None
    else:
        e["contactos"] = conn.execute(
            "SELECT c.*, concat_ws(', ', s.direccion, s.localidad, s.departamento) AS sucursal, EXISTS (SELECT 1 FROM no_llamar n WHERE n.activo AND n.alcance = 'contacto'"
            " AND n.objeto_id = c.id) AS no_llamar FROM contacto c LEFT JOIN sucursal s ON s.id = c.sucursal_id"
            " WHERE c.empresa_id = %s ORDER BY c.actualizado DESC", (eid,)).fetchall()
        tels = contactos.telefonos(conn, [c["id"] for c in e["contactos"]])
        attrs = catalogos.atributos_de_contactos(conn, [c["id"] for c in e["contactos"]])
        for c in e["contactos"]:
            c["telefonos"] = tels.get(c["id"], [])
            c["atributos"] = attrs.get(c["id"], [])
    e["atributos"] = catalogos.atributos_de_empresa(conn, eid)
    e["sucursales"] = conn.execute("SELECT * FROM sucursal WHERE empresa_id = %s ORDER BY id", (eid,)).fetchall()
    e["muestras"] = conn.execute(
        "SELECT mi.id AS item_id, m.id AS muestra_id, m.nombre, m.estado, mi.estrato, mi.rol, mi.liberado, s.nombre AS estudio"
        " FROM muestra_item mi JOIN muestra m ON m.id = mi.muestra_id JOIN estudio s ON s.id = m.estudio_id"
        " WHERE mi.empresa_id = %s OR mi.empresa_id IN (WITH RECURSIVE f AS ("
        "   SELECT id FROM empresa WHERE fusionada_en = %s"
        "   UNION SELECT e.id FROM empresa e JOIN f ON e.fusionada_en = f.id) SELECT id FROM f)"
        " ORDER BY m.id DESC", (eid, eid)).fetchall()
    e["fusiones"] = conn.execute(
        "SELECT f.*, a.codigo AS absorbente_rut, b.codigo AS absorbida_rut, b.base AS absorbida_base FROM empresa_fusion f"
        " JOIN empresa a ON a.id = f.absorbente_id JOIN empresa b ON b.id = f.absorbida_id"
        " WHERE f.absorbente_id = %s OR f.absorbida_id = %s ORDER BY f.id DESC", (eid, eid)).fetchall()
    e["no_llamar"] = conn.execute("SELECT * FROM no_llamar WHERE alcance = 'empresa' AND objeto_id = %s ORDER BY id DESC",
                                  (eid,)).fetchall()
    e["linea_de_tiempo"] = actividad.linea_de_tiempo(conn, eid, ver_contactos=u.rol != "lectura")
    return e


class EdicionEmpresa(BaseModel):
    valores: dict[str, str | None]
    motivo: str | None = None


@router.patch("/empresas/{rut}")
def editar(rut: str, body: EdicionEmpresa, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    e = empresas.obtener_o_404(conn, rut)
    valores = dict(body.valores)
    desconocidos = set(valores) - set(empresas.CAMPOS)
    if desconocidos:
        raise HTTPException(422, f"Campos no editables: {', '.join(desconocidos)}")
    if "naturaleza" in valores and valores["naturaleza"]:
        cod = empresas.resolver_naturaleza(conn, valores["naturaleza"])
        if cod is None:
            raise HTTPException(422, "Naturaleza jurídica inexistente en el catálogo")
        valores["naturaleza"] = cod
    if valores.get("estado") and valores["estado"] not in empresas.ESTADOS_EMPRESA:
        raise HTTPException(422, "estado: activa | cerrada | desconocida")
    _, cfg = config.vigente(conn)
    cambios, _ = empresas.aplicar_valores(conn, e["id"], valores, "manual", None, cfg["confianza_fuentes"].get("manual", 90),
                                          u.email, {"motivo": body.motivo} if body.motivo else None)
    auditoria.registrar(conn, u.email, "empresa.editar", "empresa", e["codigo"], {"valores": valores, "motivo": body.motivo})
    return {"cambios": {k: {"antes": a, "despues": d} for k, (a, d) in cambios.items()}}


class NuevaEmpresa(BaseModel):
    rut: str
    razon_social: str | None = None
    telefonos: list[str] = []


@router.post("/empresas")
def alta_manual(body: NuevaEmpresa, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    r, motivo = rutmod.validar(body.rut, config.rut_cortos(conn))
    if r is None:
        raise HTTPException(422, f"RUT rechazado: {motivo}")
    if conn.execute("SELECT 1 FROM empresa WHERE rut = %s", (r,)).fetchone():
        raise HTTPException(409, "Ya existe una empresa con ese RUT")
    e = conn.execute("INSERT INTO empresa (rut) VALUES (%s) RETURNING *", (r,)).fetchone()
    _, cfg = config.vigente(conn)
    if body.razon_social:
        empresas.aplicar_valores(conn, e["id"], {"razon_social": body.razon_social}, "manual", None,
                                 cfg["confianza_fuentes"].get("manual", 90), u.email)
    for t in body.telefonos:
        fila, _, _ = empresas.telefono(conn, t)
        if fila:
            empresas.vincular(conn, fila["id"], e["id"], "manual", None, u.email)
    auditoria.registrar(conn, u.email, "empresa.alta_manual", "empresa", r)
    return {"rut": r}


class NuevoTelefono(BaseModel):
    numero: str
    contacto_id: int | None = None


@router.post("/empresas/{rut}/telefonos")
def agregar_telefono(rut: str, body: NuevoTelefono, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    e = empresas.obtener_o_404(conn, rut)
    fila, n, _ = empresas.telefono(conn, body.numero)
    if fila is None:
        raise HTTPException(422, "Número vacío")
    v, nuevo = empresas.vincular(conn, fila["id"], e["id"], "manual", None, u.email, contacto_id=body.contacto_id)
    _, cfg = config.vigente(conn)
    sospechoso = intermediarios.detectar(conn, cfg["umbral_intermediario"], [fila["id"]], u.email)
    auditoria.registrar(conn, u.email, "telefono.agregar", "empresa", e["codigo"], {"numero": n.e164 or n.crudo})
    return {"e164": n.e164, "tipo": n.tipo, "motivo": n.motivo, "nuevo_vinculo": nuevo, "sospechoso": bool(sospechoso)}


class EstadoVinculo(BaseModel):
    estado: str
    motivo: str | None = None


@router.post("/vinculos/{vinculo_id}/estado")
def estado_vinculo(vinculo_id: int, body: EstadoVinculo, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    v = conn.execute("SELECT * FROM telefono_vinculo WHERE id = %s", (vinculo_id,)).fetchone()
    if v is None:
        raise HTTPException(404, "Vínculo inexistente")
    if body.estado not in ("sin_verificar", "verificado", "no_corresponde", "intermediario", "inexistente"):
        raise HTTPException(422, "Estado de vínculo inválido")
    cambio = empresas.cambiar_estado_vinculo(conn, v, body.estado, "manual", None, u.email, {"motivo": body.motivo})
    auditoria.registrar(conn, u.email, "vinculo.estado", "telefono_vinculo", vinculo_id,
                        {"estado": body.estado, "motivo": body.motivo})
    return {"cambio": cambio}


class Fusion(BaseModel):
    rut_absorbida: str
    motivo: str | None = None


@router.post("/empresas/{rut}/fusionar")
def fusionar(rut: str, body: Fusion, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    a = empresas.obtener_o_404(conn, rut)
    b = empresas.obtener_o_404(conn, body.rut_absorbida)
    return {"fusion_id": empresas.fusionar(conn, a, b, u.email, body.motivo)}


@router.post("/fusiones/{fusion_id}/deshacer")
def deshacer_fusion(fusion_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    empresas.deshacer_fusion(conn, fusion_id, u.email)
    return {"ok": True}


@router.get("/telefonos/sospechosos")
def sospechosos(estado: str = "sospechoso", conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    if estado not in ("sospechoso", "confirmado", "liberado"):
        raise HTTPException(422, "estado: sospechoso | confirmado | liberado")
    _, cfg = config.vigente(conn)
    return {"umbral": cfg["umbral_intermediario"], "telefonos": intermediarios.sospechosos(conn, estado)}


class Resolucion(BaseModel):
    accion: str
    motivo: str | None = None


@router.post("/telefonos/{telefono_id}/resolver")
def resolver(telefono_id: int, body: Resolucion, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    return intermediarios.resolver(conn, telefono_id, body.accion, u.email, body.motivo)
