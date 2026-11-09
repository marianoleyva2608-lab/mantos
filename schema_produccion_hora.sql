-- Modulo "Hora por Hora": produccion capturada por el operador cada hora, por maquina.
-- Ejecutar UNA VEZ en Supabase Studio (SQL Editor). Es seguro volver a correrlo.

create table if not exists produccion_hora (
  id               bigserial primary key,
  fecha            date not null,               -- dia en que inicia el turno
  turno            text not null,               -- '1', '2', '3'
  maquina_id       text not null,               -- TF01, SR01, ...
  maquina_nombre   text,
  hora             text not null,               -- '07:00-08:00'
  numero_parte     text default '',
  meta             integer default 0,
  real             integer default 0,
  scrap            integer default 0,
  paro_min         integer default 0,
  causa            text default '',
  comentario       text default '',
  operador_email   text,
  operador_nombre  text,
  actualizado      timestamptz default now(),
  unique (fecha, turno, maquina_id, hora)
);

create index if not exists ix_produccion_hora_fecha on produccion_hora (fecha desc, maquina_id);

-- Campos del Tablero Hora por Hora (estacion + descripcion + operador de linea)
alter table produccion_hora add column if not exists operador_linea text default '';
alter table produccion_hora add column if not exists meta_h numeric default 0;

notify pgrst, 'reload schema';
