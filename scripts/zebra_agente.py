#!/usr/bin/env python3
"""Agente de impresion Zebra para la Raspberry Pi / Orange Pi.

Consulta la cola de mantos cada 2 s y manda el ZPL a la Zebra por USB.
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
  ExecStart=/usr/bin/python3 /opt/zebra_agente.py
  Restart=always
  RestartSec=5

  [Install]
  WantedBy=multi-user.target
"""
import json
import os
import time
import urllib.request
import urllib.error

URL = os.environ.get('MANTOS_URL', '').rstrip('/')
TOKEN = os.environ.get('ZEBRA_TOKEN', '')
DISPOSITIVO = os.environ.get('ZEBRA_DISPOSITIVO', '/dev/usb/lp0')
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
                try:
                    imprimir(trabajo['zpl'])
                    _req('POST', '/api/zebra/trabajos/%s/resultado' % trabajo['id'], {'ok': True})
                    print('Impreso trabajo', trabajo['id'], flush=True)
                except OSError as e:
                    _req('POST', '/api/zebra/trabajos/%s/resultado' % trabajo['id'],
                         {'ok': False, 'error': 'Impresora: %s' % e})
                    print('Error impresora:', e, flush=True)
                continue  # revisa de inmediato si hay mas
        except (urllib.error.URLError, OSError, ValueError) as e:
            print('Sin conexion con mantos:', e, flush=True)
            time.sleep(10)
        time.sleep(INTERVALO)


if __name__ == '__main__':
    main()
