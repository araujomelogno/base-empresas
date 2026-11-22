-- 0016_archivo_fila.sql — Crear la carga sin esperas mudas (SPEC_crear_carga_asincrona; D51).
-- El archivo se parsea una sola vez, al analizarlo: sus filas quedan en archivo_fila y de ahí salen la traducción de
-- valores, la validación y los lotes de la carga. carga_fila pasa a guardar solo el lote de cada fila.
SET search_path TO empresas, public;

CREATE TABLE IF NOT EXISTS archivo_fila (
  archivo_id int NOT NULL REFERENCES archivo(id) ON DELETE CASCADE,
  fila       int NOT NULL,              -- número de fila del archivo (la primera de datos es la 2)
  datos      jsonb NOT NULL,
  PRIMARY KEY (archivo_id, fila)
);

ALTER TABLE archivo ADD COLUMN IF NOT EXISTS columnas jsonb;              -- encabezados, en orden
ALTER TABLE archivo ADD COLUMN IF NOT EXISTS n_filas int;
ALTER TABLE archivo ADD COLUMN IF NOT EXISTS filas_guardadas timestamptz; -- NULL: sus filas no están en archivo_fila

-- Las cargas nuevas toman los datos de archivo_fila; las creadas con la versión anterior los tienen acá
ALTER TABLE carga_fila ALTER COLUMN datos DROP NOT NULL;

-- A4: «Siguiente» dos veces no crea dos cargas
ALTER TABLE carga ADD COLUMN IF NOT EXISTS clave text;
CREATE UNIQUE INDEX IF NOT EXISTS carga_clave_idx ON carga(responsable, clave) WHERE clave IS NOT NULL;
CREATE INDEX IF NOT EXISTS carga_archivo_idx ON carga(archivo_id);
