"""V2 (D53): procesar un lote de carga por tandas, con pocas consultas por tanda en lugar de unas 30 por fila.

El resultado tiene que ser idéntico al del algoritmo fila por fila (cargas.aplicar_una), así que se replica su lógica
paso a paso, pero en memoria:

1. **Precarga** (unas pocas consultas por tanda): las empresas por RUT, su historia por campo (la misma consulta de
   empresas.vigentes, con «= ANY»), sus atributos vigentes y sucursales, los teléfonos por e164 o crudo y sus vínculos.
2. **Decisión en memoria**, fila por fila y en orden: la regla de supervivencia (la misma función empresas.ganador),
   altas, actualizaciones, conflictos, sucursales, teléfonos, vínculos y orígenes. Las filas nuevas de la historia
   tienen la fecha de la transacción (la misma que pone la base) e ids que siguen el orden de inserción.
3. **Escritura en bloque** al vaciar la tanda: ids reservados con nextval en orden, COPY para las altas, la historia,
   las sucursales, los teléfonos y los vínculos, un UPDATE para los valores vigentes y un upsert para los atributos.

Las filas que no son el caso común van, en su lugar y en orden, por el algoritmo fila por fila: sin RUT válido (base
provisoria), RUT nuevo con reglas de fusión además del RUT (la cascada consulta la base), empresas fusionadas o
anuladas, y contactos con teléfono. Antes de una de esas filas se vacía la tanda, y después se vuelve a precargar.
Los contactos sin teléfono se aplican después de vaciar la tanda, en el orden de las filas (no tocan lo demás).
"""
from collections import Counter

from . import catalogos, empresas
from . import telefonos as telmod
from .util import json_dumps

PREFIJO = catalogos.PREFIJO
_CANDIDATOS_VARIAS = empresas._CANDIDATOS_VARIAS
ID_NUEVO = 10 ** 15   # ids de la historia nueva en memoria: mayores que cualquiera de la base, en orden de inserción


class _Catalogo:
    """Lo que no cambia en todo el lote: la hora de la transacción, atributos, orígenes y naturalezas."""

    def __init__(self, conn):
        self.ahora = conn.execute("SELECT now() AS t").fetchone()["t"]
        self.atributos = {a["clave"]: a for a in conn.execute("SELECT * FROM atributo")}
        self.origen_id = {o["codigo"]: o["id"] for o in conn.execute("SELECT id, codigo FROM origen_telefono")}
        self.naturaleza_id = {n["codigo"]: n["id"] for n in conn.execute("SELECT id, codigo FROM naturaleza_juridica")}


def _catalogo(conn, ctx) -> _Catalogo:
    cat = getattr(ctx, "_catalogo_tanda", None)
    if cat is None:
        cat = ctx._catalogo_tanda = _Catalogo(conn)
    return cat


def aplicar(conn, ctx, filas: list):
    """Aplica una tanda de filas ya preparadas (cargas.Fila), en orden."""
    from . import cargas

    t = _Tanda(conn, ctx, _catalogo(conn, ctx))
    ventana = len(filas)   # cuántas filas se precargan juntas; se achica si hay muchas filas poco comunes
    seguidas = 0
    for i, f in enumerate(filas):
        if t.siempre_por_fila(f):
            t.vaciar()
            cargas.aplicar_una(conn, ctx, f)
            ventana, seguidas = max(8, 2 * seguidas), 0
            continue
        if t.vacia or i >= t.hasta:   # fuera de la ventana precargada (sus teléfonos no se trajeron): se vuelve a cargar
            t.vaciar()
            t.precargar(filas[i:i + ventana])
            t.hasta = i + ventana
        if not t.es_comun(f):
            t.vaciar()
            cargas.aplicar_una(conn, ctx, f)
            ventana, seguidas = max(8, 2 * seguidas), 0
            continue
        t.aplicar(f)
        seguidas += 1
    t.vaciar()


