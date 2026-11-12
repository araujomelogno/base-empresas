"""Actualización de la base desde los resultados del .sav (R1.10; SPEC_mejoras_sav_contactos, F2.1–F2.3, D39).

- Toda fila del .sav es una encuesta completa (Alchemer exporta solo las completas): el ítem
  queda «completa» en la parte y la empresa actualiza su último contacto efectivo.
- EC_TEL_USADO (el número con el que se habló) y EC_TEL_ALT (número adicional) se crean si no
  existen, se vinculan con origen «sala» y quedan **verificados**. Una calidad negativa explícita
  para el número usado (no corresponde, intermediario, inexistente) gana: ese número no se verifica (Q1).
- EC_CALIDAD_TEL actualiza el estado del vínculo; «la empresa cerró» marca la empresa cerrada.
- EC_RESP_* crea o actualiza el contacto, que queda relacionado con el número por el que se
  habló (contacto_telefono, «se habló») y con EC_TEL_ALT («número del contacto»).
- Cada cambio queda con linaje: estudio, parte, ingesta, response_id, encuestador, fecha.
Todo es idempotente: aplicar dos veces la misma fila no cambia nada la segunda vez.
"""
from . import contactos, empresas

CALIDAD_A_VINCULO = {"corresponde": "verificado", "no_corresponde": "no_corresponde",
                     "intermediario": "intermediario", "inexistente": "inexistente"}
CALIDAD_NEGATIVA = ("no_corresponde", "intermediario", "inexistente")
# Un estado más avanzado no se pisa con uno menos avanzado; «completa» es el más avanzado
RANGO_ESTADO = {"pendiente": 0, "en_curso": 1, "no_contactable": 2, "fuera_de_marco": 3, "rechazo": 4, "completa": 5}


def _verificar(conn, tel: dict, empresa_id: int, fuente_id, actor: str, linaje: dict) -> tuple[dict, bool, bool]:
    """Vincula el número a la empresa (origen sala) y lo deja verificado.
    Devuelve (vinculo, nuevo, verificado_ahora). Un intermediario confirmado no se verifica (decisión humana)."""
    estado = "sin_verificar" if tel["intermediario"] == "confirmado" else "verificado"
    v, nuevo = empresas.vincular(conn, tel["id"], empresa_id, "sala", fuente_id, actor, estado=estado, detalle=linaje,
                                 origen="sala")
    if nuevo:
        return v, True, estado == "verificado"
    if estado == "verificado" and empresas.cambiar_estado_vinculo(conn, v, "verificado", "sala", fuente_id, actor, linaje):
        return {**v, "estado": "verificado"}, False, True
    return v, False, False


