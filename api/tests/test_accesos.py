"""Alta de usuarios con enlace de acceso (SPEC_alta_usuarios_enlace_acceso, R10).

Firebase Authentication se simula con CuentasMemoria y el SMTP reemplazando correo._mandar.
"""
import logging
import smtplib

import pytest

from app import accesos, correo, settings

CLAVE_SMTP = "clave-de-aplicacion-secreta"


@pytest.fixture
def cuentas(monkeypatch):
    c = accesos.CuentasMemoria()
    monkeypatch.setattr(accesos, "_proveedor", c)
    return c


@pytest.fixture
def buzon(monkeypatch):
    """Correos 'enviados'. Con buzon.falla = excepción, el SMTP falla con ese error."""

    class Buzon(list):
        falla = None

    b = Buzon()

    def mandar(destinatario, asunto, cuerpo):
        if b.falla is not None:
            raise b.falla
        b.append({"para": destinatario, "asunto": asunto, "cuerpo": cuerpo})

    monkeypatch.setattr(settings, "SMTP_PASSWORD", CLAVE_SMTP)
    monkeypatch.setattr(correo, "_mandar", mandar)
    monkeypatch.setattr(correo, "ESPERA_S", 0)
    return b


def alta(api, email="nueva@equipos.com.uy", rol="coordinador", **kw):
    r = api.post("/usuarios", json={"email": email, "nombre": "Nueva Persona", "rol": rol, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_alta_crea_cuenta_verificada_y_manda_bienvenida(api, sql, cuentas, buzon):
    r = alta(api)
    assert r["estado"] == "creado" and r["correo"]["enviado"] is True
    assert "enlace" not in r
    c = cuentas.buscar("nueva@equipos.com.uy")
    assert c.verificada is True and c.deshabilitada is False
    assert sql.execute("SELECT rol FROM usuario WHERE email = 'nueva@equipos.com.uy'").fetchone()["rol"] == "coordinador"
    assert len(buzon) == 1 and buzon[0]["para"] == "nueva@equipos.com.uy"
    assert buzon[0]["asunto"].startswith("Tu acceso")
    assert "vence en una hora" in buzon[0]["cuerpo"] and "coordinador/a de campo" in buzon[0]["cuerpo"]
    assert "Este correo se envió automáticamente" in buzon[0]["cuerpo"]
    envio = sql.execute("SELECT * FROM correo_envio").fetchone()
    assert (envio["tipo"], envio["estado"], envio["disparado_por"]) == ("bienvenida", "enviado", "admin@equipos.com.uy")


def test_alta_con_smtp_fallido_devuelve_el_enlace(api, sql, cuentas, buzon, caplog):
    buzon.falla = smtplib.SMTPAuthenticationError(535, f"5.7.8 Username and Password not accepted {CLAVE_SMTP}".encode())
    caplog.set_level(logging.DEBUG)
    r = alta(api)
    assert r["estado"] == "creado" and r["correo"]["enviado"] is False
    assert "rechazó la credencial" in r["correo"]["detalle"]
    assert CLAVE_SMTP not in str(r)
    enlace = r["enlace"]
    assert enlace.startswith(settings.APP_URL)
    assert cuentas.buscar("nueva@equipos.com.uy") is not None
    assert sql.execute("SELECT count(*) AS n FROM usuario WHERE email = 'nueva@equipos.com.uy'").fetchone()["n"] == 1
    # El enlace no queda en auditoría, en correo_envio ni en los logs; la clave SMTP tampoco
    envio = sql.execute("SELECT * FROM correo_envio").fetchone()
    assert envio["estado"] == "fallido" and enlace not in str(envio) and CLAVE_SMTP not in str(envio)
    assert enlace not in str(sql.execute("SELECT detalle FROM auditoria").fetchall())
    assert enlace not in caplog.text and CLAVE_SMTP not in caplog.text


def test_errores_transitorios_se_reintentan(api, sql, cuentas, buzon, monkeypatch):
    intentos = []

    def mandar(destinatario, asunto, cuerpo):
        intentos.append(1)
        if len(intentos) < 3:
            raise ConnectionRefusedError("sin conexión")

    monkeypatch.setattr(correo, "_mandar", mandar)
    r = alta(api)
    assert r["correo"]["enviado"] is True and len(intentos) == 3
    assert sql.execute("SELECT intentos FROM correo_envio").fetchone()["intentos"] == 3


def test_alta_de_email_con_cuenta_existente(api, sql, cuentas, buzon):
    c = cuentas.crear("vieja@equipos.com.uy", None, deshabilitada=False)
    c.verificada = False  # creada a mano en la consola
    r = alta(api, email="vieja@equipos.com.uy")
    assert r["estado"] == "ya_existia" and "Reenviar acceso" in r["mensaje"]
    assert len(cuentas.cuentas) == 1 and cuentas.buscar("vieja@equipos.com.uy").verificada is True
    assert buzon == [] and "enlace" not in r


def test_editar_no_manda_correo(api, sql, cuentas, buzon):
    alta(api)
    buzon.clear()
    r = alta(api, rol="jefe", exportar_contactos=True)
    assert r["estado"] == "actualizado" and buzon == []
    assert sql.execute("SELECT rol FROM usuario WHERE email = 'nueva@equipos.com.uy'").fetchone()["rol"] == "jefe"


def test_reenviar_bienvenida_o_restablecer(api, sql, cuentas, buzon):
    alta(api)
    r = api.post("/usuarios/nueva@equipos.com.uy/reenviar-acceso").json()
    assert r["correo"]["tipo"] == "bienvenida" and buzon[-1]["asunto"].startswith("Tu acceso")
    cuentas.buscar("nueva@equipos.com.uy").ultimo_ingreso_ms = 1_790_000_000_000  # ya ingresó
    r = api.post("/usuarios/nueva@equipos.com.uy/reenviar-acceso").json()
    assert r["correo"]["tipo"] == "restablecer" and buzon[-1]["asunto"].startswith("Restablecé")
    u = sql.execute("SELECT * FROM usuario WHERE email = 'nueva@equipos.com.uy'").fetchone()
    assert u["reenvios"] == 2 and u["ultimo_reenvio_por"] == "admin@equipos.com.uy" and u["ultimo_reenvio_en"]
    acciones = [a["accion"] for a in sql.execute("SELECT accion FROM auditoria WHERE objeto_id = 'nueva@equipos.com.uy'")]
    assert acciones.count("usuario.reenviar_acceso") == 2


def test_reenviar_crea_la_cuenta_si_no_existe(api, sql, cuentas, buzon):
    # usuario registrado antes de este cambio, sin cuenta de Firebase
    r = api.post("/usuarios/coord@equipos.com.uy/reenviar-acceso").json()
    assert r["estado"] == "cuenta_creada" and r["correo"]["tipo"] == "bienvenida"
    assert cuentas.buscar("coord@equipos.com.uy").verificada is True
    assert api.post("/usuarios/nadie@equipos.com.uy/reenviar-acceso").status_code == 404


def test_desactivar_y_reactivar(api, sql, cuentas, buzon):
    alta(api)
    alta(api, activo=False)
    assert cuentas.buscar("nueva@equipos.com.uy").deshabilitada is True
    r = api.c.get("/api/me", headers={"X-Dev-User": "nueva@equipos.com.uy"})
    assert r.status_code == 403 and "Tu acceso está desactivado" in r.json()["detail"]
    assert api.post("/usuarios/nueva@equipos.com.uy/reenviar-acceso").status_code == 409
    alta(api, activo=True)
    assert cuentas.buscar("nueva@equipos.com.uy").deshabilitada is False
    assert api.c.get("/api/me", headers={"X-Dev-User": "nueva@equipos.com.uy"}).status_code == 200


def test_admin_no_puede_desactivarse(api, cuentas, buzon):
    r = api.post("/usuarios", json={"email": "admin@equipos.com.uy", "rol": "admin", "activo": False})
    assert r.status_code == 422


def test_solo_administradores(api, cuentas, buzon):
    for rol in ("steward", "jefe", "coordinador", "lectura"):
        assert api.post("/usuarios", rol=rol, json={"email": "x@equipos.com.uy", "rol": "lectura"}).status_code == 403
        assert api.post("/usuarios/coord@equipos.com.uy/reenviar-acceso", rol=rol).status_code == 403
        assert api.get("/usuarios", rol=rol).status_code == 403


def test_listado_con_cuenta_y_ultimo_correo(api, cuentas, buzon):
    alta(api)
    u = {x["email"]: x for x in api.get("/usuarios").json()}
    nueva = u["nueva@equipos.com.uy"]
    assert nueva["correo_estado"] == "enviado" and nueva["cuenta"]["verificada"] is True
    assert nueva["cuenta"]["ultimo_ingreso"] is None
    assert u["coord@equipos.com.uy"]["cuenta"] is None


def test_mensaje_de_usuario_no_registrado(api):
    r = api.c.get("/api/me", headers={"X-Dev-User": "desconocida@equipos.com.uy"})
    assert r.status_code == 403 and "Pedile a un administrador" in r.json()["detail"]


def test_invitar_admins_iniciales(api, sql, cuentas, buzon, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", ["jefa.ti@equipos.com.uy"])
    job = {"X-Job-Token": "token-job"}
    r = api.c.post("/api/jobs/invitar-admins", headers=job, json={}).json()["resultados"]
    assert r[0]["correo"]["enviado"] is True and r[0]["estado"] == "cuenta_creada"
    assert sql.execute("SELECT rol FROM usuario WHERE email = 'jefa.ti@equipos.com.uy'").fetchone()["rol"] == "admin"
    # segunda vez sin forzar: no se toca la cuenta ni se manda correo
    buzon.clear()
    r = api.c.post("/api/jobs/invitar-admins", headers=job, json={}).json()["resultados"]
    assert r[0]["estado"] == "ya_existia" and buzon == []
    # con forzar (./infra/desplegar.sh invitar): llega un enlace nuevo
    r = api.c.post("/api/jobs/invitar-admins", headers=job, json={"forzar": True}).json()["resultados"]
    assert r[0]["estado"] == "reenviado" and len(buzon) == 1
    assert api.c.post("/api/jobs/invitar-admins", json={}).status_code == 401


def test_correo_envio_se_purga_a_los_90_dias(api, sql, cuentas, buzon):
    sql.execute("INSERT INTO correo_envio (tipo, destinatario, estado, disparado_por, fecha)"
                " VALUES ('bienvenida', 'vieja@x.com', 'enviado', 'a', now() - interval '91 days')")
    alta(api)
    assert sql.execute("SELECT count(*) AS n FROM correo_envio WHERE destinatario = 'vieja@x.com'").fetchone()["n"] == 0
