-- Modulo "Informacion QR": cada fila es un QR leido con el motivo de la persona.
-- Ejecutar UNA VEZ en Supabase Studio (SQL Editor). Es seguro volver a correrlo.

create table if not exists qr_registros (
  id              bigserial primary key,
  contenido       text not null,                 -- texto tal cual venia en el QR
  datos           jsonb default '[]'::jsonb,     -- campos reconocidos: [{"k": "Nombre", "v": "Juan"}]
  motivo          text not null,
  fecha           timestamptz default now(),
  usuario_email   text,
  usuario_nombre  text
);

create index if not exists ix_qr_registros_fecha on qr_registros (fecha desc);

-- Que la API vea la tabla nueva de inmediato
notify pgrst, 'reload schema';
