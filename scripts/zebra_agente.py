#!/usr/bin/env python3
"""Agente de impresion Zebra para la Raspberry Pi / Orange Pi.

Consulta la cola de mantos cada 2 s. Hay dos tipos de trabajo:
- ZPL ya armado: se manda directo a la Zebra por USB.
- ruta + cuerpo (pestañas Trays, Conversión, H60, Recibo, Cliente): se reenvía
  al servidor local de la Pi (zebra-print.service, puerto 5000), que arma el
  ZPL como siempre. Ese servicio debe seguir corriendo.
Solo necesita salida a internet: no hace falta abrir puertos ni saber la IP
de la Pi, asi que se puede imprimir desde cualquier celular o PC.

Instalacion en la Pi:
  sudo cp zebra_agente.py /opt/zebra_agente.py
  sudo nano /etc/systemd/system/zebra-agente.service   (contenido abajo)
  sudo systemctl daemon-reload
  sudo systemctl enable --now zebra-agente
  journalctl -u zebra-agente -f        # para ver que imprime

  [Unit]
  Description=Agente cola Zebra (mantos)
  After=network-online.target
  Wants=network-online.target

  [Service]
  Environment=MANTOS_URL=https://TU-DOMINIO-DE-MANTOS
  Environment=ZEBRA_TOKEN=
  Environment=ZEBRA_DISPOSITIVO=/dev/usb/lp0
  Environment=PI_LOCAL_URL=http://127.0.0.1:5000
  ExecStart=/usr/bin/python3 /opt/zebra_agente.py
  Restart=always
  RestartSec=5

  [Install]
  WantedBy=multi-user.target
"""
import json
import ssl
import os
import time
import urllib.request
import urllib.error

URL = os.environ.get('MANTOS_URL', '').rstrip('/')
TOKEN = os.environ.get('ZEBRA_TOKEN', '')
DISPOSITIVO = os.environ.get('ZEBRA_DISPOSITIVO', '/dev/usb/lp0')
PI_LOCAL = os.environ.get('PI_LOCAL_URL', 'http://127.0.0.1:5000').rstrip('/')
INTERVALO = float(os.environ.get('ZEBRA_INTERVALO', '2'))


def _req(metodo, ruta, datos=None):
    cuerpo = json.dumps(datos).encode() if datos is not None else None
    r = urllib.request.Request(URL + ruta, data=cuerpo, method=metodo)
    r.add_header('Content-Type', 'application/json')
    if TOKEN:
        r.add_header('X-Zebra-Token', TOKEN)
    with urllib.request.urlopen(r, timeout=15) as resp:
        texto = resp.read().decode() if resp.status != 204 else ''
        return resp.status, (json.loads(texto) if texto else None)


def reenviar_local(ruta, cuerpo):
    """Manda el trabajo al servidor Flask de la Pi y regresa (ok, respuesta, error)."""
    r = urllib.request.Request(PI_LOCAL + ruta, data=json.dumps(cuerpo).encode(), method='POST')
    r.add_header('Content-Type', 'application/json')
    ctx = ssl._create_unverified_context()  # el certificado local es autofirmado
    try:
        with urllib.request.urlopen(r, timeout=60, context=ctx) as resp:
            data = json.loads(resp.read().decode() or '{}')
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read().decode() or '{}')
        except ValueError:
            data = {}
        return False, data, data.get('error') or ('HTTP %s en %s' % (e.code, ruta))
    return bool(data.get('ok')), data, data.get('error', '')


def imprimir(zpl):
    with open(DISPOSITIVO, 'wb') as f:
        f.write(zpl.encode('utf-8'))


def main():
    if not URL:
        raise SystemExit('Falta MANTOS_URL')
    print('Agente Zebra ->', URL, '->', DISPOSITIVO, flush=True)
    while True:
        try:
            estado, trabajo = _req('GET', '/api/zebra/siguiente')
            if estado == 200 and trabajo:
                tid = trabajo['id']
                if trabajo.get('ruta'):
                    try:
                        ok, resp, err = reenviar_local(trabajo['ruta'], trabajo.get('cuerpo') or {})
                    except (urllib.error.URLError, OSError, ValueError) as e:
                        ok, resp, err = False, None, 'Servidor local de la Pi: %s' % e
                    _req('POST', '/api/zebra/trabajos/%s/resultado' % tid,
                         {'ok': ok, 'respuesta': resp, 'error': err})
                    print('Trabajo', tid, trabajo['ruta'], 'OK' if ok else 'ERROR ' + str(err), flush=True)
                else:
                    try:
                        imprimir(trabajo['zpl'])
                        _req('POST', '/api/zebra/trabajos/%s/resultado' % tid, {'ok': True})
                        print('Impreso trabajo', tid, flush=True)
                    except OSError as e:
                        _req('POST', '/api/zebra/trabajos/%s/resultado' % tid,
                             {'ok': False, 'error': 'Impresora: %s' % e})
                        print('Error impresora:', e, flush=True)
                continue  # revisa de inmediato si hay mas
        except (urllib.error.URLError, OSError, ValueError) as e:
            print('Sin conexion con mantos:', e, flush=True)
            time.sleep(10)
        time.sleep(INTERVALO)


if __name__ == '__main__':
    main()
