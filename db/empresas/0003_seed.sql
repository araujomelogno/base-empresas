-- 0003_seed.sql — Configuración inicial (versión 1) y catálogo base de naturalezas jurídicas.
-- Las marcas de exclusión definitivas salen de la hoja "excluidos" del Excel de referencia
-- (ver fase0/cargar_excluidos.py); acá ninguna naturaleza queda excluida por defecto.
SET search_path TO empresas, public;

INSERT INTO naturaleza_juridica (codigo, nombre) VALUES
  ('UNI',    'Empresa unipersonal'),
  ('SA',     'Sociedad anónima'),
  ('SRL',    'Sociedad de responsabilidad limitada'),
  ('SAS',    'Sociedad por acciones simplificada'),
  ('SH',     'Sociedad de hecho'),
  ('SC',     'Sociedad colectiva'),
  ('SCS',    'Sociedad en comandita'),
  ('COOP',   'Cooperativa'),
  ('AC',     'Asociación civil'),
  ('FUND',   'Fundación'),
  ('SUCEXT', 'Sucursal de sociedad extranjera'),
  ('GIE',    'Grupo de interés económico'),
  ('CONS',   'Consorcio'),
  ('FID',    'Fideicomiso'),
  ('SUCES',  'Sucesión'),
  ('PPNE',   'Persona pública no estatal'),
  ('PUB',    'Organismo público o ente estatal'),
  ('GD',     'Gobierno departamental'),
  ('OTRO',   'Otra');

INSERT INTO config_version (parametros, autor, comentario) VALUES (
'{
  "umbral_intermediario": 5,
  "meses_enfriamiento": 6,
  "reglas_disponibilidad": {
    "enfriamiento": true,
    "muestra_activa": true,
    "sin_telefono_discable": true
  },
  "naturalezas_excluidas": [],
  "reglas_fusion": ["rut", "telefono", "razon_social", "dominio"],
  "confianza_fuentes": {"manual": 90, "sala": 80, "sav": 80, "fusion": 60, "carga": 50, "sistema": 40},
  "destinos_internos": ["^\\d{1,5}$", "^\\*", "^#"],
  "prefijos_salida": [],
  "franjas": [
    {"nombre": "mañana", "dias": [1,2,3,4,5], "desde": "10:00", "hasta": "16:30"},
    {"nombre": "tarde", "dias": [1,2,3,4,5], "desde": "16:30", "hasta": "23:59"},
    {"nombre": "fin de semana", "dias": [6,7], "desde": "00:00", "hasta": "23:59"}
  ],
  "contacto_efectivo": ["completa", "parcial", "rechazo"],
  "csv_ucontact": {
    "separador": ";",
    "columnas": [
      {"columna": "id_item", "campo": "id_item"},
      {"columna": "telefono", "campo": "tel_nacional"},
      {"columna": "rut", "campo": "rut"},
      {"columna": "razon_social", "campo": "razon_social"},
      {"columna": "contacto", "campo": "contacto"},
      {"columna": "link", "campo": "link"}
    ]
  }
}'::jsonb, 'sistema', 'Configuración inicial');
