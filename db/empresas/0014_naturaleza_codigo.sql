-- 0014_naturaleza_codigo.sql — Una naturaleza jurídica no puede tener el código vacío (D49).
-- Antes el alta no lo validaba y quedaron filas sin código, que no se podían editar ni borrar desde la pantalla.
-- NOT VALID: la regla vale para las filas nuevas y las modificadas, sin rechazar la migración por las que ya existen;
-- esas se corrigen (o se borran) desde Administración → Naturalezas jurídicas.
SET search_path TO empresas, public;

ALTER TABLE naturaleza_juridica DROP CONSTRAINT IF EXISTS naturaleza_codigo_no_vacio;
ALTER TABLE naturaleza_juridica ADD CONSTRAINT naturaleza_codigo_no_vacio CHECK (btrim(codigo) <> '') NOT VALID;
