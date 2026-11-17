"""Fase 2 (SPEC_fase2_enriquecimiento): calidad de la base, enriquecimiento bajo demanda, duplicados difusos,
grupos económicos y descubrimiento de empresas nuevas."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import calidad, descubrimiento, duplicados, empresas, enriquecimiento as enr, tareas
from ..auth import Usuario, requiere, requiere_job
from ..db import conexion, get_conn

router = APIRouter()
GESTION = ("admin", "steward")


# ── A1 · Calidad de la base ──

@router.get("/calidad")
def ver_calidad(conn=Depends(get_conn), u: Usuario = Depends(requiere("steward", "jefe"))):
    return calidad.tablero(conn)


@router.get("/calidad/{indicador}")
def lista_calidad(indicador: str, pagina: int = 1, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward", "jefe"))):
    return calidad.incumplen(conn, indicador, pagina)


@router.post("/calidad/alertas/{empresa_id}/revisar")
def revisar_alerta(empresa_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    return calidad.revisar_alerta(conn, empresa_id, u.email)


@router.post("/calidad/medir")
def medir_ahora(conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    return calidad.medir(conn, actor=u.email)


@router.post("/jobs/calidad")
def job_calidad(conn=Depends(get_conn), _: str = Depends(requiere_job)):
    """Cloud Scheduler diario: foto de los indicadores (evolución del tablero)."""
    return calidad.medir(conn)


@router.post("/jobs/duplicados")
def job_duplicados(conn=Depends(get_conn), _: str = Depends(requiere_job)):
    """Cloud Scheduler diario: detección de duplicados difusos."""
    return duplicados.detectar(conn)


# ── B1 · Configuración: claves de los proveedores (nunca se devuelven) ──

@router.get("/config/enriquecimiento")
def config_enriquecimiento(conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    cfg, _ = enr.cfg_vigente(conn)
    return {"parametros": cfg, "proveedores": enr.estado_proveedores(conn, cfg), "gasto": enr.resumen_gasto(conn)}


class Clave(BaseModel):
    proveedor: str
    clave: str


@router.put("/config/enriquecimiento/clave")
def guardar_clave(body: Clave, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    return enr.guardar_clave(conn, body.proveedor, body.clave, u.email)


# ── B2 · Corridas de enriquecimiento ──

def _puede_lanzar(u: Usuario, origen: str):
    """Admin y data steward desde cualquier lado; el jefe de estudio solo desde una muestra."""
    if u.puede(*GESTION) or (origen == "muestra" and u.puede("jefe")):
        return
    raise HTTPException(403, "Solo el administrador y el data steward enriquecen (el jefe de estudio, desde una muestra)")


class Estimar(BaseModel):
    origen: str
    muestra_id: int | None = None
    filtros: dict | None = None
    rut: str | None = None
    alcance: str = "sin_telefono"


@router.post("/enriquecimiento/estimar")
def estimar(body: Estimar, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward", "jefe"))):
    _puede_lanzar(u, body.origen)
    return enr.estimar(conn, body.origen, u.email, body.muestra_id, body.filtros, body.rut, body.alcance)


class Aprobar(BaseModel):
    limite: int | None = None
    reducir: str = "orden"


def _corrida(conn, corrida_id: int, u: Usuario) -> dict:
    c = conn.execute("SELECT origen FROM enriquecimiento_corrida WHERE id = %s", (corrida_id,)).fetchone()
    if c is None:
        raise HTTPException(404, "Corrida inexistente")
    _puede_lanzar(u, c["origen"])
    return c


@router.post("/enriquecimiento/{corrida_id}/aprobar")
def aprobar(corrida_id: int, body: Aprobar, u: Usuario = Depends(requiere("steward", "jefe"))):
    with conexion() as conn:
        _corrida(conn, corrida_id, u)
        r = enr.aprobar(conn, corrida_id, u.email, body.limite, body.reducir)
    tareas.despachar(r["tarea_id"])
    return r


@router.post("/enriquecimiento/{corrida_id}/descartar")
def descartar(corrida_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward", "jefe"))):
    _corrida(conn, corrida_id, u)
    return enr.descartar(conn, corrida_id, u.email)


@router.post("/enriquecimiento/{corrida_id}/cancelar")
def cancelar(corrida_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward", "jefe"))):
    _corrida(conn, corrida_id, u)
    return enr.cancelar(conn, corrida_id, u.email)


@router.post("/enriquecimiento/{corrida_id}/deshacer")
def deshacer(corrida_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere(*GESTION))):
    return enr.deshacer(conn, corrida_id, u.email)


@router.get("/enriquecimiento")
def corridas(muestra_id: int | None = None, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward", "jefe"))):
    return enr.listar(conn, "enriquecimiento", muestra_id)


@router.get("/enriquecimiento/{corrida_id}")
def corrida(corrida_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward", "jefe"))):
    c = enr.detalle(conn, corrida_id)
    if c["resultado"]:   # la lista por empresa va aparte (paginada)
        c["resultado"] = {k: v for k, v in c["resultado"].items() if k not in ("empresas", "resultados")}
    return c


@router.get("/enriquecimiento/{corrida_id}/empresas")
def corrida_empresas(corrida_id: int, resultado: str | None = None, pagina: int = 1, conn=Depends(get_conn),
                     u: Usuario = Depends(requiere("steward", "jefe"))):
    c = enr.detalle(conn, corrida_id)
    filas = [f for f in ((c["resultado"] or {}).get("empresas") or []) if not resultado or f["resultado"] == resultado]
    pagina = max(1, pagina)
    return {"total": len(filas), "pagina": pagina, "filas": filas[(pagina - 1) * 50: pagina * 50]}


@router.get("/empresas/{rut}/enriquecimiento")
def enriquecimiento_empresa(rut: str, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward", "jefe"))):
    emp = empresas.obtener_o_404(conn, rut)
    return enr.pasos_empresa(conn, emp["id"])


# ── B4 · Duplicados difusos y grupos económicos ──

@router.get("/duplicados")
def bandeja(estado: str = "pendiente", pagina: int = 1, conn=Depends(get_conn), u: Usuario = Depends(requiere(*GESTION))):
    return duplicados.bandeja(conn, estado, pagina)


@router.post("/duplicados/detectar")
def detectar(conn=Depends(get_conn), u: Usuario = Depends(requiere(*GESTION))):
    return duplicados.detectar(conn, u.email)


class Resolver(BaseModel):
    accion: str
    absorbente_id: int | None = None
    nombre_grupo: str | None = None


@router.post("/duplicados/{par_id}/resolver")
def resolver(par_id: int, body: Resolver, conn=Depends(get_conn), u: Usuario = Depends(requiere(*GESTION))):
    return duplicados.resolver(conn, par_id, body.accion, u.email, body.absorbente_id, body.nombre_grupo)


@router.get("/grupos/{grupo_id}")
def ver_grupo(grupo_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward", "jefe", "coordinador", "lectura"))):
    return duplicados.grupo(conn, grupo_id)


class NombreGrupo(BaseModel):
    nombre: str


@router.put("/grupos/{grupo_id}")
def renombrar_grupo(grupo_id: int, body: NombreGrupo, conn=Depends(get_conn), u: Usuario = Depends(requiere(*GESTION))):
    return duplicados.renombrar(conn, grupo_id, body.nombre, u.email)


@router.delete("/empresas/{rut}/grupo")
def quitar_de_grupo(rut: str, conn=Depends(get_conn), u: Usuario = Depends(requiere(*GESTION))):
    emp = empresas.obtener_o_404(conn, rut)
    return duplicados.quitar(conn, emp["id"], u.email)


# ── B5 · Descubrimiento de empresas nuevas ──

class Busqueda(BaseModel):
    consulta: str | None = None
    rubro: str | None = None
    departamento: str | None = None
    localidad: str | None = None
    paginas: int = 1


@router.post("/descubrimiento/estimar")
def estimar_busqueda(body: Busqueda, conn=Depends(get_conn), u: Usuario = Depends(requiere(*GESTION))):
    return descubrimiento.estimar(conn, u.email, body.consulta, body.rubro, body.departamento, body.localidad, body.paginas)


@router.post("/descubrimiento/{corrida_id}/buscar")
def buscar(corrida_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere(*GESTION))):
    return descubrimiento.buscar(conn, corrida_id, u.email)


class Seleccion(BaseModel):
    seleccion: dict[str, str] = {}


@router.post("/descubrimiento/{corrida_id}/confirmar")
def confirmar(corrida_id: int, body: Seleccion, conn=Depends(get_conn), u: Usuario = Depends(requiere(*GESTION))):
    return descubrimiento.confirmar(conn, corrida_id, body.seleccion, u.email)


@router.post("/descubrimiento/{corrida_id}/descartar")
def descartar_busqueda(corrida_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere(*GESTION))):
    return enr.descartar(conn, corrida_id, u.email)


@router.post("/descubrimiento/{corrida_id}/deshacer")
def deshacer_busqueda(corrida_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere(*GESTION))):
    return descubrimiento.deshacer(conn, corrida_id, u.email)


@router.get("/descubrimiento")
def busquedas(conn=Depends(get_conn), u: Usuario = Depends(requiere(*GESTION))):
    return enr.listar(conn, "descubrimiento")


@router.get("/descubrimiento/{corrida_id}")
def busqueda(corrida_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere(*GESTION))):
    return enr.detalle(conn, corrida_id)
