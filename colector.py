"""
Colector de trazabilidad  (worker independiente del sistema AD-PACK)
-------------------------------------------------------------------
Escucha el/los Dingtian por MQTT, cuenta ciclos de produccion y detecta
paros, y lo escribe en Supabase self-hosted a traves de la API REST (Kong),
igual que hace app.py con su clase SB. NO usa conexion Postgres directa.

Variables de entorno:
  MQTT_HOST              broker            (ej. 2.24.126.87  o  el nombre del
                                            servicio mosquitto si esta en la
                                            misma red de Dokploy)
  MQTT_PORT             1883
  MQTT_USER            colector
  MQTT_PASS            (contrasena del usuario colector)
  SUPABASE_INTERNAL_URL http://manto_supabase_kong:8000   (mismo valor que app.py)
  SUPABASE_SERVICE_KEY  (mismo service key que app.py)
"""

import os
import time
import threading
from datetime import datetime, timezone

import requests
import paho.mqtt.client as mqtt

MQTT_HOST = os.environ.get("MQTT_HOST", "2.24.126.87")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ["MQTT_USER"]
MQTT_PASS = os.environ["MQTT_PASS"]

SB_URL = os.environ.get("SUPABASE_INTERNAL_URL", "http://manto_supabase_kong:8000").rstrip("/")
SB_KEY = os.environ["SUPABASE_SERVICE_KEY"]

DEBOUNCE_MS = 120          # ignora rebotes del contacto de ciclo

# ------------------------------------------------------------------
# Cliente REST minimo (mismo patron que la clase SB de app.py)
# ------------------------------------------------------------------
_H = {
    "apikey": SB_KEY,
    "Authorization": f"Bearer {SB_KEY}",
    "Content-Type": "application/json",
}
_BASE = SB_URL + "/rest/v1"


def sb_select(table, select="*", **params):
    params["select"] = select
    r = requests.get(f"{_BASE}/{table}", headers=_H, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def sb_insert(table, data, return_rows=True):
    h = dict(_H)
    if return_rows:
        h["Prefer"] = "return=representation"
    r = requests.post(f"{_BASE}/{table}", headers=h, json=data, timeout=15)
    r.raise_for_status()
    return r.json() if return_rows and r.text else None


def sb_update(table, data, **filters):
    r = requests.patch(f"{_BASE}/{table}", headers=_H, params=filters, json=data, timeout=15)
    r.raise_for_status()


def sb_rpc(fn, args):
    r = requests.post(f"{_BASE}/rpc/{fn}", headers=_H, json=args, timeout=15)
    r.raise_for_status()


# ------------------------------------------------------------------
# Estado en memoria por maquina
# ------------------------------------------------------------------
maquinas = {}   # sn -> fila de 'maquinas'
estado   = {}   # sn -> {"ultimo_ciclo","marcha","paro_id"}
lock     = threading.Lock()


def cargar_maquinas():
    for row in sb_select("maquinas"):
        maquinas[row["dingtian_sn"]] = row
        estado.setdefault(row["dingtian_sn"],
                          {"ultimo_ciclo": 0.0, "marcha": False, "paro_id": None})
    print(f"Maquinas cargadas: {[m['id'] for m in maquinas.values()]}", flush=True)


def orden_activa(maquina_id):
    rows = sb_select("ordenes", select="id",
                     maquina=f"eq.{maquina_id}", fin="is.null",
                     order="inicio.desc", limit=1)
    return rows[0]["id"] if rows else None


def registrar_ciclo(m):
    minuto = datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat()
    sb_rpc("bump_produccion", {"p_maquina": m["id"], "p_minuto": minuto})
    print(f"{datetime.now():%H:%M:%S}  {m['id']}  ciclo", flush=True)


def abrir_paro(m, st, causa):
    if st["paro_id"]:
        return
    oid = orden_activa(m["id"])
    row = sb_insert("paros", {
        "maquina": m["id"],
        "inicio": datetime.now(timezone.utc).isoformat(),
        "causa": causa,
        "orden_id": oid,
    })
    st["paro_id"] = row[0]["id"]
    print(f"{datetime.now():%H:%M:%S}  {m['id']}  INICIO PARO ({causa})", flush=True)


def cerrar_paro(m, st):
    if not st["paro_id"]:
        return
    sb_update("paros", {"fin": datetime.now(timezone.utc).isoformat()},
              id=f"eq.{st['paro_id']}")
    print(f"{datetime.now():%H:%M:%S}  {m['id']}  FIN PARO", flush=True)
    st["paro_id"] = None


def registrar_equipo(sn, val):
    try:
        sb_insert("equipo_estado", {"dingtian_sn": sn, "estado": val}, return_rows=False)
    except Exception as e:
        print(f"[equipo_estado] {e}", flush=True)


# ------------------------------------------------------------------
# MQTT
# ------------------------------------------------------------------
def sn_de_topic(topic):
    # dingtian/relay52862/out/i1 -> ("52862", "i1")
    partes = topic.split("/")
    if len(partes) < 4:
        return None, None
    return partes[1].replace("relay", ""), partes[-1]


def on_connect(cli, *_):
    cli.subscribe("dingtian/+/out/#")
    print("MQTT conectado, suscrito a dingtian/+/out/#", flush=True)


def on_message(cli, _u, msg):
    sn, hoja = sn_de_topic(msg.topic)
    if sn not in maquinas:
        return
    m  = maquinas[sn]
    st = estado[sn]
    payload = msg.payload.decode(errors="ignore").strip()
    activo  = payload.upper() == str(m["estado_activo"]).upper()

    with lock:
        try:
            if hoja == "lwt_availability":
                registrar_equipo(sn, "online" if payload == "online" else "offline")

            elif hoja == f"i{m['entrada_ciclo']}":
                if activo:
                    ahora = time.time()
                    if (ahora - st["ultimo_ciclo"]) * 1000 < DEBOUNCE_MS:
                        return
                    st["ultimo_ciclo"] = ahora
                    registrar_ciclo(m)
                    if st["paro_id"]:
                        cerrar_paro(m, st)

            elif hoja == f"i{m['entrada_marcha']}":
                if activo != st["marcha"]:
                    st["marcha"] = activo
                    if not activo:
                        abrir_paro(m, st, "sin_marcha")
                    else:
                        cerrar_paro(m, st)
        except Exception as e:
            print(f"[on_message] {msg.topic} -> {e}", flush=True)


def vigilar_gaps():
    while True:
        time.sleep(5)
        ahora = time.time()
        with lock:
            for sn, st in estado.items():
                m = maquinas[sn]
                if (st["marcha"] and not st["paro_id"] and st["ultimo_ciclo"]
                        and ahora - st["ultimo_ciclo"] > m["paro_gap_seg"]):
                    try:
                        abrir_paro(m, st, "gap_ciclos")
                    except Exception as e:
                        print(f"[gap] {e}", flush=True)


def main():
    cargar_maquinas()
    cli = mqtt.Client()
    cli.username_pw_set(MQTT_USER, MQTT_PASS)
    cli.on_connect = on_connect
    cli.on_message = on_message
    cli.reconnect_delay_set(min_delay=1, max_delay=30)
    cli.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    threading.Thread(target=vigilar_gaps, daemon=True).start()
    cli.loop_forever()


if __name__ == "__main__":
    main()
