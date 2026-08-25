"""
Migracion UNICA de datos: copia lo que hay en el SQLite local
(DATA_DIR/reports.db, el que uso la app antes de este cambio) hacia
Supabase, usando la API REST (PostgREST) a traves de Kong -- la unica
ruta de red que el contenedor 'adpack' alcanza (Postgres directo no es
alcanzable desde aqui).

Como correrlo (una sola vez, desde la consola del servicio adpack en
Easypanel, con SUPABASE_SERVICE_KEY ya configurada):

    python migrate_to_postgres.py

Es seguro volver a correrlo: usa upsert (on_conflict + merge-duplicates)
en vez de insertar a ciegas, asi que no duplica filas si se ejecuta mas
de una vez.
"""
import os
import sqlite3
import requests

DATA_DIR = os.environ.get('DATA_DIR', '/app/data')
SQLITE_PATH = os.path.join(DATA_DIR, 'reports.db')

SB_URL = os.environ.get('SUPABASE_INTERNAL_URL', 'http://manto_supabase_kong:8000').rstrip('/')
SB_KEY = os.environ.get('SUPABASE_SERVICE_KEY', '')
BASE = SB_URL + '/rest/v1'
HEADERS = {
    'apikey': SB_KEY,
    'Authorization': f'Bearer {SB_KEY}',
    'Content-Type': 'application/json',
    'Prefer': 'resolution=merge-duplicates,return=minimal',
}


def get_sqlite():
    con = sqlite3.connect(SQLITE_PATH)
    con.row_factory = sqlite3.Row
    return con


def table_exists_sqlite(sq, name):
    row = sq.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


def copy_table(sq, table, cols, conflict_col, batch_size=200):
    if not table_exists_sqlite(sq, table):
        print(f'  [{table}] no existe en el SQLite viejo, se omite')
        return
    rows = sq.execute(f"SELECT {','.join(cols)} FROM {table}").fetchall()
    if not rows:
        print(f'  [{table}] 0 filas, nada que copiar')
        return
    total = 0
    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        payload = [{c: r[c] for c in cols} for r in chunk]
        r = requests.post(
            f'{BASE}/{table}',
            headers=HEADERS,
            params={'on_conflict': conflict_col},
            json=payload,
            timeout=30,
        )
        if r.status_code >= 300:
            print(f'  [{table}] ERROR en lote {i}: {r.status_code} {r.text[:300]}')
            continue
        total += len(chunk)
    print(f'  [{table}] {total}/{len(rows)} filas copiadas')


def main():
    if not SB_KEY:
        print('Falta SUPABASE_SERVICE_KEY en el entorno. Configúrala antes de correr esto.')
        return
    if not os.path.exists(SQLITE_PATH):
        print(f'No se encontro el SQLite viejo en {SQLITE_PATH}. Nada que migrar.')
        return

    print(f'Leyendo datos existentes de: {SQLITE_PATH}')
    print(f'Escribiendo via API REST en: {SB_URL}')
    sq = get_sqlite()

    copy_table(sq, 'reports', ['id', 'machine_id', 'fecha', 'data'], 'id')
    copy_table(sq, 'app_meta', ['key', 'value'], 'key')
    copy_table(sq, 'respuestas_problemas', [
        'id', 'folio', 'fecha', 'equipo', 'seccion', 'descripcion_falla', 'hora_inicio',
        'mttr_estimado', 'tiempo_real', 'areas_notificadas', 'acciones_tomadas',
        'causa_raiz', 'tiempo_total_paro', 'elaboro'
    ], 'id')
    copy_table(sq, 'work_orders', [
        'id', 'numero', 'solicitante', 'fecha', 'equipo', 'planta', 'tipo', 'estatus',
        'hora_inicio', 'hora_termino', 'tiempo_paro', 'descripcion_falla',
        'actividad_realizada', 'refaccion', 'observaciones', 'firma_solicitante',
        'firma_recibe', 'firma_liberacion', 'fotos'
    ], 'id')
    copy_table(sq, 'refacciones', [
        'id', 'nombre', 'descripcion', 'marca', 'modelo', 'categoria', 'criticidad',
        'seccion', 'cant_min', 'stock_actual', 'tiempo_entrega', 'proveedor', 'ubicacion',
        'costo', 'notas', 'foto_b64', 'imagen_url', 'numero_parte', 'estante_nombre'
    ], 'id')
    copy_table(sq, 'users', ['nombre', 'email', 'pin_hash', 'rol', 'permisos'], 'email')
    copy_table(sq, 'proveedores_extra', ['codigo', 'nombre'], 'codigo')
    copy_table(sq, 'estantes', ['nombre'], 'nombre')
    copy_table(sq, 'requisiciones', [
        'id', 'folio', 'fecha', 'solicitante', 'planta', 'departamento', 'tipo', 'data'
    ], 'id')

    sq.close()
    print('Listo.')


if __name__ == '__main__':
    main()
