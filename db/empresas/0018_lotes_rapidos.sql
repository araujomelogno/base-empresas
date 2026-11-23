-- 0018_lotes_rapidos.sql — Lotes de carga rápidos (SPEC_lotes_rapidos; D53).
-- Cada lote guarda cuántas consultas hizo, para medir el ritmo (V3).
SET search_path TO empresas, public;

ALTER TABLE carga_lote ADD COLUMN IF NOT EXISTS consultas int;
ALTER TABLE carga_lote ADD COLUMN IF NOT EXISTS preview_consultas int;
