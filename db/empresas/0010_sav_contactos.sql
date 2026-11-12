-- 0010_sav_contactos.sql — Lo que trae el .sav y contactos completos
-- (SPEC_mejoras_sav_contactos_atributos_identidad, fases 2 y 3). Compatible hacia atrás:
-- solo agrega tablas y columnas; telefono_vinculo.contacto_id se conserva, pero ya no se usa.
SET search_path TO empresas, public;

-- ── F2.2 Relación contacto–teléfono (reemplaza telefono_vinculo.contacto_id, que admite un solo contacto) ──
-- relacion: 'se_hablo' (el .sav dice que se habló con el contacto a ese número) o 'del_contacto'
-- (número del contacto: EC_TEL_ALT, la carga o la ficha). claves: una por fila del .sav, para que
-- volver a ingerir no sume veces.
CREATE TABLE IF NOT EXISTS contacto_telefono (
  id           serial PRIMARY KEY,
  contacto_id  int NOT NULL REFERENCES contacto(id) ON DELETE CASCADE,
  telefono_id  int NOT NULL REFERENCES telefono(id),
  relacion     text NOT NULL DEFAULT 'del_contacto' CHECK (relacion IN ('se_hablo', 'del_contacto')),
  fuente_tipo  text NOT NULL,
  fuente_id    int,
  primera_vez  timestamptz NOT NULL DEFAULT now(),
  ultima_vez   timestamptz NOT NULL DEFAULT now(),
  veces        int NOT NULL DEFAULT 1,
  claves       text[] NOT NULL DEFAULT '{}',
  UNIQUE (contacto_id, telefono_id, relacion)
);
CREATE INDEX IF NOT EXISTS contacto_telefono_tel_idx ON contacto_telefono(telefono_id);
CREATE INDEX IF NOT EXISTS contacto_telefono_fuente_idx ON contacto_telefono(fuente_tipo, fuente_id);

INSERT INTO contacto_telefono (contacto_id, telefono_id, relacion, fuente_tipo, fuente_id, primera_vez, ultima_vez)
SELECT v.contacto_id, v.telefono_id, 'del_contacto', v.fuente_tipo, v.fuente_id, v.fecha, v.fecha
FROM telefono_vinculo v WHERE v.contacto_id IS NOT NULL
ON CONFLICT DO NOTHING;

-- ── F2.4 / F3.1 Historia de contactos: append-only, con la excepción de purga de la 0007 ──
-- campo: 'alta', 'nombre', 'cargo', 'area', 'email', 'sucursal', 'telefono', 'atributo.<clave>'.
-- Sin FK a contacto: al borrar un contacto (dato personal) su historia se purga en la misma transacción.
CREATE TABLE IF NOT EXISTS contacto_historia (
  id          bigserial PRIMARY KEY,
  contacto_id int NOT NULL,
  empresa_id  int NOT NULL,
  campo       text NOT NULL,
  valor       text,
  fuente_tipo text NOT NULL,
  fuente_id   int,
  actor       text,
  detalle     jsonb,
  fecha       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS contacto_historia_contacto_idx ON contacto_historia(contacto_id);
CREATE INDEX IF NOT EXISTS contacto_historia_empresa_idx ON contacto_historia(empresa_id);
CREATE INDEX IF NOT EXISTS contacto_historia_fuente_idx ON contacto_historia(fuente_tipo, fuente_id);
DROP TRIGGER IF EXISTS contacto_historia_append_only ON contacto_historia;
CREATE TRIGGER contacto_historia_append_only BEFORE UPDATE OR DELETE ON contacto_historia
  FOR EACH ROW EXECUTE FUNCTION append_only();

-- Los contactos que ya existen entran como «alta»
INSERT INTO contacto_historia (contacto_id, empresa_id, campo, valor, fuente_tipo, fuente_id, actor, detalle, fecha)
SELECT c.id, c.empresa_id, 'alta', c.nombre, c.fuente_tipo, c.fuente_id, 'migracion_0010', c.detalle, c.creado
FROM contacto c
WHERE NOT EXISTS (SELECT 1 FROM contacto_historia h WHERE h.contacto_id = c.id AND h.campo = 'alta');

-- ── F2.1 / F2.3 Filas del .sav: avisos por fila, fecha y encuestador (para contar sin depender del ítem) ──
ALTER TABLE sav_fila ADD COLUMN IF NOT EXISTS avisos jsonb NOT NULL DEFAULT '[]';
ALTER TABLE sav_fila ADD COLUMN IF NOT EXISTS fecha timestamptz;
ALTER TABLE sav_fila ADD COLUMN IF NOT EXISTS encuestador text;
CREATE INDEX IF NOT EXISTS sav_fila_parte_idx ON sav_fila(parte_id);
CREATE INDEX IF NOT EXISTS sav_fila_fecha_idx ON sav_fila(fecha);

-- ── F3.3 Atributos de contacto: ámbito del atributo y valores por contacto ──
ALTER TABLE atributo ADD COLUMN IF NOT EXISTS ambito text NOT NULL DEFAULT 'empresa';
ALTER TABLE atributo DROP CONSTRAINT IF EXISTS atributo_ambito_check;
ALTER TABLE atributo ADD CONSTRAINT atributo_ambito_check CHECK (ambito IN ('empresa', 'contacto'));

CREATE TABLE IF NOT EXISTS contacto_atributo (
  contacto_id  int NOT NULL REFERENCES contacto(id) ON DELETE CASCADE,
  atributo_id  int NOT NULL REFERENCES atributo(id),
  valor_texto  text,
  valor_numero numeric,
  valor_fecha  date,
  crudo        text,
  fuente_tipo  text NOT NULL,
  fuente_id    int,
  actualizado  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (contacto_id, atributo_id)
);
CREATE INDEX IF NOT EXISTS contacto_atributo_atributo_idx ON contacto_atributo(atributo_id);
CREATE INDEX IF NOT EXISTS contacto_fuente_idx ON contacto(fuente_tipo, fuente_id);
