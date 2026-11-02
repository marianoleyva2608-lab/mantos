-- Inventario de Materia Prima (almacen por planta: Termoformado, Conversión, Tepezalá).
-- Ejecutar UNA VEZ en Supabase Studio (SQL Editor). Es seguro volver a correrlo.
--
-- La existencia NO se guarda: se calcula sumando entradas y restando salidas
-- (no canceladas) de inv_movimientos, por planta y por lote.

create table if not exists inv_articulos (
  id           bigserial primary key,
  codigo       text unique,
  descripcion  text not null,
  tipo         text default '',              -- Rollo / Lámina, Resina, Pigmento, Tinta, Adhesivo, Empaque, Otro
  unidad       text default 'kg',            -- kg, rollo, pza, lt, caja...
  minimos      jsonb default '{}'::jsonb,    -- {"Termoformado": 500, "Conversión": 200}
  proveedor    text default '',
  notas        text default '',
  activo       boolean default true,
  creado       timestamptz default now(),
  actualizado  timestamptz default now()
);

create table if not exists inv_movimientos (
  id              bigserial primary key,
  articulo_id     bigint not null references inv_articulos(id),
  planta          text not null,
  tipo            text not null check (tipo in ('entrada', 'salida')),
  cantidad        numeric not null check (cantidad > 0),
  lote            text default '',           -- lote interno MP-AAMMDD-NNN (lo asigna el sistema en entradas)
  lote_proveedor  text default '',
  proveedor       text default '',           -- entradas
  referencia      text default '',           -- factura / remisión (entrada) u orden de producción (salida)
  destino         text default '',           -- máquina / área (salidas)
  notas           text default '',
  fecha           timestamptz default now(),
  usuario_email   text,
  usuario_nombre  text,
  cancelado       jsonb,                     -- {fecha, email, nombre, motivo}; null = vigente
  creado          timestamptz default now()
);

create index if not exists ix_inv_mov_planta on inv_movimientos (planta, fecha desc);
create index if not exists ix_inv_mov_articulo on inv_movimientos (articulo_id, planta, fecha desc);

-- Por si la tabla ya existia sin la columna de lote del proveedor:
alter table inv_movimientos add column if not exists lote_proveedor text default '';

-- Que la API vea las tablas nuevas de inmediato
notify pgrst, 'reload schema';
