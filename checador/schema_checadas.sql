-- Tabla para las checadas del checador Hikvision.
-- Ejecutar UNA VEZ en Supabase Studio (SQL Editor) antes de usar el panel.

create table if not exists checadas (
  id          bigserial primary key,
  fecha_hora  timestamptz,
  empleado_no text,
  nombre      text,
  tipo        text,
  metodo      text,
  serial_no   bigint,
  raw         jsonb,
  recibido_en timestamptz default now(),
  unique (empleado_no, fecha_hora, serial_no)
);

create index if not exists ix_checadas_fecha on checadas (fecha_hora desc);
