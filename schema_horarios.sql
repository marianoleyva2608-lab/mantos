-- Horarios por empleado (para el panel de Asistencia).
-- Ejecutar UNA VEZ en Supabase Studio (SQL Editor).
-- Si ya creaste la tabla antes, corre igual este bloque: agrega las columnas de break.

create table if not exists horarios (
  empleado_no      text primary key,
  nombre           text,
  hora_entrada     text,               -- 'HH:MM' (ej. '08:00')
  hora_break_ini   text,               -- salida a descanso (ej. '13:00')
  hora_break_fin   text,               -- regreso de descanso (ej. '13:30')
  hora_salida      text,               -- 'HH:MM' (ej. '18:00')
  tolerancia_min   int default 10,     -- minutos de gracia antes de marcar retardo
  dias             text default 'L,M,X,J,V,S',
  activo           boolean default true,
  actualizado      timestamptz default now()
);

-- Por si la tabla ya existia sin las columnas de break:
alter table horarios add column if not exists hora_break_ini text;
alter table horarios add column if not exists hora_break_fin text;
