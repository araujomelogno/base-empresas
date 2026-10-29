-- 0001_init.sql — Esquema base de la Base de Empresas (fase 1)
-- Un solo esquema `empresas`. Las tablas de historia y auditoría son append-only
-- (ver triggers al final). Requerimientos: R1.1–R1.13 del spec.

CREATE SCHEMA IF NOT EXISTS empresas;
SET search_path TO empresas, public;

-- ─────────────────────────────────────────────────────────────
-- Usuarios y roles (R1.13)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE usuario (
  id            serial PRIMARY KEY,
  email         text NOT NULL UNIQUE,
  nombre        text,
  rol           text NOT NULL CHECK (rol IN ('admin','steward','jefe','coordinador','lectura')),
  exportar_contactos boolean NOT NULL DEFAULT false,   -- permiso específico (Ley 18.331)
  activo        boolean NOT NULL DEFAULT true,
  creado        timestamptz NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────
-- Configuración versionada (R1.12)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE config_version (
  version     serial PRIMARY KEY,
  parametros  jsonb NOT NULL,
  autor       text NOT NULL,
  comentario  text,
  fecha       timestamptz NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────
-- Catálogo de naturalezas jurídicas (R1.4)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE naturaleza_juridica (
  id        serial PRIMARY KEY,
  codigo    text NOT NULL UNIQUE,
  nombre    text NOT NULL,
  excluida  boolean NOT NULL DEFAULT false   -- espejo de config.naturalezas_excluidas
);

-- ─────────────────────────────────────────────────────────────
-- Cargas (lotes de ingesta, R1.3)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE archivo (
  id         serial PRIMARY KEY,
  nombre     text NOT NULL,
  tipo       text NOT NULL,                 -- xlsx | csv | sav
  sha256     text NOT NULL,
  ruta       text NOT NULL,                 -- ruta en el bucket o en disco
  tamano     bigint NOT NULL,
  subido_por text NOT NULL,
  fecha      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE carga_plantilla (
  tipo_fuente text PRIMARY KEY,
  mapeo       jsonb NOT NULL,
  actualizado timestamptz NOT NULL DEFAULT now(),
  autor       text NOT NULL
);

CREATE TABLE carga (
  id           serial PRIMARY KEY,
  archivo_id   int NOT NULL REFERENCES archivo(id),
  fuente       text NOT NULL,               -- nombre de la fuente (p. ej. "Estudio X 2025")
  tipo_fuente  text NOT NULL,               -- tipo para la plantilla de mapeo
  licencia     text NOT NULL,
  responsable  text NOT NULL,
  regla_fusion text NOT NULL DEFAULT 'rut' CHECK (regla_fusion IN ('rut','telefono','razon_social','dominio')),
  confianza    int NOT NULL DEFAULT 50 CHECK (confianza BETWEEN 0 AND 100),
  mapeo        jsonb NOT NULL,
  estado       text NOT NULL DEFAULT 'analizando'
               CHECK (estado IN ('analizando','preview','en_proceso','confirmada','deshecha','error')),
  conteos      jsonb NOT NULL DEFAULT '{}'::jsonb,
  error        text,
  config_version int,
  fecha        timestamptz NOT NULL DEFAULT now(),
  confirmada   timestamptz,
  deshecha     timestamptz
);

CREATE TABLE carga_rechazo (
  id        bigserial PRIMARY KEY,
  carga_id  int NOT NULL REFERENCES carga(id) ON DELETE CASCADE,
  fila      int NOT NULL,
  motivo    text NOT NULL,
  datos     jsonb NOT NULL
);
CREATE INDEX ON carga_rechazo(carga_id);

-- ─────────────────────────────────────────────────────────────
-- Empresas (R1.1)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE empresa (
  id            serial PRIMARY KEY,
  rut           char(12) NOT NULL UNIQUE,
  razon_social  text,
  fantasia      text,
  naturaleza_id int REFERENCES naturaleza_juridica(id),
  ciiu          text,
  tamano        text,
  departamento  text,
  localidad     text,
  direccion     text,
  web           text,
  estado        text NOT NULL DEFAULT 'desconocida' CHECK (estado IN ('activa','cerrada','desconocida')),
  baja          text CHECK (baja IN ('fusionada','anulada')),   -- estados de sistema
  fusionada_en  int REFERENCES empresa(id),
  ultimo_contacto_efectivo timestamptz,
  carga_alta_id int REFERENCES carga(id),
  creado        timestamptz NOT NULL DEFAULT now(),
  actualizado   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON empresa(naturaleza_id);
CREATE INDEX ON empresa(departamento);
CREATE INDEX ON empresa(tamano);
CREATE INDEX empresa_razon_idx ON empresa (lower(razon_social));

-- Linaje por campo: valor, fuente, fecha, actor y confianza. Append-only.
CREATE TABLE empresa_campo_historia (
  id          bigserial PRIMARY KEY,
  empresa_id  int NOT NULL REFERENCES empresa(id),
  campo       text NOT NULL,
  valor       text,
  fuente_tipo text NOT NULL CHECK (fuente_tipo IN ('carga','sav','sala','manual','fusion','sistema')),
  fuente_id   int,
  confianza   int NOT NULL,
  actor       text NOT NULL,
  detalle     jsonb,                          -- linaje extra: estudio, parte, encuestador
  fecha       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON empresa_campo_historia(empresa_id, campo);
CREATE INDEX ON empresa_campo_historia(fuente_tipo, fuente_id);

CREATE TABLE sucursal (
  id           serial PRIMARY KEY,
  empresa_id   int NOT NULL REFERENCES empresa(id),
  direccion    text,
  departamento text,
  localidad    text,
  fuente_tipo  text NOT NULL,
  fuente_id    int,
  creado       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON sucursal(empresa_id);

-- Dato personal (Ley 18.331)
CREATE TABLE contacto (
  id          serial PRIMARY KEY,
  empresa_id  int NOT NULL REFERENCES empresa(id),
  sucursal_id int REFERENCES sucursal(id),
  nombre      text NOT NULL,
  cargo       text,
  area        text,
  email       text,
  fuente_tipo text NOT NULL,
  fuente_id   int,
  detalle     jsonb,
  creado      timestamptz NOT NULL DEFAULT now(),
  actualizado timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON contacto(empresa_id);

CREATE TABLE empresa_fusion (
  id            serial PRIMARY KEY,
  absorbente_id int NOT NULL REFERENCES empresa(id),
  absorbida_id  int NOT NULL REFERENCES empresa(id),
  movidos       jsonb NOT NULL,      -- ids movidos para poder deshacer
  actor         text NOT NULL,
  motivo        text,
  fecha         timestamptz NOT NULL DEFAULT now(),
  deshecha      timestamptz,
  deshecha_por  text
);

-- ─────────────────────────────────────────────────────────────
-- Teléfonos (R1.2)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE telefono (
  id            serial PRIMARY KEY,
  e164          text UNIQUE,                     -- NULL si no se pudo normalizar
  crudo         text NOT NULL,
  tipo          text NOT NULL CHECK (tipo IN ('fijo','celular','especial','internacional','invalido')),
  estado        text NOT NULL DEFAULT 'valido' CHECK (estado IN ('valido','invalido','inexistente')),
  intermediario text CHECK (intermediario IN ('sospechoso','confirmado','liberado')),
  intermediario_n int,                          -- RUTs vinculados al resolver
  intermediario_fecha timestamptz,
  intermediario_por text,
  creado        timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX telefono_crudo_invalido ON telefono(crudo) WHERE e164 IS NULL;

CREATE TABLE telefono_vinculo (
  id          serial PRIMARY KEY,
  telefono_id int NOT NULL REFERENCES telefono(id),
  empresa_id  int NOT NULL REFERENCES empresa(id),
  contacto_id int REFERENCES contacto(id),
  sucursal_id int REFERENCES sucursal(id),
  estado      text NOT NULL DEFAULT 'sin_verificar'
              CHECK (estado IN ('sin_verificar','verificado','no_corresponde','intermediario','inexistente')),
  fuente_tipo text NOT NULL,
  fuente_id   int,
  fecha       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (telefono_id, empresa_id)
);
CREATE INDEX ON telefono_vinculo(empresa_id);

-- Historia de estados del vínculo. Append-only.
CREATE TABLE telefono_vinculo_historia (
  id          bigserial PRIMARY KEY,
  vinculo_id  int NOT NULL,
  telefono_id int NOT NULL,
  empresa_id  int NOT NULL,
  estado      text NOT NULL,
  fuente_tipo text NOT NULL,
  fuente_id   int,
  actor       text NOT NULL,
  detalle     jsonb,
  fecha       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON telefono_vinculo_historia(empresa_id);

-- ─────────────────────────────────────────────────────────────
-- No llamar (R1.4)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE no_llamar (
  id          serial PRIMARY KEY,
  alcance     text NOT NULL CHECK (alcance IN ('empresa','telefono','contacto')),
  objeto_id   int NOT NULL,
  motivo      text NOT NULL,
  solicitante text NOT NULL,
  registrado_por text NOT NULL,
  fecha       timestamptz NOT NULL DEFAULT now(),
  activo      boolean NOT NULL DEFAULT true
);
CREATE INDEX ON no_llamar(alcance, objeto_id) WHERE activo;

-- Bandeja de revisión de coincidencias que no son por RUT (R1.3)
CREATE TABLE revision_fusion (
  id           serial PRIMARY KEY,
  carga_id     int NOT NULL REFERENCES carga(id),
  fila         int NOT NULL,
  datos        jsonb NOT NULL,
  criterio     text NOT NULL,
  candidata_id int NOT NULL REFERENCES empresa(id),
  estado       text NOT NULL DEFAULT 'pendiente'
               CHECK (estado IN ('pendiente','alta','actualizar_candidata','descartada')),
  resuelto_por text,
  resuelto     timestamptz
);

-- ─────────────────────────────────────────────────────────────
-- Estudios, partes y muestras (R1.5, R1.6)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE estudio (
  id          serial PRIMARY KEY,
  nombre      text NOT NULL,
  cliente     text,
  campo_desde date NOT NULL,
  campo_hasta date NOT NULL,
  creado_por  text NOT NULL,
  creado      timestamptz NOT NULL DEFAULT now(),
  CHECK (campo_hasta >= campo_desde)
);

CREATE TABLE parte (
  id         serial PRIMARY KEY,
  estudio_id int NOT NULL REFERENCES estudio(id),
  nombre     text NOT NULL,
  survey_id  text,
  link_base  text,
  respondente_objetivo text,
  plantilla_mapeo jsonb,
  creado     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE marco_snapshot (
  id             serial PRIMARY KEY,
  config_version int NOT NULL REFERENCES config_version(version),
  criterios      jsonb NOT NULL,
  fecha          timestamptz NOT NULL DEFAULT now(),
  n              int NOT NULL
);

CREATE TABLE marco_snapshot_item (
  snapshot_id int NOT NULL REFERENCES marco_snapshot(id),
  empresa_id  int NOT NULL REFERENCES empresa(id),
  estrato     text NOT NULL,
  PRIMARY KEY (snapshot_id, empresa_id)
);

CREATE TABLE muestra (
  id             serial PRIMARY KEY,
  estudio_id     int NOT NULL REFERENCES estudio(id),
  nombre         text NOT NULL,
  criterios      jsonb NOT NULL,
  semilla        bigint,
  config_version int REFERENCES config_version(version),
  snapshot_id    int REFERENCES marco_snapshot(id),
  estado         text NOT NULL DEFAULT 'borrador' CHECK (estado IN ('borrador','activa','cerrada')),
  resultado      jsonb,                      -- exclusiones por regla y avisos por estrato
  creado_por     text NOT NULL,
  sorteada_por   text,
  sorteada       timestamptz,
  creado         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE muestra_item (
  id          serial PRIMARY KEY,
  muestra_id  int NOT NULL REFERENCES muestra(id),
  empresa_id  int NOT NULL REFERENCES empresa(id),
  estrato     text NOT NULL,
  rol         text NOT NULL CHECK (rol IN ('titular','reemplazo')),
  orden       int NOT NULL,                  -- orden sorteado dentro del estrato
  liberado    boolean NOT NULL DEFAULT false,
  liberado_por text,
  liberado_motivo text,
  liberado_fecha timestamptz,
  UNIQUE (muestra_id, empresa_id),
  UNIQUE (muestra_id, estrato, orden)
);
CREATE INDEX ON muestra_item(empresa_id);

CREATE TABLE item_parte_estado (
  item_id     int NOT NULL REFERENCES muestra_item(id),
  parte_id    int NOT NULL REFERENCES parte(id),
  estado      text NOT NULL DEFAULT 'pendiente'
              CHECK (estado IN ('pendiente','en_curso','completa','rechazo','no_contactable','fuera_de_marco')),
  telefono_id int REFERENCES telefono(id),
  respondente text,
  encuestador text,
  fecha       timestamptz,
  PRIMARY KEY (item_id, parte_id)
);

-- ─────────────────────────────────────────────────────────────
-- CDR (R1.8)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE cdr_lote (
  id          serial PRIMARY KEY,
  recibido    timestamptz NOT NULL DEFAULT now(),
  origen      text,
  conteos     jsonb NOT NULL
);

CREATE TABLE intento (
  id           bigserial PRIMARY KEY,
  cdr_id       text NOT NULL UNIQUE,
  lote_id      int REFERENCES cdr_lote(id),
  telefono_id  int NOT NULL REFERENCES telefono(id),
  empresas     int[] NOT NULL,             -- empresas vinculadas al momento de la llamada
  item_id      int REFERENCES muestra_item(id),
  encuestador  text,
  inicio       timestamptz NOT NULL,
  franja       text,
  duracion     int,
  disposicion  text,
  disposicion_encuesta text,
  campania     text,
  destino_crudo text
);
CREATE INDEX ON intento(telefono_id);
CREATE INDEX ON intento(item_id);
CREATE INDEX ON intento(inicio);
CREATE INDEX ON intento USING gin (empresas);

-- ─────────────────────────────────────────────────────────────
-- Ingesta del .sav (R1.9)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE sav_ingesta (
  id          serial PRIMARY KEY,
  parte_id    int NOT NULL REFERENCES parte(id),
  archivo_id  int NOT NULL REFERENCES archivo(id),
  mapeo       jsonb,
  conteos     jsonb NOT NULL DEFAULT '{}'::jsonb,
  estado      text NOT NULL DEFAULT 'analizada'
              CHECK (estado IN ('analizada','en_proceso','confirmada','error')),
  error       text,
  actor       text NOT NULL,
  fecha       timestamptz NOT NULL DEFAULT now(),
  confirmada  timestamptz
);

CREATE TABLE sav_fila (
  id          bigserial PRIMARY KEY,
  ingesta_id  int NOT NULL REFERENCES sav_ingesta(id),
  parte_id    int NOT NULL REFERENCES parte(id),
  response_id text NOT NULL,
  item_id     int REFERENCES muestra_item(id),
  valores     jsonb NOT NULL,              -- valores crudos para remapear
  aplicado    jsonb,                       -- resumen de lo aplicado a la base
  motivo      text,                        -- por qué quedó sin asociar
  actualizado timestamptz NOT NULL DEFAULT now(),
  UNIQUE (parte_id, response_id)
);
CREATE INDEX ON sav_fila(ingesta_id);

-- ─────────────────────────────────────────────────────────────
-- Conciliación (R1.8, R1.9)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE conciliacion (
  id          serial PRIMARY KEY,
  tipo        text NOT NULL CHECK (tipo IN ('intento','sav_fila')),
  objeto_id   bigint NOT NULL,
  motivo      text NOT NULL,
  candidatos  jsonb,
  estado      text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente','resuelta','descartada')),
  resolucion  jsonb,
  resuelto_por text,
  resuelto    timestamptz,
  creado      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tipo, objeto_id)
);

-- ─────────────────────────────────────────────────────────────
-- Tareas diferidas (Cloud Tasks) con progreso visible
-- ─────────────────────────────────────────────────────────────
CREATE TABLE tarea (
  id         serial PRIMARY KEY,
  tipo       text NOT NULL,
  payload    jsonb NOT NULL,
  estado     text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente','corriendo','ok','error')),
  progreso   int NOT NULL DEFAULT 0,
  total      int,
  resultado  jsonb,
  error      text,
  creado_por text NOT NULL,
  creado     timestamptz NOT NULL DEFAULT now(),
  terminado  timestamptz
);

-- ─────────────────────────────────────────────────────────────
-- Auditoría (R1.13). Append-only; export diario a BigQuery.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE auditoria (
  id       bigserial PRIMARY KEY,
  actor    text NOT NULL,
  accion   text NOT NULL,
  objeto   text NOT NULL,
  objeto_id text,
  detalle  jsonb,
  fecha    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON auditoria(fecha);
CREATE INDEX ON auditoria(objeto, objeto_id);

CREATE TABLE export_estado (
  nombre   text PRIMARY KEY,
  ultimo_id bigint NOT NULL DEFAULT 0,
  fecha    timestamptz NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────
-- Append-only: historia y auditoría no admiten UPDATE ni DELETE
-- ─────────────────────────────────────────────────────────────
CREATE FUNCTION append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'La tabla % es append-only', TG_TABLE_NAME;
END $$;

CREATE TRIGGER auditoria_append_only BEFORE UPDATE OR DELETE ON auditoria
  FOR EACH ROW EXECUTE FUNCTION append_only();
CREATE TRIGGER historia_append_only BEFORE UPDATE OR DELETE ON empresa_campo_historia
  FOR EACH ROW EXECUTE FUNCTION append_only();
CREATE TRIGGER vinculo_historia_append_only BEFORE UPDATE OR DELETE ON telefono_vinculo_historia
  FOR EACH ROW EXECUTE FUNCTION append_only();
