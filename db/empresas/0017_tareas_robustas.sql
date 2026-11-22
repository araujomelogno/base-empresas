-- 0017_tareas_robustas.sql — Robustez de las cargas por lotes (SPEC_cargas_lotes_robustez; D52).
-- Una tarea cuyo proceso muere se retoma sola: el que la corre deja un latido (tarea.actualizado, cada 30 s) y su
-- marca de dueño; si el latido se detiene más de 3 minutos, el próximo intento la toma.
SET search_path TO empresas, public;

ALTER TABLE tarea ADD COLUMN IF NOT EXISTS dueno text;                          -- quién la está corriendo ahora
ALTER TABLE tarea ADD COLUMN IF NOT EXISTS paso_inicio timestamptz;             -- cuándo empezó el paso (o lote) en curso
ALTER TABLE tarea ADD COLUMN IF NOT EXISTS reintentos_auto int NOT NULL DEFAULT 0;  -- reanudaciones automáticas seguidas
