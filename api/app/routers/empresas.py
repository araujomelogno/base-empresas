"""Empresas: buscador, ficha, edición manual, teléfonos, intermediarios y fusiones (R1.1, R1.2, R1.11)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import actividad, auditoria, config, empresas, intermediarios, rut as rutmod
from ..auth import Usuario, requiere, usuario_actual
from ..db import get_conn

router = APIRouter()


@router.get("/me")
def me(u: Usuario = Depends(usuario_actual)):
    return u.__dict__


@router.get("/empresas")
def buscar(q: str | None = None, departamento: str | None = None, tamano: str | None = None,
           naturaleza: str | None = None, disponible: bool | None = None, pagina: int = 1,
           conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    where, args = ["e.baja IS NULL"], []
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
    pagina = max(1, pagina)
    filas = conn.execute(
        "SELECT e.id, e.rut, e.razon_social, e.fantasia, e.departamento, e.tamano, e.ciiu, e.estado, n.codigo AS naturaleza,"
        " e.ultimo_contacto_efectivo, d.disponible, d.reglas, d.hasta,"
        " (SELECT count(*) FROM v_vinculo_discable x WHERE x.empresa_id = e.id) AS telefonos_discables,"
        " count(*) OVER () AS total"
        " FROM empresa e LEFT JOIN naturaleza_juridica n ON n.id = e.naturaleza_id"
        " JOIN v_empresa_disponible d ON d.empresa_id = e.id"
        f" WHERE {' AND '.join(where)} ORDER BY e.razon_social NULLS LAST, e.rut LIMIT 50 OFFSET %s",
        (*args, (pagina - 1) * 50)).fetchall()
    total = filas[0]["total"] if filas else 0
    return {"total": total, "pagina": pagina, "empresas": filas}


@router.get("/empresas/valores")
def valores_filtro(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    """Valores distintos para los filtros de búsqueda y de muestra."""
    def distintos(col):
        return [r["v"] for r in conn.execute(
            f"SELECT DISTINCT {col} AS v FROM empresa WHERE baja IS NULL AND {col} IS NOT NULL ORDER BY 1")]
    return {"departamento": distintos("departamento"), "tamano": distintos("tamano"),
            "ciiu2": [r["v"] for r in conn.execute(
                "SELECT DISTINCT left(ciiu, 2) AS v FROM empresa WHERE baja IS NULL AND ciiu IS NOT NULL ORDER BY 1")],
            "naturaleza": conn.execute("SELECT codigo, nombre, excluida FROM naturaleza_juridica ORDER BY nombre").fetchall()}


@router.get("/empresas/{rut}")
def ficha(rut: str, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    e = empresas.obtener_o_404(conn, rut)
    eid = e["id"]
    e["naturaleza"] = conn.execute("SELECT codigo, nombre, excluida FROM naturaleza_juridica WHERE id = %s",
                                   (e["naturaleza_id"],)).fetchone() if e["naturaleza_id"] else None
    if e["fusionada_en"]:
        e["fusionada_en_rut"] = conn.execute("SELECT rut FROM empresa WHERE id = %s", (e["fusionada_en"],)).fetchone()["rut"]
    e["disponibilidad"] = conn.execute("SELECT disponible, reglas, hasta FROM v_empresa_disponible WHERE empresa_id = %s",
                                       (eid,)).fetchone()
    e["historia"] = conn.execute(
        "SELECT h.id, h.campo, h.valor, h.fuente_tipo, h.fuente_id, h.confianza, h.actor, h.fecha, h.detalle,"
        " (c.estado = 'deshecha' OR f.deshecha IS NOT NULL) AS anulada"
        " FROM empresa_campo_historia h LEFT JOIN carga c ON h.fuente_tipo = 'carga' AND c.id = h.fuente_id"
        " LEFT JOIN empresa_fusion f ON h.fuente_tipo = 'fusion' AND f.id = h.fuente_id"
        " WHERE h.empresa_id = %s ORDER BY h.campo, h.fecha DESC, h.id DESC", (eid,)).fetchall()
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
        " EXISTS (SELECT 1 FROM no_llamar n WHERE n.activo AND n.alcance = 'telefono' AND n.objeto_id = t.id) AS no_llamar"
        " FROM telefono_vinculo v JOIN telefono t ON t.id = v.telefono_id LEFT JOIN contacto c ON c.id = v.contacto_id"
        " WHERE v.empresa_id = %s ORDER BY discable DESC, t.e164", (eid,)).fetchall()
    if u.rol == "lectura":
        e["contactos"] = [{"id": None, "nombre": "(dato personal oculto)", "cargo": None, "area": None, "email": None}
                          for _ in conn.execute("SELECT 1 FROM contacto WHERE empresa_id = %s", (eid,))]
    else:
        e["contactos"] = conn.execute(
            "SELECT c.*, EXISTS (SELECT 1 FROM no_llamar n WHERE n.activo AND n.alcance = 'contacto' AND n.objeto_id = c.id)"
            " AS no_llamar FROM contacto c WHERE c.empresa_id = %s ORDER BY c.actualizado DESC", (eid,)).fetchall()
    e["sucursales"] = conn.execute("SELECT * FROM sucursal WHERE empresa_id = %s ORDER BY id", (eid,)).fetchall()
    e["muestras"] = conn.execute(
        "SELECT mi.id AS item_id, m.id AS muestra_id, m.nombre, m.estado, mi.estrato, mi.rol, mi.liberado, s.nombre AS estudio"
        " FROM muestra_item mi JOIN muestra m ON m.id = mi.muestra_id JOIN estudio s ON s.id = m.estudio_id"
        " WHERE mi.empresa_id = %s ORDER BY m.id DESC", (eid,)).fetchall()
    e["fusiones"] = conn.execute(
        "SELECT f.*, a.rut AS absorbente_rut, b.rut AS absorbida_rut FROM empresa_fusion f"
        " JOIN empresa a ON a.id = f.absorbente_id JOIN empresa b ON b.id = f.absorbida_id"
        " WHERE f.absorbente_id = %s OR f.absorbida_id = %s ORDER BY f.id DESC", (eid, eid)).fetchall()
    e["no_llamar"] = conn.execute("SELECT * FROM no_llamar WHERE alcance = 'empresa' AND objeto_id = %s ORDER BY id DESC",
                                  (eid,)).fetchall()
    e["linea_de_tiempo"] = actividad.linea_de_tiempo(conn, eid)
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
    auditoria.registrar(conn, u.email, "empresa.editar", "empresa", e["rut"], {"valores": valores, "motivo": body.motivo})
    return {"cambios": {k: {"antes": a, "despues": d} for k, (a, d) in cambios.items()}}


class NuevaEmpresa(BaseModel):
    rut: str
    razon_social: str | None = None
    telefonos: list[str] = []


@router.post("/empresas")
def alta_manual(body: NuevaEmpresa, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    r, motivo = rutmod.validar(body.rut)
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
    auditoria.registrar(conn, u.email, "telefono.agregar", "empresa", e["rut"], {"numero": n.e164 or n.crudo})
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
