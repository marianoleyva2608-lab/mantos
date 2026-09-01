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

-- ============================================================
--  TRAZABILIDAD DE PRODUCCION (Dingtian por MQTT -> colector)
-- ============================================================

CREATE TABLE IF NOT EXISTS maquinas (
    id             TEXT PRIMARY KEY,           -- 'TF-01'
    nombre         TEXT,
    dingtian_sn    TEXT UNIQUE,                -- '52862'
    entrada_ciclo  INT  NOT NULL DEFAULT 1,    -- input con el pulso de ciclo
    entrada_marcha INT  NOT NULL DEFAULT 2,    -- input con marcha / automatico
    estado_activo  TEXT NOT NULL DEFAULT 'ON', -- payload que cuenta como "activo"
    paro_gap_seg   INT  NOT NULL DEFAULT 25    -- sin ciclos con marcha por > esto = paro
);

CREATE TABLE IF NOT EXISTS ordenes (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    maquina       TEXT NOT NULL REFERENCES maquinas(id),
    orden         TEXT NOT NULL,
    lote_material TEXT,
    molde         TEXT,
    operador      TEXT,
    turno         INT,
    inicio        TIMESTAMPTZ NOT NULL DEFAULT now(),
    fin           TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_ordenes_maq ON ordenes (maquina, inicio DESC);

CREATE TABLE IF NOT EXISTS produccion (
    maquina TEXT NOT NULL REFERENCES maquinas(id),
    minuto  TIMESTAMPTZ NOT NULL,
    piezas  INT NOT NULL DEFAULT 0,
    PRIMARY KEY (maquina, minuto)
);

-- 1 fila por pieza, con hora exacta (segundo)
CREATE TABLE IF NOT EXISTS pulsos (
    id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    maquina  TEXT NOT NULL REFERENCES maquinas(id),
    ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
    orden_id BIGINT REFERENCES ordenes(id)
);
CREATE INDEX IF NOT EXISTS ix_pulsos_maq_ts ON pulsos (maquina, ts DESC);

-- 1 fila por pieza NG (rechazo / scrap). La captura el operador con el
-- boton "+1 NG" del dashboard; no viene del sensor.
CREATE TABLE IF NOT EXISTS piezas_ng (
    id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    maquina  TEXT NOT NULL REFERENCES maquinas(id),
    ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
    orden_id BIGINT REFERENCES ordenes(id)
);
CREATE INDEX IF NOT EXISTS ix_ng_maq_ts ON piezas_ng (maquina, ts DESC);

CREATE TABLE IF NOT EXISTS paros (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    maquina      TEXT NOT NULL REFERENCES maquinas(id),
    inicio       TIMESTAMPTZ NOT NULL,
    fin          TIMESTAMPTZ,
    duracion_seg INT GENERATED ALWAYS AS
          (CASE WHEN fin IS NOT NULL
                THEN EXTRACT(EPOCH FROM (fin - inicio))::INT END) STORED,
    causa        TEXT NOT NULL DEFAULT 'sin_marcha',  -- sin_marcha | gap_ciclos
    motivo       TEXT,                                -- lo captura el operador
    orden_id     BIGINT REFERENCES ordenes(id)
);
CREATE INDEX IF NOT EXISTS ix_paros_maq ON paros (maquina, inicio DESC);

CREATE TABLE IF NOT EXISTS equipo_estado (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    dingtian_sn TEXT NOT NULL,
    estado      TEXT NOT NULL                         -- online | offline
);

-- Conteo atomico de un ciclo (lo llama el colector: POST /rest/v1/rpc/bump_produccion)
CREATE OR REPLACE FUNCTION bump_produccion(p_maquina TEXT, p_minuto TIMESTAMPTZ)
RETURNS void
LANGUAGE sql
AS $$
    INSERT INTO produccion (maquina, minuto, piezas)
    VALUES (p_maquina, date_trunc('minute', p_minuto), 1)
    ON CONFLICT (maquina, minuto)
    DO UPDATE SET piezas = produccion.piezas + 1;
$$;

GRANT EXECUTE ON FUNCTION bump_produccion(TEXT, TIMESTAMPTZ) TO anon, authenticated, service_role;

-- Vistas para el dashboard
CREATE OR REPLACE VIEW v_produccion_por_orden AS
SELECT o.id AS orden_id, o.maquina, o.orden, o.lote_material, o.molde,
       o.operador, o.turno, o.inicio, o.fin,
       COALESCE(SUM(p.piezas), 0) AS piezas,
       COALESCE((SELECT COUNT(*) FROM piezas_ng n
                  WHERE n.maquina = o.maquina
                    AND n.ts >= o.inicio
                    AND (o.fin IS NULL OR n.ts < o.fin)), 0) AS ng
FROM ordenes o
LEFT JOIN produccion p
       ON p.maquina = o.maquina
      AND p.minuto >= o.inicio
      AND (o.fin IS NULL OR p.minuto < o.fin)
GROUP BY o.id;

CREATE OR REPLACE VIEW v_paros_abiertos AS
SELECT * FROM paros WHERE fin IS NULL;

-- Maquina de ejemplo (ajusta entrada_ciclo / entrada_marcha al cablear)
INSERT INTO maquinas (id, nombre, dingtian_sn, entrada_ciclo, entrada_marcha)
VALUES ('TF-01', 'Termoformadora 1', '52862', 1, 2)
ON CONFLICT (id) DO NOTHING;
