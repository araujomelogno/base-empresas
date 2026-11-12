"""Base provisoria: empresas sin RUT (F6.1). Pantalla, «Agregar RUT», «Es otra empresa» y RUT por archivo.
Consultar: cualquier usuario; cambiar: data steward y administrador."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from .. import empresas, provisorias, storage
from ..auth import Usuario, requiere, usuario_actual
from ..db import conexion, get_conn

router = APIRouter()


class Rut(BaseModel):
    rut: str


class Descarte(BaseModel):
    candidatas: list[int]


class Aplicar(BaseModel):
    archivo_id: int
    fusionar: bool = False


@router.get("/provisorias")
def listar(q: str | None = None, pagina: int = 1, con_candidatas: bool = False, conn=Depends(get_conn),
           u: Usuario = Depends(usuario_actual)):
    return provisorias.listar(conn, q, pagina, con_candidatas)


@router.get("/empresas/{codigo}/candidatas")
def candidatas(codigo: str, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    emp = empresas.obtener_o_404(conn, codigo)
    umbral = float(provisorias.config.vigente(conn)[1].get("umbral_fusion_flexible", 0.85))
    return provisorias.candidatas_definitiva(conn, emp, umbral) if emp["base"] == "provisoria" else []


@router.post("/empresas/{codigo}/rut")
def agregar_rut(codigo: str, body: Rut, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    """«Agregar RUT»: si es nuevo, la empresa pasa a la definitiva; si ya existe, 409 para ofrecer la fusión."""
    emp = empresas.obtener_o_404(conn, codigo)
    if emp["baja"]:
        raise HTTPException(409, "La empresa está dada de baja o fusionada")
    e = provisorias.promover(conn, emp, body.rut, u.email)
    return {"rut": e["rut"], "base": e["base"]}


@router.post("/empresas/{codigo}/descartar")
def descartar(codigo: str, body: Descarte, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    """«Es otra empresa»: las candidatas no se vuelven a proponer."""
    emp = empresas.obtener_o_404(conn, codigo)
    return {"descartadas": provisorias.descartar(conn, emp, body.candidatas, u.email)}


@router.post("/provisorias/ruts/analizar")
def ruts_analizar(archivo: UploadFile = File(...), u: Usuario = Depends(requiere("steward"))):
    """Completar RUT por archivo (codigo_provisorio;rut): preview sin aplicar nada."""
    datos = archivo.file.read()
    with conexion() as conn:
        a = storage.guardar(conn, archivo.filename or "ruts.csv", datos, u.email)
        return {"archivo_id": a["id"], **provisorias.ruts_preview(conn, a)}


@router.post("/provisorias/ruts/aplicar")
def ruts_aplicar(body: Aplicar, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    a = conn.execute("SELECT * FROM archivo WHERE id = %s", (body.archivo_id,)).fetchone()
    if a is None:
        raise HTTPException(404, "Archivo inexistente")
    return provisorias.ruts_aplicar(conn, a, body.fusionar, u.email)
