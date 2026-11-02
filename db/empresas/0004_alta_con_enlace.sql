-- 0004_alta_con_enlace.sql — Alta de usuarios con enlace de acceso (SPEC_alta_usuarios_enlace_acceso).
-- Compatible hacia atrás: solo agrega columnas con valor por defecto y una tabla nueva.
SET search_path TO empresas, public;

-- Quién pidió el último reenvío del acceso y cuántos hubo (R4)
ALTER TABLE usuario
  ADD COLUMN IF NOT EXISTS reenvios          int NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS ultimo_reenvio_por text,
  ADD COLUMN IF NOT EXISTS ultimo_reenvio_en  timestamptz;

-- Un registro por intento de envío de correo (R7). Nunca guarda el enlace de acceso.
-- Se purga a los 90 días (lo hace la API al registrar cada envío).
CREATE TABLE IF NOT EXISTS correo_envio (
  id            bigserial PRIMARY KEY,
  tipo          text NOT NULL CHECK (tipo IN ('bienvenida','restablecer')),
  destinatario  text NOT NULL,
  estado        text NOT NULL CHECK (estado IN ('enviado','fallido')),
  motivo        text,
  intentos      int NOT NULL DEFAULT 1,
  disparado_por text NOT NULL,
  fecha         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS correo_envio_destinatario ON correo_envio (destinatario, fecha DESC);
