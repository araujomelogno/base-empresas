"""Tests del job del CDR: mapeo fila → payload, lotes, estado incremental (MySQL y HTTP simulados)."""
import datetime as dt
import json
from zoneinfo import ZoneInfo

import pytest

import cdr_job

TZ = ZoneInfo("America/Montevideo")


def fila(uid, calldate, dst="29011234", billsec=30, **extra):
    return {"uniqueid": uid, "calldate": dt.datetime.fromisoformat(calldate), "src": "201", "dst": dst,
            "duration": billsec + 10, "billsec": billsec, "disposition": "ANSWERED", "userfield": "Contesta|Completa",
            "peeraccount": "SIP/enc01", "accountcode": "EMP-2609", **extra}


@pytest.fixture
def cfg():
    return {"mysql": {}, "api_url": "https://api.ejemplo", "token": "tok", "sql": cdr_job.SQL_DEFECTO, "lote": 2,
            "tz": TZ, "origen": "uContact", "timeout": 5, "reintentos": 3}


def args(tmp_path, *extra):
    return cdr_job.parser().parse_args(["--estado", str(tmp_path / "estado.json"), *extra])


class FalsoPost:
    """Simula la API: registra los lotes y puede fallar en el lote N."""

    def __init__(self, falla_en=None):
        self.llamadas = []
        self.falla_en = falla_en

    def __call__(self, url, cuerpo, token, timeout, reintentos):
        self.llamadas.append((url, cuerpo, token))
        if self.falla_en is not None and len(self.llamadas) == self.falla_en:
            raise cdr_job.ErrorEnvio("HTTP 503")
        n = len(cuerpo.get("llamadas", []))
        return {"lote_id": len(self.llamadas), "recibidas": n, "intentos_nuevos": n, "no_cruzan_por_tipo": {"fijo": 1}}


def test_fila_a_llamada():
    ll = cdr_job.fila_a_llamada(fila("1730.5", "2026-10-28 10:15:00", dst=" 099123456 "), TZ)
    assert ll == {"cdr_id": "1730.5", "inicio": "2026-10-28T10:15:00-03:00", "destino": "099123456",
                  "encuestador": "SIP/enc01", "duracion": 30, "userfield": "Contesta|Completa",
                  "disposicion": "ANSWERED", "campania": "EMP-2609"}


def test_fila_a_llamada_manual_y_sin_billsec():
    f = fila("2", "2026-10-28 22:00:00", accountcode="", userfield="")
    f["billsec"] = None
    ll = cdr_job.fila_a_llamada(f, TZ)
    assert ll["campania"] is None and ll["userfield"] is None and ll["duracion"] == f["duration"]
    # calldate como texto también sirve
    f["calldate"] = "2026-10-28 22:00:00"
    assert cdr_job.fila_a_llamada(f, TZ)["inicio"] == "2026-10-28T22:00:00-03:00"


def test_lotes_y_deduplicar():
    assert [len(x) for x in cdr_job.lotes(list(range(5)), 2)] == [2, 2, 1]
    filas = [fila("1", "2026-10-28 10:00:00", billsec=0), fila("2", "2026-10-28 10:00:01"),
             fila("1", "2026-10-28 10:00:02", billsec=50)]
    d = cdr_job.deduplicar(filas)
    assert [f["uniqueid"] for f in d] == ["1", "2"] and d[0]["billsec"] == 50


def test_envia_en_lotes_y_avanza_estado(tmp_path, cfg, capsys):
    filas = [fila(str(i), f"2026-10-28 10:00:0{i}") for i in range(5)]
    post = FalsoPost()
    assert cdr_job.ejecutar(args(tmp_path), cfg, leer=lambda c, d, h: filas, post=post) == 0
    assert len(post.llamadas) == 3                       # lote de 2: 2 + 2 + 1
    url, cuerpo, token = post.llamadas[0]
    assert url == "https://api.ejemplo/api/intentos/lote" and token == "tok" and cuerpo["origen"] == "uContact"
    assert [ll["cdr_id"] for ll in cuerpo["llamadas"]] == ["0", "1"]
    estado = json.loads((tmp_path / "estado.json").read_text())
    assert estado["ultima_calldate"] == "2026-10-28 10:00:04" and estado["ultimo_uniqueid"] == "4"
    resumen = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert resumen["llamadas_enviadas"] == 5 and resumen["intentos_nuevos"] == 5
    assert resumen["no_cruzan_por_tipo"] == {"fijo": 3}


def test_estado_solo_avanza_con_post_exitoso(tmp_path, cfg):
    filas = [fila(str(i), f"2026-10-28 10:00:0{i}") for i in range(5)]
    assert cdr_job.ejecutar(args(tmp_path), cfg, leer=lambda c, d, h: filas, post=FalsoPost(falla_en=2)) == 1
    estado = json.loads((tmp_path / "estado.json").read_text())
    assert estado["ultima_calldate"] == "2026-10-28 10:00:01"   # solo el primer lote
    # sin ningún POST exitoso no se escribe estado
    otro = tmp_path / "otro"
    otro.mkdir()
    assert cdr_job.ejecutar(args(otro), cfg, leer=lambda c, d, h: filas, post=FalsoPost(falla_en=1)) == 1
    assert not (otro / "estado.json").exists()


