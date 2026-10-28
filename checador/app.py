"""
Panel de Checador - Hikvision DS-K1T343 (sucursal Maravillas)

Recibe las checadas que el checador empuja por HTTP Listening y las guarda
en Supabase a traves de la API REST (PostgREST) via Kong, igual que mantos.
Luego las muestra en un panel con filtros y exportacion a CSV.

Variables de entorno (mismas que mantos):
  SUPABASE_INTERNAL_URL  -> http://manto_supabase_kong:8000  (red interna del proyecto)
  SUPABASE_SERVICE_KEY   -> service key de Supabase
  APP_TITLE              -> opcional
  NAME_MAP               -> opcional "1001=Juan Perez;1002=Maria Lopez"

Antes de usar: crear la tabla 'checadas' en Supabase Studio con schema_checadas.sql

Endpoints:
  POST /checador  -> recibe el evento del checador (HTTP Listening)
  GET  /          -> panel web
  GET  /export    -> CSV de lo filtrado
  GET  /health    -> ping
"""

import os
import io
import csv
import json
from datetime import date
import requests
from flask import Flask, request, render_template, Response

APP_TITLE = os.environ.get("APP_TITLE", "Panel de Checador")
SB_URL = os.environ.get("SUPABASE_INTERNAL_URL", "http://manto_supabase_kong:8000").rstrip("/")
SB_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
TABLE = os.environ.get("TABLE_NAME", "checadas")

NAME_MAP = {}
for pair in os.environ.get("NAME_MAP", "").split(";"):
    if "=" in pair:
        k, v = pair.split("=", 1)
        NAME_MAP[k.strip()] = v.strip()

app = Flask(__name__)
_REST = SB_URL + "/rest/v1"
_H = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}",
      "Content-Type": "application/json"}


# --------------------------- Cliente Supabase ----------------------------
def sb_insert(row):
    """Inserta una checada; ignora duplicados (upsert por la constraint unica)."""
    headers = dict(_H)
    headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
    params = {"on_conflict": "empleado_no,fecha_hora,serial_no"}
    r = requests.post(f"{_REST}/{TABLE}", headers=headers, params=params,
                      json=row, timeout=15)
    r.raise_for_status()


def sb_select(params):
    """params: lista de tuplas (permite repetir llaves, ej. rango de fecha)."""
    r = requests.get(f"{_REST}/{TABLE}", headers=_H, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def sb_count():
    headers = dict(_H)
    headers["Prefer"] = "count=exact"
    r = requests.get(f"{_REST}/{TABLE}", headers=headers,
                     params=[("select", "id"), ("limit", "1")], timeout=15)
    r.raise_for_status()
    rango = r.headers.get("Content-Range", "*/0")  # ej "0-0/1831"
    try:
        return int(rango.split("/")[-1])
    except Exception:
        return 0


# ----------------------- Parseo del evento Hikvision ---------------------
METODO = {75: "Cara", 76: "Huella", 1: "Tarjeta", 8: "Tarjeta",
          38: "Cara", 10: "Huella"}
TIPO = {"checkIn": "Entrada", "checkOut": "Salida",
        "breakOut": "Salida descanso", "breakIn": "Regreso descanso",
        "overtimeIn": "Entrada extra", "overtimeOut": "Salida extra"}


def extraer_evento(payload):
    ace = payload.get("AccessControllerEvent", {})
    if ace.get("majorEventType") != 5:
        return None
    empleado = str(ace.get("employeeNoString") or ace.get("employeeNo") or "").strip()
    nombre = (ace.get("name") or "").strip()
    if not nombre and empleado in NAME_MAP:
        nombre = NAME_MAP[empleado]
    if not empleado and not nombre:
        return None
    sub = ace.get("subEventType")
    estado = ace.get("attendanceStatus") or ""
    return {
        "fecha_hora": payload.get("dateTime") or ace.get("time") or None,
        "empleado_no": empleado,
        "nombre": nombre or "(sin nombre)",
        "tipo": TIPO.get(estado, estado or "s.d."),
        "metodo": METODO.get(sub, f"otro ({sub})" if sub is not None else "s.d."),
        "serial_no": ace.get("serialNo"),
        "raw": payload,
    }


def leer_payload():
    if "event_log" in request.form:
        try:
            return json.loads(request.form["event_log"])
        except Exception:
            pass
    if "event_log" in request.files:
        try:
            return json.loads(request.files["event_log"].read().decode("utf-8", "ignore"))
        except Exception:
            pass
    data = (request.get_data(as_text=True) or "").strip()
    if data.startswith("{"):
        try:
            return json.loads(data)
        except Exception:
            pass
    return None


# ------------------------------- Endpoints -------------------------------
@app.route("/checador", methods=["POST"])
def recibir():
    payload = leer_payload()
    if not payload:
        return "OK", 200
    ev = extraer_evento(payload)
    if ev is None:
        return "OK", 200
    try:
        sb_insert(ev)
    except Exception as e:
        app.logger.error("Error guardando checada: %s", e)
    # Siempre 200: si respondemos error, el aparato reintenta y traba la cola
    return "OK", 200


def _params_filtro(args, base):
    params = list(base)
    desde, hasta = args.get("desde", "").strip(), args.get("hasta", "").strip()
    nombre = args.get("nombre", "").strip()
    if desde:
        params.append(("fecha_hora", f"gte.{desde}T00:00:00"))
    if hasta:
        params.append(("fecha_hora", f"lte.{hasta}T23:59:59"))
    if nombre:
        params.append(("or", f"(nombre.ilike.*{nombre}*,empleado_no.ilike.*{nombre}*)"))
    return params


@app.route("/")
def panel():
    base = [("select", "*"), ("order", "fecha_hora.desc"), ("limit", "1000")]
    try:
        filas = sb_select(_params_filtro(request.args, base))
        total = sb_count()
        error = None
    except Exception as e:
        filas, total, error = [], 0, str(e)
    return render_template("panel.html", title=APP_TITLE, filas=filas,
                           total=total, mostrados=len(filas),
                           hoy=date.today().isoformat(), f=request.args, error=error)


@app.route("/export")
def export():
    base = [("select", "fecha_hora,empleado_no,nombre,tipo,metodo"),
            ("order", "fecha_hora.desc")]
    filas = sb_select(_params_filtro(request.args, base))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Fecha y hora", "No. empleado", "Nombre", "Tipo", "Metodo"])
    for r in filas:
        w.writerow([r.get("fecha_hora"), r.get("empleado_no"),
                    r.get("nombre"), r.get("tipo"), r.get("metodo")])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":
                             f"attachment; filename=checadas_{date.today().isoformat()}.csv"})


@app.route("/health")
def health():
    try:
        sb_count()
        return {"status": "ok", "supabase": "ok"}, 200
    except Exception as e:
        return {"status": "ok", "supabase": f"error: {e}"}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
