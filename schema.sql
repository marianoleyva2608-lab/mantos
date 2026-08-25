-- ============================================================
-- Esquema Postgres para la app "mantos" (Mantenimiento AD-PACK)
-- Ejecutar una sola vez en el SQL Editor de Supabase Studio.
-- Usa CREATE TABLE IF NOT EXISTS: es seguro volver a correrlo.
-- ============================================================

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    machine_id TEXT,
    fecha TEXT,
    data TEXT
);

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS respuestas_problemas (
    id SERIAL PRIMARY KEY,
    folio TEXT, fecha TEXT, equipo TEXT, seccion TEXT,
    descripcion_falla TEXT, hora_inicio TEXT,
    mttr_estimado TEXT, tiempo_real TEXT,
    areas_notificadas TEXT, acciones_tomadas TEXT,
    causa_raiz TEXT, tiempo_total_paro TEXT, elaboro TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS work_orders (
    id SERIAL PRIMARY KEY,
    numero TEXT NOT NULL, solicitante TEXT, fecha TEXT, equipo TEXT,
    planta TEXT, tipo TEXT, estatus TEXT, hora_inicio TEXT, hora_termino TEXT,
    tiempo_paro TEXT, descripcion_falla TEXT, actividad_realizada TEXT,
    refaccion TEXT, observaciones TEXT, firma_solicitante TEXT,
    firma_recibe TEXT, firma_liberacion TEXT, fotos TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
);

CREATE TABLE IF NOT EXISTS refacciones (
    id SERIAL PRIMARY KEY,
    nombre TEXT, descripcion TEXT, marca TEXT, modelo TEXT,
    categoria TEXT, criticidad TEXT DEFAULT 'MEDIA', seccion TEXT,
    cant_min INTEGER DEFAULT 1, stock_actual INTEGER DEFAULT 0,
    tiempo_entrega TEXT, proveedor TEXT, ubicacion TEXT,
    costo REAL DEFAULT 0, notas TEXT, foto_b64 TEXT,
    imagen_url TEXT DEFAULT '',
    numero_parte TEXT DEFAULT '',
    estante_nombre TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    pin_hash TEXT NOT NULL,
    rol TEXT DEFAULT 'usuario',
    permisos TEXT DEFAULT '',
    created_at TEXT DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
);

CREATE TABLE IF NOT EXISTS proveedores_extra (
    codigo TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    created_at TEXT DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
);

CREATE TABLE IF NOT EXISTS estantes (
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    created_at TEXT DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
);
INSERT INTO estantes (nombre) VALUES ('Almacén Estante 2') ON CONFLICT (nombre) DO NOTHING;
INSERT INTO estantes (nombre) VALUES ('Estante de herramientas') ON CONFLICT (nombre) DO NOTHING;

CREATE TABLE IF NOT EXISTS requisiciones (
    id TEXT PRIMARY KEY,
    folio INTEGER,
    fecha TEXT,
    solicitante TEXT,
    planta TEXT,
    departamento TEXT,
    tipo TEXT,
    data TEXT,
    created_at TEXT DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
);

-- Usuario administrador por defecto (mismo PIN que ya usan: 260881)
INSERT INTO users (nombre, email, pin_hash, rol, permisos)
VALUES (
    'Mariano Leyva',
    'marianoleyva2608@gmail.com',
    encode(sha256('260881'::bytea), 'hex'),
    'admin',
    'all'
)
ON CONFLICT (email) DO UPDATE SET rol = 'admin', permisos = 'all';