class _Tanda:
    def __init__(self, conn, ctx, cat: _Catalogo):
        self.conn, self.ctx, self.cat = conn, ctx, cat
        self.mapeo = ctx.mapeo
        self.reglas_extra = any(r["criterio"] != "rut" for r in ctx.reglas)
        self.con_contactos = bool(self.mapeo.get("contacto_nombre"))
        self.con_sucursal = bool(self.mapeo.get("sucursal_direccion") or self.mapeo.get("sucursal_localidad"))
        self._limpiar()

    def _limpiar(self):
        self.vacia = True
        self.hasta = 0                 # la ventana precargada va hasta esta fila (sin incluirla)
        self.empresas = {}             # rut → empresa (dict; las altas, con id provisorio negativo)
        self.cand = {}                 # id de empresa → {campo: [filas de historia vigentes]}
        self.attr_actual = {}          # id de empresa → {clave: valor_crudo}
        self.sucursales = {}           # (id de empresa, dirección en minúsculas) → id de sucursal
        self.tels = {}                 # ("e", e164) | ("c", crudo) → teléfono (dict)
        self.vinculos = {}             # (id de teléfono, id de empresa) → id del vínculo
        self.sig_id = -1
        self.sig_hist = ID_NUEVO
        # lo que se escribe al vaciar, en orden
        self.altas, self.hist, self.suc_nuevas, self.tel_nuevos, self.vin_nuevos = [], [], [], [], []
        self.origenes = []             # (id de vínculo, código de origen)
        self.cambiadas = {}            # id de empresa → empresa (con sus valores vigentes nuevos)
        self.attr_escribir = {}        # (id de empresa, clave) → fila ganadora de la historia | None (borrar)
        self.pendientes = []           # (fila, empresa, es_alta, hubo_cambio): contacto y conteo después de vaciar
        self.tocados = []              # ids de teléfono (provisorios o reales) con vínculo nuevo

    def _nuevo_id(self) -> int:
        self.sig_id -= 1
        return self.sig_id

    # ── 1 · Precarga ──

    def precargar(self, filas):
        conn, ruts = self.conn, sorted({f.r for f in filas if f.r})
        for e in conn.execute("SELECT e.*, n.codigo AS naturaleza FROM empresa e LEFT JOIN naturaleza_juridica n"
                              " ON n.id = e.naturaleza_id WHERE e.rut = ANY(%s)", (ruts,)) if ruts else []:
            self.empresas[e["rut"]] = e
        ids = [e["id"] for e in self.empresas.values() if e["baja"] is None]
        if ids:
            for h in conn.execute(_CANDIDATOS_VARIAS, (ids,)):
                self.cand.setdefault(h["empresa_id"], {}).setdefault(h["campo"], []).append(h)
            for a in conn.execute("SELECT ea.empresa_id, a.clave, ea.valor_crudo FROM empresa_atributo ea"
                                  " JOIN atributo a ON a.id = ea.atributo_id WHERE ea.empresa_id = ANY(%s)", (ids,)):
                self.attr_actual.setdefault(a["empresa_id"], {})[a["clave"]] = a["valor_crudo"]
            if self.con_sucursal:
                for s in conn.execute("SELECT id, empresa_id, direccion FROM sucursal WHERE empresa_id = ANY(%s)"
                                      " ORDER BY id", (ids,)):
                    self.sucursales.setdefault((s["empresa_id"], (s["direccion"] or "").lower()), s["id"])
        e164s, crudos = set(), set()
        for f in filas:
            for t, _ in f.tels:
                n = telmod.normalizar(t.crudo)
                if n.crudo:
                    (e164s.add(n.e164) if n.e164 else crudos.add(n.crudo))
        if e164s:
            for t in conn.execute("SELECT * FROM telefono WHERE e164 = ANY(%s)", (sorted(e164s),)):
                self.tels[("e", t["e164"])] = t
        if crudos:
            for t in conn.execute("SELECT * FROM telefono WHERE e164 IS NULL AND crudo = ANY(%s)", (sorted(crudos),)):
                self.tels[("c", t["crudo"])] = t
        tel_ids = [t["id"] for t in self.tels.values()]
        if tel_ids and ids:
            for v in conn.execute("SELECT id, telefono_id, empresa_id FROM telefono_vinculo"
                                  " WHERE telefono_id = ANY(%s) AND empresa_id = ANY(%s)", (tel_ids, ids)):
                self.vinculos[(v["telefono_id"], v["empresa_id"])] = v["id"]
        self.vacia = False

    # ── 2 · Decisión en memoria ──

    def siempre_por_fila(self, f) -> bool:
        """Filas que van por el algoritmo fila por fila sin importar la base: sin RUT válido (base provisoria) o con
        un contacto con teléfono (el teléfono del contacto se vincula a la empresa)."""
        return f.r is None or bool(self.con_contactos and cargas_valor(f.fila, self.mapeo, "contacto_telefono"))

    def es_comun(self, f) -> bool:
        """¿Esta fila va por el camino rápido? Si no, la aplica el algoritmo fila por fila."""
        emp = self.empresas.get(f.r)
        if emp is None:
            return not self.reglas_extra      # RUT nuevo: con otras reglas, la cascada consulta la base
        return emp["baja"] is None

    def aplicar(self, f):
        ctx, c = self.ctx, self.ctx.c
        emp = self.empresas.get(f.r)
        es_alta = False
        if emp is None:
            base = "definitiva" if ctx.con_rut_a_definitiva else "provisoria"
            emp = {k: None for k in empresas.CAMPOS}
            emp.update({"id": self._nuevo_id(), "rut": f.r, "codigo": f.r, "base": base, "baja": None,
                        "estado": "desconocida", "carga_alta_id": ctx.cid})
            self.empresas[f.r] = emp
            self.altas.append(emp)
            es_alta = True
            c[f"altas_{base}"] += 1
        hubo, conflictos = self._valores(emp, f.datos)
        if f.attrs:
            cambios_a, conflictos_a = self._atributos(emp, f.attrs)
            hubo = hubo or bool(cambios_a)
            conflictos = {**conflictos, **conflictos_a}
        if conflictos:
            c["conflictos"] += 1
            if len(ctx.conflictos_muestra) < 30:
                ctx.conflictos_muestra.append({"rut": emp["codigo"], "campos": conflictos})
        sucursal_id = None
        d = f.datos
        if d.get("sucursal_direccion") or d.get("sucursal_localidad"):
            clave = (emp["id"], (d.get("sucursal_direccion") or "").lower())
            sucursal_id = self.sucursales.get(clave)
            if sucursal_id is None:
                sucursal_id = self._nuevo_id()
                self.sucursales[clave] = sucursal_id
                self.suc_nuevas.append((sucursal_id, emp, d.get("sucursal_direccion"), d.get("sucursal_departamento"),
                                        d.get("sucursal_localidad")))
                c["sucursales_nuevas"] += 1
                hubo = True
        for t, origen in f.tels:
            if self._telefono(emp, t, origen, sucursal_id):
                hubo = True
        self.pendientes.append((f, emp, es_alta, hubo))

    def _valores(self, emp, datos) -> tuple[bool, dict]:
        """Como empresas.aplicar_valores: historia y recálculo de los valores vigentes. (hubo cambios, conflictos)"""
        limpios = {k: v for k, v in datos.items() if k in empresas.CAMPOS and v is not None and str(v).strip() != ""}
        if not limpios:
            return False, {}
        cands = self.cand.setdefault(emp["id"], {})
        antes = {k: empresas.ganador(cands[k]) for k in limpios if cands.get(k)}
        for k, v in limpios.items():
            self._historia(emp, cands, k, str(v), None)
        cambios = {}
        for k in limpios:
            g = empresas.ganador(cands.get(k, []))
            nuevo = g["valor"] if g else (None if k != "estado" else "desconocida")
            if nuevo != emp[k]:
                cambios[k] = (emp[k], nuevo)
                emp[k] = nuevo
        if cambios:
            self.cambiadas[emp["id"]] = emp
        conflictos = {}
        for k, v in limpios.items():
            previo = antes.get(k)
            if previo is not None and previo["valor"] != str(v) and k not in cambios:
                conflictos[k] = {"vigente": previo["valor"], "fuente_vigente": previo["fuente_tipo"], "llego": str(v)}
        return bool(cambios), conflictos

    def _atributos(self, emp, valores) -> tuple[dict, dict]:
        """Como empresas.aplicar_atributos + catalogos.recalcular_atributos."""
        limpios = {k: v for k, v in valores.items() if v and v.get("valor") not in (None, "")}
        if not limpios:
            return {}, {}
        cands = self.cand.setdefault(emp["id"], {})
        antes = {PREFIJO + k: empresas.ganador(cands[PREFIJO + k]) for k in limpios if cands.get(PREFIJO + k)}
        for k, v in limpios.items():
            self._historia(emp, cands, PREFIJO + k, str(v["valor"]), {"invalido": True} if v.get("invalido") else None)
        actual = self.attr_actual.setdefault(emp["id"], {})
        previo_crudo = dict(actual)
        cambios = {}
        for k in limpios:
            g = empresas.ganador(cands.get(PREFIJO + k, []))
            a = self.cat.atributos.get(k)
            if a is not None:
                if a["fusionado_en"] or g is None:
                    actual.pop(k, None)
                    self.attr_escribir[(emp["id"], k)] = None
                else:
                    actual[k] = catalogos.interpretar(a, g["valor"])["crudo"]
                    self.attr_escribir[(emp["id"], k)] = g
            nuevo = g["valor"] if g else None
            if previo_crudo.get(k) != nuevo:
                cambios[PREFIJO + k] = (previo_crudo.get(k), nuevo)
        conflictos = {}
        for k, v in limpios.items():
            previo = antes.get(PREFIJO + k)
            if previo is not None and previo["valor"] != str(v["valor"]) and PREFIJO + k not in cambios:
                conflictos[PREFIJO + k] = {"vigente": previo["valor"], "fuente_vigente": previo["fuente_tipo"],
                                           "llego": str(v["valor"])}
        return cambios, conflictos

    def _historia(self, emp, cands, campo, valor, detalle):
        ctx = self.ctx
        self.sig_hist += 1
        h = {"id": self.sig_hist, "campo": campo, "valor": valor, "fuente_tipo": "carga", "fuente_id": ctx.cid,
             "confianza": ctx.confianza, "actor": ctx.actor, "fecha": self.cat.ahora, "detalle": detalle}
        cands.setdefault(campo, []).append(h)
        self.hist.append((emp, h))

    def _telefono(self, emp, t, origen, sucursal_id) -> bool:
        """Como cargas.aplicar_fila para un teléfono: empresas.telefono + empresas.vincular. True si el vínculo es nuevo."""
        c = self.ctx.c
        if t.tipo == "interno":
            c["telefonos_invalidos"] += 1
            return False
        n = telmod.normalizar(t.crudo)
        if not n.crudo:
            return False
        clave = ("e", n.e164) if n.e164 else ("c", n.crudo)
        tel = self.tels.get(clave)
        if tel is None:
            tel = {"id": self._nuevo_id(), "e164": n.e164, "crudo": n.crudo,
                   "tipo": n.tipo if n.e164 else "invalido", "estado": "valido" if n.e164 else "invalido"}
            self.tels[clave] = tel
            self.tel_nuevos.append(tel)
            c["telefonos_nuevos"] += 1
        if not n.e164:
            c["telefonos_invalidos"] += 1
        vclave = (tel["id"], emp["id"])
        vid = self.vinculos.get(vclave)
        nuevo = vid is None
        if nuevo:
            vid = self._nuevo_id()
            self.vinculos[vclave] = vid
            self.vin_nuevos.append((vid, tel, emp, sucursal_id))
        self.origenes.append((vid, origen))
        po = self.ctx.por_origen.setdefault(origen, Counter())
        po["nuevos" if nuevo else "existentes"] += 1
        if nuevo:
            c["vinculos_nuevos"] += 1
            self.tocados.append(tel)
        return nuevo

    # ── 3 · Escritura en bloque ──

    def _reservar(self, tabla: str, n: int) -> list[int]:
        if not n:
            return []
        return sorted(r["id"] for r in self.conn.execute(
            "SELECT nextval(pg_get_serial_sequence(%s, 'id')) AS id FROM generate_series(1, %s)", (tabla, n)))

    def _copy(self, sql: str, filas):
        if not filas:
            return
        with self.conn.cursor() as cur:
            with cur.copy(sql) as cp:
                for f in filas:
                    cp.write_row(f)

    def vaciar(self):
        if self.vacia:
            return
        conn, ctx = self.conn, self.ctx
        reales = {}

        def real(i):
            return reales.get(i, i) if i is not None and i < 0 else i

        # Altas
        for e, i in zip(self.altas, self._reservar("empresa", len(self.altas))):
            reales[e["id"]] = i
        self._copy("COPY empresa (id, rut, base, carga_alta_id) FROM STDIN",
                   [(reales[e["id"]], e["rut"], e["base"], e["carga_alta_id"]) for e in self.altas])
        for e in self.altas:
            e["id"] = reales[e["id"]]
        # Sucursales
        ids = self._reservar("sucursal", len(self.suc_nuevas))
        for (tmp, *_), i in zip(self.suc_nuevas, ids):
            reales[tmp] = i
        self._copy("COPY sucursal (id, empresa_id, direccion, departamento, localidad, fuente_tipo, fuente_id) FROM STDIN",
                   [(reales[tmp], e["id"], dir_, dep, loc, "carga", ctx.cid) for tmp, e, dir_, dep, loc in self.suc_nuevas])
        # Teléfonos
        for t, i in zip(self.tel_nuevos, self._reservar("telefono", len(self.tel_nuevos))):
            reales[t["id"]] = i
            t["id"] = i
        self._copy("COPY telefono (id, e164, crudo, tipo, estado) FROM STDIN",
                   [(t["id"], t["e164"], t["crudo"], t["tipo"], t["estado"]) for t in self.tel_nuevos])
        # Vínculos, su historia y sus orígenes
        for (tmp, *_), i in zip(self.vin_nuevos, self._reservar("telefono_vinculo", len(self.vin_nuevos))):
            reales[tmp] = i
        self._copy("COPY telefono_vinculo (id, telefono_id, empresa_id, sucursal_id, estado, fuente_tipo, fuente_id)"
                   " FROM STDIN", [(reales[tmp], t["id"], e["id"], real(s), "sin_verificar", "carga", ctx.cid)
                                   for tmp, t, e, s in self.vin_nuevos])
        self._copy("COPY telefono_vinculo_historia (vinculo_id, telefono_id, empresa_id, estado, fuente_tipo, fuente_id,"
                   " actor) FROM STDIN", [(reales[tmp], t["id"], e["id"], "sin_verificar", "carga", ctx.cid, ctx.actor)
                                          for tmp, t, e, s in self.vin_nuevos])
        orig = [(real(v), self.cat.origen_id[o]) for v, o in self.origenes if o in self.cat.origen_id]
        if orig:
            conn.execute("INSERT INTO telefono_vinculo_origen (vinculo_id, origen_id, fuente_tipo, fuente_id)"
                         " SELECT v, o, 'carga', %s FROM unnest(%s::int[], %s::int[]) AS x(v, o) ON CONFLICT DO NOTHING",
                         (ctx.cid, [v for v, _ in orig], [o for _, o in orig]))
        # Historia, en el orden en que se generó (los ids de la base siguen ese orden)
        self._copy("COPY empresa_campo_historia (empresa_id, campo, valor, fuente_tipo, fuente_id, confianza, actor, detalle)"
                   " FROM STDIN", [(e["id"], h["campo"], h["valor"], "carga", ctx.cid, ctx.confianza, ctx.actor,
                                    json_dumps(h["detalle"]) if h["detalle"] else None) for e, h in self.hist])
        # Valores vigentes
        if self.cambiadas:
            es = list(self.cambiadas.values())
            cols = [k for k in empresas.CAMPOS if k != "naturaleza"]
            conn.execute(
                "UPDATE empresa e SET " + ", ".join(f"{k} = v.{k}" for k in cols) +
                ", naturaleza_id = v.naturaleza_id, actualizado = now() FROM unnest(%s::int[], %s::int[], " +
                ", ".join("%s::text[]" for _ in cols) + ") AS v(id, naturaleza_id, " + ", ".join(cols) + ") WHERE e.id = v.id AND e.id = ANY(%s::int[])",
                ([e["id"] for e in es], [self.cat.naturaleza_id.get(e["naturaleza"]) for e in es],
                 *[[e[k] for e in es] for k in cols], [e["id"] for e in es]))
        # Atributos vigentes
        borrar = [(real(eid), self.cat.atributos[k]["id"]) for (eid, k), g in self.attr_escribir.items() if g is None]
        poner = [(real(eid), self.cat.atributos[k], g) for (eid, k), g in self.attr_escribir.items() if g is not None]
        if borrar:
            conn.execute("DELETE FROM empresa_atributo ea USING unnest(%s::int[], %s::int[]) AS x(e, a)"
                         " WHERE ea.empresa_id = x.e AND ea.atributo_id = x.a AND ea.empresa_id = ANY(%s::int[])",
                         ([e for e, _ in borrar], [a for _, a in borrar], [e for e, _ in borrar]))
        catalogos.poner_atributos(conn, poner)
        for t in self.tocados:
            ctx.telefonos_tocados.add(t["id"])
        # Contactos (sin teléfono) y el conteo de cada fila, en orden
        from . import cargas

        for f, emp, es_alta, hubo in self.pendientes:
            if self.con_contactos:
                hubo = cargas.aplicar_contacto(conn, emp, f.fila, self.mapeo, ctx.traductor, ctx.prefijos, ctx.cid,
                                               ctx.actor, ctx.c, ctx.por_atributo, ctx.telefonos_tocados) or hubo
            cargas.contar_resultado(ctx, emp, es_alta, hubo)
        self._limpiar()


def cargas_valor(fila, mapeo, campo):
    from .cargas import _valor

    return _valor(fila, mapeo, campo)
