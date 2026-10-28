-- Planta de cada checada (Matriz / Conversión), para tener dos checadores.
-- Ejecutar UNA VEZ en Supabase Studio (SQL Editor).

alter table checadas add column if not exists planta text;

-- Todo lo que ya existe viene del checador de Matriz
update checadas set planta = 'Matriz' where planta is null;

create index if not exists ix_checadas_planta on checadas (planta, fecha_hora desc);

-- Que la API vea la columna nueva de inmediato
notify pgrst, 'reload schema';
