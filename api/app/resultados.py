"""Actualización de la base desde los resultados del .sav (R1.10).

- EC_CALIDAD_TEL actualiza el estado del vínculo teléfono–empresa; "estudio contable o
  jurídico" lo marca como intermediario confirmado.
- EC_TEL_ALT crea un teléfono vinculado a la empresa, sin verificar y con fuente "sala".
- EC_RESP_* crea o actualiza un contacto de la empresa con su área y cargo.
- Un contacto efectivo (completa, parcial o rechazo) actualiza el último contacto efectivo.
- Cada cambio queda con linaje: estudio, parte, encuestador, fecha.
Todo es idempotente: aplicar dos veces la misma fila no cambia nada la segunda vez.
"""
from . import empresas

CALIDAD_A_VINCULO = {"corresponde": "verificado", "no_corresponde": "no_corresponde",
                     "intermediario": "intermediario", "inexistente": "inexistente"}
RESULTADO_A_ESTADO = {"completa": "completa", "parcial": "en_curso", "rechazo": "rechazo",
                      "no_corresponde": "fuera_de_marco", "agendada": "en_curso", "descalificada": "fuera_de_marco"}
# Un estado más avanzado no se pisa con uno menos avanzado
RANGO_ESTADO = {"pendiente": 0, "en_curso": 1, "no_contactable": 2, "fuera_de_marco": 3, "rechazo": 4, "completa": 5}


def aplicar(conn, item: dict, parte: dict, v: dict, linaje: dict, cfg: dict, actor: str, forzar: bool = False) -> dict:
    """item: fila de muestra_item; v: valores ya mapeados al sistema.
    forzar=True (remapeo) permite que el estado de la parte retroceda al corregir el mapeo."""
    empresa_id = item["empresa_id"]
    aplicado = {}
    fuente_id = linaje.get("ingesta_id")
    conf_sala = cfg["confianza_fuentes"].get("sala", 80)

    tel_usado = None
    if v.get("tel_usado"):
        fila, n, creado = empresas.telefono(conn, v["tel_usado"])
        if fila is not None and n.e164:
            tel_usado = fila
            _, nuevo = empresas.vincular(conn, fila["id"], empresa_id, "sala", fuente_id, actor, detalle=linaje)
            if nuevo:
                aplicado["tel_usado_nuevo"] = n.e164

    calidad = v.get("calidad_tel")
    if calidad and calidad != "ignorar":
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
                                            None, "sala", fuente_id, linaje)
        if nuevo:
            aplicado["contacto_nuevo"] = v["resp_nombre"]

    if v.get("tel_alt"):
        fila, n, creado = empresas.telefono(conn, v["tel_alt"])
        if fila is not None:
            _, nuevo = empresas.vincular(conn, fila["id"], empresa_id, "sala", fuente_id, actor,
                                         contacto_id=contacto["id"] if contacto else None, detalle=linaje)
            if nuevo:
                aplicado["tel_alt_nuevo"] = n.e164 or n.crudo

    resultado = v.get("resultado")
    estado = RESULTADO_A_ESTADO.get(resultado) if resultado else None
    if estado:
        actual = conn.execute("SELECT * FROM item_parte_estado WHERE item_id = %s AND parte_id = %s",
                              (item["id"], parte["id"])).fetchone()
        if actual is None or forzar or RANGO_ESTADO[estado] >= RANGO_ESTADO[actual["estado"]]:
            conn.execute(
                "INSERT INTO item_parte_estado (item_id, parte_id, estado, telefono_id, respondente, encuestador, fecha)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (item_id, parte_id) DO UPDATE SET estado = EXCLUDED.estado,"
                " telefono_id = coalesce(EXCLUDED.telefono_id, item_parte_estado.telefono_id),"
                " respondente = coalesce(EXCLUDED.respondente, item_parte_estado.respondente),"
                " encuestador = coalesce(EXCLUDED.encuestador, item_parte_estado.encuestador),"
                " fecha = coalesce(EXCLUDED.fecha, item_parte_estado.fecha)",
                (item["id"], parte["id"], estado, tel_usado["id"] if tel_usado else None, v.get("resp_nombre"),
                 linaje.get("encuestador"), linaje.get("fecha")))
            aplicado["estado_parte"] = estado
    if resultado in cfg.get("contacto_efectivo", []) and linaje.get("fecha"):
        r = conn.execute(
            "UPDATE empresa SET ultimo_contacto_efectivo = %s WHERE id = %s"
            " AND (ultimo_contacto_efectivo IS NULL OR ultimo_contacto_efectivo < %s) RETURNING id",
            (linaje["fecha"], empresa_id, linaje["fecha"])).fetchone()
        if r:
            aplicado["ultimo_contacto_efectivo"] = linaje["fecha"]
    return aplicado