def aplicar(conn, item: dict, parte: dict, v: dict, linaje: dict, cfg: dict, actor: str, forzar: bool = False) -> dict:
    """item: fila de muestra_item; v: valores ya mapeados al sistema. Devuelve el resumen de lo aplicado.
    forzar (remapeo) no cambia nada aquí: «completa» nunca retrocede."""
    empresa_id = item["empresa_id"]
    aplicado = {}
    fuente_id = linaje.get("ingesta_id")
    conf_sala = cfg["confianza_fuentes"].get("sala", 80)
    prefijos = cfg.get("prefijos_salida") or []
    calidad = v.get("calidad_tel")
    calidad = None if calidad == "ignorar" else calidad
    clave = f"sav:{linaje.get('parte_id')}:{linaje.get('response_id')}"

    tel_usado = None
    if v.get("tel_usado"):
        fila, n, _ = empresas.telefono(conn, v["tel_usado"], prefijos)
        if fila is not None and n.e164:
            tel_usado = fila
            if calidad in CALIDAD_NEGATIVA:  # Q1: la calidad negativa explícita gana sobre la verificación
                _, nuevo = empresas.vincular(conn, fila["id"], empresa_id, "sala", fuente_id, actor, detalle=linaje,
                                             origen="sala")
                verificado = False
            else:
                _, nuevo, verificado = _verificar(conn, fila, empresa_id, fuente_id, actor, linaje)
            if nuevo:
                aplicado["tel_usado_nuevo"] = n.e164
            if verificado:
                aplicado["tel_usado_verificado"] = n.e164

    if calidad:
        if calidad == "cerro":
            cambios, _ = empresas.aplicar_valores(conn, empresa_id, {"estado": "cerrada"}, "sala", fuente_id,
                                                  conf_sala, actor, linaje)
            if cambios:
                aplicado["empresa_cerrada"] = True
        elif tel_usado is not None:
            vinc = conn.execute("SELECT * FROM telefono_vinculo WHERE telefono_id = %s AND empresa_id = %s",
                                (tel_usado["id"], empresa_id)).fetchone()
            nuevo_estado = CALIDAD_A_VINCULO[calidad]
            if empresas.cambiar_estado_vinculo(conn, vinc, nuevo_estado, "sala", fuente_id, actor, linaje):
                aplicado["vinculo"] = {"e164": tel_usado["e164"], "estado": nuevo_estado}
            if calidad == "intermediario" and tel_usado["intermediario"] != "confirmado":
                conn.execute("UPDATE telefono SET intermediario = 'confirmado', intermediario_fecha = now(),"
                             " intermediario_por = %s WHERE id = %s", (f"sala:{linaje.get('encuestador') or actor}",
                                                                       tel_usado["id"]))
                aplicado["intermediario_confirmado"] = tel_usado["e164"]
            if calidad == "inexistente" and tel_usado["estado"] != "inexistente":
                conn.execute("UPDATE telefono SET estado = 'inexistente' WHERE id = %s", (tel_usado["id"],))
        else:
            aplicado["calidad_sin_telefono"] = calidad

    contacto = None
    if v.get("resp_nombre"):
        contacto, nuevo = empresas.contacto(conn, empresa_id, v["resp_nombre"], v.get("resp_cargo"), v.get("resp_area"),
                                            None, "sala", fuente_id, linaje, actor=actor)
        if nuevo:
            aplicado["contacto_nuevo"] = v["resp_nombre"]
        if tel_usado is not None and contactos.relacionar_telefono(
                conn, contacto["id"], tel_usado["id"], "se_hablo", "sala", fuente_id, linaje.get("fecha"), clave):
            aplicado["contacto_telefono"] = tel_usado["e164"]

    if v.get("tel_alt"):
        fila, n, _ = empresas.telefono(conn, v["tel_alt"], prefijos)
        if fila is not None:
            if n.e164:
                _, nuevo, verificado = _verificar(conn, fila, empresa_id, fuente_id, actor, linaje)
                if verificado:
                    aplicado["tel_alt_verificado"] = n.e164
            else:  # no normalizable: queda vinculado como dato crudo (no es discable)
                _, nuevo = empresas.vincular(conn, fila["id"], empresa_id, "sala", fuente_id, actor, detalle=linaje,
                                             origen="sala")
            if nuevo:
                aplicado["tel_alt_nuevo"] = n.e164 or n.crudo
            if contacto is not None:
                contactos.relacionar_telefono(conn, contacto["id"], fila["id"], "del_contacto", "sala", fuente_id,
                                              linaje.get("fecha"), clave)

    for clave_attr, valor in (v.get("atributos_contacto") or {}).items():
        if contacto is not None:
            from . import catalogos
            if catalogos.aplicar_atributo_contacto(conn, contacto, clave_attr, valor, "sala", fuente_id, actor, linaje):
                aplicado.setdefault("atributos_contacto", []).append(clave_attr)

    # D-b: toda fila del .sav es una encuesta completa
    actual = conn.execute("SELECT * FROM item_parte_estado WHERE item_id = %s AND parte_id = %s",
                          (item["id"], parte["id"])).fetchone()
    if actual is None or actual["estado"] != "completa" or forzar:
        conn.execute(
            "INSERT INTO item_parte_estado (item_id, parte_id, estado, telefono_id, respondente, encuestador, fecha)"
            " VALUES (%s,%s,'completa',%s,%s,%s,%s) ON CONFLICT (item_id, parte_id) DO UPDATE SET estado = 'completa',"
            " telefono_id = coalesce(EXCLUDED.telefono_id, item_parte_estado.telefono_id),"
            " respondente = coalesce(EXCLUDED.respondente, item_parte_estado.respondente),"
            " encuestador = coalesce(EXCLUDED.encuestador, item_parte_estado.encuestador),"
            " fecha = coalesce(EXCLUDED.fecha, item_parte_estado.fecha)",
            (item["id"], parte["id"], tel_usado["id"] if tel_usado else None, v.get("resp_nombre"),
             linaje.get("encuestador"), linaje.get("fecha")))
        if actual is None or actual["estado"] != "completa":
            aplicado["estado_parte"] = "completa"
    if linaje.get("fecha"):
        r = conn.execute(
            "UPDATE empresa SET ultimo_contacto_efectivo = %s WHERE id = %s"
            " AND (ultimo_contacto_efectivo IS NULL OR ultimo_contacto_efectivo < %s) RETURNING id",
            (linaje["fecha"], empresa_id, linaje["fecha"])).fetchone()
        if r:
            aplicado["ultimo_contacto_efectivo"] = linaje["fecha"]
    return aplicado