def test_incremental_desde_el_estado(tmp_path, cfg):
    (tmp_path / "estado.json").write_text(json.dumps(
        {"ultima_calldate": "2026-10-28 10:00:05", "ultimo_uniqueid": "b", "uniqueids_en_ultima": ["a", "b"]}))
    pedidos = []

    def leer(c, desde, hasta):
        pedidos.append((desde, hasta))
        return [fila("a", "2026-10-28 10:00:05"), fila("b", "2026-10-28 10:00:05"), fila("c", "2026-10-28 10:00:05"),
                fila("d", "2026-10-28 11:00:00")]

    post = FalsoPost()
    cfg["lote"] = 10
    assert cdr_job.ejecutar(args(tmp_path), cfg, leer=leer, post=post) == 0
    assert pedidos == [(dt.datetime(2026, 10, 28, 10, 0, 5), None)]
    assert [ll["cdr_id"] for ll in post.llamadas[0][1]["llamadas"]] == ["c", "d"]
    estado = json.loads((tmp_path / "estado.json").read_text())
    assert estado["ultima_calldate"] == "2026-10-28 11:00:00" and estado["uniqueids_en_ultima"] == ["d"]


def test_mismo_segundo_entre_lotes_acumula_uniqueids():
    e = cdr_job.avanzar({}, [fila("a", "2026-10-28 10:00:05")])
    e = cdr_job.avanzar(e, [fila("b", "2026-10-28 10:00:05")])
    assert e["uniqueids_en_ultima"] == ["a", "b"]
    assert cdr_job.ya_enviada(fila("a", "2026-10-28 10:00:05"), e)
    assert not cdr_job.ya_enviada(fila("c", "2026-10-28 10:00:05"), e)


def test_reproceso_no_retrocede_el_estado(tmp_path, cfg):
    (tmp_path / "estado.json").write_text(json.dumps({"ultima_calldate": "2026-10-28 23:00:00", "uniqueids_en_ultima": ["z"]}))
    pedidos = []

    def leer(c, desde, hasta):
        pedidos.append((desde, hasta))
        return [fila("x", "2026-10-01 10:00:00")]

    post = FalsoPost()
    a = args(tmp_path, "--desde", "2026-10-01", "--hasta", "2026-10-02")
    assert cdr_job.ejecutar(a, cfg, leer=leer, post=post) == 0
    assert pedidos == [(dt.datetime(2026, 10, 1), dt.datetime(2026, 10, 2))]
    assert len(post.llamadas) == 1
    assert json.loads((tmp_path / "estado.json").read_text())["ultima_calldate"] == "2026-10-28 23:00:00"


def test_dry_run_escribe_payload_y_no_envia(tmp_path, cfg):
    salida = tmp_path / "payload.json"
    post = FalsoPost()
    a = args(tmp_path, "--dry-run", "--salida", str(salida))
    assert cdr_job.ejecutar(a, cfg, leer=lambda c, d, h: [fila("1", "2026-10-28 10:00:00")], post=post) == 0
    assert post.llamadas == [] and not (tmp_path / "estado.json").exists()
    payload = json.loads(salida.read_text())
    assert payload["origen"] == "uContact" and payload["llamadas"][0]["cdr_id"] == "1"


def test_exportar_auditoria(tmp_path, cfg):
    post = FalsoPost()
    a = args(tmp_path, "--exportar-auditoria")
    assert cdr_job.ejecutar(a, cfg, leer=lambda c, d, h: [], post=post) == 0
    assert post.llamadas[-1][0] == "https://api.ejemplo/api/jobs/auditoria-bq"


def test_post_json_reintenta_errores_de_red(monkeypatch):
    intentos = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"recibidas": 1}'

    def urlopen(req, timeout):
        intentos.append(req.headers)
        if len(intentos) < 3:
            raise cdr_job.urllib.error.URLError("conexión rechazada")
        return Resp()

    monkeypatch.setattr(cdr_job.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(cdr_job.time, "sleep", lambda s: None)
    assert cdr_job.post_json("http://x/api/intentos/lote", {"llamadas": []}, "tok", 5, 5) == {"recibidas": 1}
    assert len(intentos) == 3 and intentos[0]["X-job-token"] == "tok"


def test_post_json_no_reintenta_4xx(monkeypatch):
    def urlopen(req, timeout):
        raise cdr_job.urllib.error.HTTPError(req.full_url, 401, "no", {}, None)

    monkeypatch.setattr(cdr_job.urllib.request, "urlopen", urlopen)
    with pytest.raises(cdr_job.ErrorEnvio, match="401"):
        cdr_job.post_json("http://x", {}, "mal", 5, 5)


def test_cargar_env(tmp_path, monkeypatch):
    monkeypatch.delenv("MYSQL_DB", raising=False)
    monkeypatch.setenv("API_URL", "https://ya-definida")
    env = tmp_path / "x.env"
    env.write_text("# comentario\nMYSQL_DB=uc\nAPI_URL=https://otra/\nJOB_TOKEN='secreto'\n")
    monkeypatch.delenv("JOB_TOKEN", raising=False)
    cdr_job.cargar_env(env)
    c = cdr_job.config()
    assert c["mysql"]["database"] == "uc" and c["api_url"] == "https://ya-definida" and c["token"] == "secreto"
