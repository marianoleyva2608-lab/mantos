import os, io, base64, sqlite3, json, hashlib
from flask import Flask, request, send_file, jsonify

app = Flask(__name__)
DATA_DIR = os.environ.get('DATA_DIR', '/app/data')
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, 'reports.db')

def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_db()
    con.execute('CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY, machine_id TEXT, fecha TEXT, data TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS work_orders (id INTEGER PRIMARY KEY AUTOINCREMENT, numero TEXT NOT NULL, solicitante TEXT, fecha TEXT, equipo TEXT, planta TEXT, tipo TEXT, estatus TEXT, hora_inicio TEXT, hora_termino TEXT, tiempo_paro TEXT, descripcion_falla TEXT, actividad_realizada TEXT, refaccion TEXT, observaciones TEXT, firma_solicitante TEXT, firma_recibe TEXT, firma_liberacion TEXT, fotos TEXT, created_at TEXT DEFAULT (datetime(\'now\')))')
    # Migrate: add fotos column if missing
    try:
        con.execute('ALTER TABLE work_orders ADD COLUMN fotos TEXT DEFAULT "[]"')
        con.commit()
    except Exception:
        pass  # column already exists

    con.execute('''CREATE TABLE IF NOT EXISTS refacciones (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   nombre TEXT, descripcion TEXT, marca TEXT, modelo TEXT,
                   categoria TEXT, criticidad TEXT DEFAULT 'MEDIA', seccion TEXT,
                   cant_min INTEGER DEFAULT 1, stock_actual INTEGER DEFAULT 0,
                   tiempo_entrega TEXT, proveedor TEXT, ubicacion TEXT,
                   costo REAL DEFAULT 0, notas TEXT, foto_b64 TEXT,
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    # -- Seed refacciones AD-PACK --
    import base64 as _b64, json as _json
    _seed = _json.loads(_b64.b64decode("W1siQ29udGFjdG9yIEFDIENISU5UIE5YQy0zMiAyMjBWIDUwLzYwSHoiLCAiQ29udGFjdG9yIiwgIkFMVEEiLCAiRWxlY3RyaWNvIC8gQ29udHJvbCIsIDMsIDMsICIx4oCTMiBkw61hcyIsICJFTE1FU0kgLyBDT0lOU0EiLCAiRXN0YW50ZTogQ09OVEFDVE9SRVMiLCA0ODAuMCwgIlN0b2NrIE9LIOKckyIsICJDSElOVCBOWEMtMzIiLCAiOTI2MjEzIl0sIFsiUmVsZXZhZG9yIHTDqXJtaWNvIENISU5UIE5SMi0zRSAyLjjigJM0QSIsICJSZWxldmFkb3IiLCAiQUxUQSIsICJFbGVjdHJpY28gLyBDb250cm9sIiwgMiwgMSwgIjHigJMyIGTDrWFzIiwgIkVMTUVTSSIsICJFc3RhbnRlOiBDT05UQUNUT1JFUyIsIDMyMC4wLCAiIiwgIkNISU5UIE5SMi0zRSIsICIyMDkxMDYiXSwgWyJTU1IgRm90ZWsgU1NSLTI1VkEgMjVBIiwgIlNTUiIsICJBTFRBIiwgIkVsZWN0cmljbyAvIENvbnRyb2wiLCAyLCAxLCAiM+KAkzUgZMOtYXMiLCAiQ09JTlNBIiwgIkVzdGFudGU6IEhFUlJBTUlFTlRBIiwgODUwLjAsICIiLCAiRm90ZWsgU1NSLTI1VkEiLCAiIl0sIFsiU1NSIEpNUCA4MEEgNDgwVkFDIiwgIlNTUiIsICJBTFRBIiwgIkVsZWN0cmljbyAvIENvbnRyb2wiLCAxLCAxLCAiM+KAkzUgZMOtYXMiLCAiSk1QIC8gQ09JTlNBIiwgIkVzdGFudGU6IEhFUlJBTUlFTlRBIiwgMTgwMC4wLCAiRXF1aXBvcyBncmFuZGVzIiwgIkpNUCBKRy0zNEYgRC00ODBBNTBaUy1MIiwgIiJdLCBbIlRpbWVyIEF1dG9uaWNzIEFUOE4gMTAw4oCTMjQwVkFDIiwgIlRpbWVyIiwgIk1FRElBIiwgIkVsZWN0cmljbyAvIENvbnRyb2wiLCAzLCA0LCAiM+KAkzUgZMOtYXMiLCAiQ09JTlNBIC8gQXV0b25pY3MiLCAiRXN0YW50ZTogVElNRVIiLCA2NTAuMCwgIlN0b2NrIGFidW5kYW50ZSDinJMiLCAiQXV0b25pY3MgQVQ4TiIsICIiXSwgWyJDb250cm9sYWRvciB0ZW1wZXJhdHVyYSBBdXRvbmljcyBUQ040Uy0yNFIiLCAiQ29udHJvbCB0ZW1wLiIsICJBTFRBIiwgIkVsZWN0cmljbyAvIENvbnRyb2wiLCAyLCAzLCAiM+KAkzUgZMOtYXMiLCAiQ09JTlNBIC8gQXV0b25pY3MiLCAiRXN0YW50ZTogVElNRVIiLCAxMjAwLjAsICJNdWx0aS1zZW5zb3IsIFJlbGF5K1NTUiIsICJBdXRvbmljcyBUQ040Uy0yNFIiLCAiIl0sIFsiUmVsZXZhZG9yIGVuY2h1ZmFibGUgOC1waW4gMTBBIDI1MFZBQyIsICJSZWxldmFkb3IiLCAiTUVESUEiLCAiRWxlY3RyaWNvIC8gQ29udHJvbCIsIDYsIDYsICIx4oCTMiBkw61hcyIsICJFTE1FU0kgLyBDT0lOU0EiLCAiRXN0YW50ZTogRUxFQ1RSTyBWw4FMVlVMQVMiLCAxODAuMCwgIlZhcmlvcyDinJMiLCAiRmluZGVyIiwgIk9tcm9uIl0sIFsiRnVlbnRlIDI0VkRDIE1vZWxsZXIgZWFzeTQwMC1QT1ciLCAiRnVlbnRlIERDIiwgIkFMVEEiLCAiRWxlY3RyaWNvIC8gQ29udHJvbCIsIDEsIDEsICI14oCTNyBkw61hcyIsICJFTE1FU0kiLCAiRXN0YW50ZTogSEVSUkFNSUVOVEEiLCAyMjAwLjAsICIiLCAiTW9lbGxlciBlYXN5NDAwLVBPVyIsICIiXSwgWyJTd2l0Y2ggZGUgbMOtbWl0ZSAxNUEgMTI14oCTNDgwViIsICJGaW4gZGUgY2FycmVyYSIsICJNRURJQSIsICJFbGVjdHJpY28gLyBDb250cm9sIiwgNCwgMywgIjLigJMzIGTDrWFzIiwgIkpNUCAvIENPSU5TQSIsICJFc3RhbnRlOiBIRVJSQU1JRU5UQSIsIDM4MC4wLCAiMyB1ZHMg4pyTIiwgIkpNUCBNb2RlbG8gMTE2LTIwMyIsICIiXSwgWyJGdXNpYmxlcyBzdXJ0aWRvcyAoY2FqYSkiLCAiRnVzaWJsZSIsICJBTFRBIiwgIkVsZWN0cmljbyAvIENvbnRyb2wiLCAxLCAxLCAiMSBkw61hIiwgIkVMTUVTSSIsICJFc3RhbnRlOiBIRVJSQU1JRU5UQSIsIDMwMC4wLCAiQ2FqYSDinJMiLCAiSGFueW91bmcgTlVYIiwgInZhcmlvcyJdLCBbIkJsb3F1ZSB0ZXJtaW5hbCA1VCAoSk1QKSIsICJUZXJtaW5hbCIsICJCQUpBIiwgIkVsZWN0cmljbyAvIENvbnRyb2wiLCAxMCwgMTAsICIxIGTDrWEiLCAiSk1QIC8gQ09JTlNBIiwgIkVzdGFudGU6IENPTlRBQ1RPUkVTIiwgMjUuMCwgIiIsICJKTVAgNVQiLCAiIl0sIFsiS2l0IHRlcm1pbmFsZXMgYWlzbGFkYXMgNTUgcHogMTLigJMyMiBBV0ciLCAiVGVybWluYWwiLCAiQkFKQSIsICJFbGVjdHJpY28gLyBDb250cm9sIiwgMiwgMiwgIjEgZMOtYSIsICJUdWsgLyBPZmZpY2UgRGVwb3QiLCAiRXN0YW50ZTogQ09OVEFDVE9SRVMiLCA4NS4wLCAiIiwgIlZvbHRlYyIsICJUdWsiXSwgWyJSZXNpc3RlbmNpYSB0dWJ1bGFyIHRpcG8gVSAjQk4tMSAoaG9ycXVpbGxhKSIsICJSZXNpc3RlbmNpYSIsICJBTFRBIiwgIlJlc2lzdGVuY2lhcyAvIENhbGVmYWNjaW9uIiwgNSwgMjAsICI14oCTMTAgZMOtYXMiLCAiVENSIiwgIkVzdGFudGU6IFJFU0lTVEVOQ0lBUyIsIDM4MC4wLCAiQ2FqYSB+MjAgcHphcyDinJMiLCAiVENSIiwgIlNBTDAwMDAyIl0sIFsiUmVzaXN0ZW5jaWEgcGxhbmEgMjIwLzIzMFZBQyA2NTBXIHRlcm1vY3VwbGEgSyAyNcOXNi41Y20iLCAiUmVzaXN0ZW5jaWEiLCAiQUxUQSIsICJSZXNpc3RlbmNpYXMgLyBDYWxlZmFjY2lvbiIsIDIsIDIsICI14oCTMTAgZMOtYXMiLCAiVENSIiwgIkVzdGFudGU6IFJFU0lTVEVOQ0lBUyIsIDY1MC4wLCAiIiwgIlRDUiBTQUwwMDAwMiIsICIiXSwgWyJSZXNpc3RlbmNpYSBwbGFuYSAyMjAvMjMwVkFDIDYyNVcgdGVybW9wYXIgSyAyNcOXNjVjbSIsICJSZXNpc3RlbmNpYSIsICJBTFRBIiwgIlJlc2lzdGVuY2lhcyAvIENhbGVmYWNjaW9uIiwgMiwgMiwgIjXigJMxMCBkw61hcyIsICJUQ1IiLCAiRXN0YW50ZTogUkVTSVNURU5DSUFTIiwgNjIwLjAsICIiLCAiVENSIFNBTDAwMDAyIE5FR1UiLCAiIl0sIFsiUmVzaXN0ZW5jaWEgcGxhbmEgMjIwLzIzMFZBQyAzMjVXIHRlcm1vY3VwbGEgSyAxMsOXNi41Y20iLCAiUmVzaXN0ZW5jaWEiLCAiQUxUQSIsICJSZXNpc3RlbmNpYXMgLyBDYWxlZmFjY2lvbiIsIDQsIDcsICI14oCTMTAgZMOtYXMiLCAiVENSIiwgIkVzdGFudGU6IFJFU0lTVEVOQ0lBUyIsIDM4MC4wLCAifjcgcHphcyDinJMiLCAiVENSIiwgIiJdLCBbIlJlc2lzdGVuY2lhIHBsYW5hIDIyMC8yMzBWQUMgMzAwVyB0ZXJtb2N1cGxhIEsgMTLDlzYuNWNtIiwgIlJlc2lzdGVuY2lhIiwgIkFMVEEiLCAiUmVzaXN0ZW5jaWFzIC8gQ2FsZWZhY2Npb24iLCAyLCAxLCAiNeKAkzEwIGTDrWFzIiwgIlRDUiIsICJFc3RhbnRlOiBSRVNJU1RFTkNJQVMiLCAzNTAuMCwgIiIsICJUQ1IiLCAiIl0sIFsiVGVybWluYWwgZGUgY2Vyw6FtaWNhIHBhcmEgcmVzaXN0ZW5jaWEiLCAiQ29uc3VtaWJsZSIsICJNRURJQSIsICJSZXNpc3RlbmNpYXMgLyBDYWxlZmFjY2lvbiIsIDEwLCAxMCwgIjPigJM1IGTDrWFzIiwgIlRDUiAvIENPSU5TQSIsICJFc3RhbnRlOiBURVJNLiBDRVLDgU1JQ0EiLCA0NS4wLCAiIiwgIkdlbsOpcmljbyIsICIiXSwgWyJUZXJtb3BhciB0aXBvIEsgZGUgcmVwdWVzdG8iLCAiU2Vuc29yIiwgIkFMVEEiLCAiUmVzaXN0ZW5jaWFzIC8gQ2FsZWZhY2Npb24iLCA0LCAyLCAiM+KAkzUgZMOtYXMiLCAiQ09JTlNBIC8gQXV0b25pY3MiLCAiRXN0YW50ZTogSVRNIFRFTVAuIiwgMjgwLjAsICIiLCAiR2Vuw6lyaWNvIiwgIkF1dG9uaWNzIl0sIFsiVsOhbHZ1bGEgc29sZW5vaWRlIERFIFdJVCAyVy0yNS1OQy1FLVZJNSAxXCIgTkMiLCAiRWxlY3Ryb3bDoWx2dWxhIiwgIkFMVEEiLCAiTmV1bWF0aWNvIC8gSGlkcmF1bGljbyIsIDIsIDIsICIz4oCTNSBkw61hcyIsICJERSBXSVQgLyBDT0lOU0EiLCAiRXN0YW50ZTogRUxFQ1RSTyBWw4FMVlVMQVMiLCA5NTAuMCwgIk5DIOKckyIsICJERSBXSVQgMlctMjUtTkMtRS1WSTUiLCAiIl0sIFsiRWxlY3Ryb3bDoWx2dWxhIG5ldW3DoXRpY2EgNC8yIHbDrWFzIDI0VkRDIiwgIkVsZWN0cm92w6FsdnVsYSIsICJBTFRBIiwgIk5ldW1hdGljbyAvIEhpZHJhdWxpY28iLCAyLCAxLCAiM+KAkzUgZMOtYXMiLCAiU01DIC8gQ09JTlNBIiwgIkVzdGFudGU6IEVMRUNUUk8gVsOBTFZVTEFTIiwgNzgwLjAsICIiLCAiU3BvcnRyb25pYyIsICJTTUMiXSwgWyJNYW7Ds21ldHJvIGdsaWNlcmluYSAw4oCTMTAgYmFyIDEvNFwiIiwgIkluc3RydW1lbnRvIiwgIkJBSkEiLCAiTmV1bWF0aWNvIC8gSGlkcmF1bGljbyIsIDIsIDIsICIy4oCTMyBkw61hcyIsICJDT0lOU0EiLCAiRXN0YW50ZTogTUFOT01FVFJPUyIsIDIyMC4wLCAi4pyTIiwgIldpa2EiLCAiVmFyaW9zIl0sIFsiQ29uZGVuc2Fkb3IgZGUgbWFyY2hhIG1vdG9yIDExMFYgNTAvNjBIeiIsICJDYXBhY2l0b3IiLCAiTUVESUEiLCAiTmV1bWF0aWNvIC8gSGlkcmF1bGljbyIsIDMsIDMsICIy4oCTMyBkw61hcyIsICJDT0lOU0EgLyBHcmFpbmdlciIsICJFc3RhbnRlOiBFTEVDVFJPIFbDgUxWVUxBUyIsIDE4MC4wLCAi4pyTIiwgIkdlbsOpcmljbyIsICIiXSwgWyJSb2RhbWllbnRvIC8gYmFsZXJvIFVSQiBSVU0iLCAiUm9kYW1pZW50byIsICJNRURJQSIsICJOZXVtYXRpY28gLyBIaWRyYXVsaWNvIiwgMiwgMSwgIjPigJM1IGTDrWFzIiwgIkRpc3RyaWJ1aWRvcmEgU0tGIiwgIkVzdGFudGU6IFJPREFNSUVOVE9TIiwgMjUwLjAsICJWZXJpZmljYXIgIyBhbnRlcyBkZSBwZWRpciIsICJVUkIgUlVNIiwgIiJdLCBbIkZpdHRpbmcgbmV1bcOhdGljbyBwdXNoLXRvLWNvbm5lY3Qgc3VydGlkbyIsICJGaXR0aW5nIiwgIkJBSkEiLCAiTmV1bWF0aWNvIC8gSGlkcmF1bGljbyIsIDEwLCAxMCwgIjHigJMyIGTDrWFzIiwgIlNNQyAvIENPSU5TQSIsICJFc3RhbnRlOiBFTEVDVFJPIFbDgUxWVUxBUyIsIDQ1LjAsICLinJMiLCAiU01DIiwgIlBhcmtlciJdLCBbIk1hbmd1ZXJhIGFpcmUgdGVqaWRhIGJsYW5jYSAoc3Bvb2wpIiwgIk1hbmd1ZXJhIiwgIkJBSkEiLCAiTmV1bWF0aWNvIC8gSGlkcmF1bGljbyIsIDEsIDEsICIz4oCTNSBkw61hcyIsICJDT0lOU0EgLyBTTUMiLCAiQm9kZWdhIC8gcGlzbyIsIDE4MDAuMCwgIlJvbGxvIOKckyIsICJHZW7DqXJpY28iLCAiIl0sIFsiU29sZGFkdXJhIGVzdGHDsW8gNjAvNDAgMW1tIDQ1MGciLCAiQ29uc3VtaWJsZSIsICJCQUpBIiwgIkNvbnN1bWlibGVzIC8gSW5zdW1vcyIsIDIsIDIsICIxIGTDrWEiLCAiVHJ1cGVyIC8gZmVycmV0ZXLDrWEiLCAiRXN0YW50ZTogSEVSUkFNSUVOVEEiLCAxODAuMCwgIlZhcmlvcyByb2xsb3Mg4pyTIiwgIlRydXBlciA2MCIsICI0MCJdLCBbIkNpbnRhIGFpc2xhbnRlIFBWQyBhbWFyaWxsYSIsICJDb25zdW1pYmxlIiwgIkJBSkEiLCAiQ29uc3VtaWJsZXMgLyBJbnN1bW9zIiwgNCwgMywgIjEgZMOtYSIsICJPZmZpY2UgRGVwb3QiLCAiRXN0YW50ZTogQ09OVEFDVE9SRVMiLCAzNS4wLCAiIiwgIlZvbHRlYyIsICIzTSJdLCBbIkNpbnRhIGZpYnJhIGRlIHZpZHJpbyBhbHRhIHRlbXAuIiwgIkNvbnN1bWlibGUiLCAiTUVESUEiLCAiQ29uc3VtaWJsZXMgLyBJbnN1bW9zIiwgMiwgMSwgIjPigJM1IGTDrWFzIiwgIkNPSU5TQSIsICJFc3RhbnRlOiBSRVNJU1RFTkNJQVMiLCAxMjAuMCwgIlBhcmEgcmVzaXN0ZW5jaWFzIiwgIkdlbsOpcmljbyIsICIiXSwgWyJDaW50YSB0ZWZsw7NuIDEvMlwiIiwgIkNvbnN1bWlibGUiLCAiQkFKQSIsICJDb25zdW1pYmxlcyAvIEluc3Vtb3MiLCA1LCAzLCAiMSBkw61hIiwgIkZlcnJldGVyw61hIiwgIkVzdGFudGU6IEhFUlJBTUlFTlRBIiwgMTguMCwgIiIsICJHZW7DqXJpY28iLCAiIl0sIFsiUGVnYW1lbnRvIGluc3RhbnTDoW5lbyBzdXBlciBnbHVlIiwgIkNvbnN1bWlibGUiLCAiQkFKQSIsICJDb25zdW1pYmxlcyAvIEluc3Vtb3MiLCAyLCAyLCAiMSBkw61hIiwgIkZlcnJldGVyw61hIiwgIkVzdGFudGU6IENPTlRBQ1RPUkVTIiwgNDUuMCwgIuKckyIsICJMb2N0aXRlIiwgIkdlbsOpcmljbyJdLCBbIkx1YnJpY2FudGUgYW50aS1hZ2Fycm90YW1pZW50byBMQiA3NzEiLCAiTHVicmljYW50ZSIsICJCQUpBIiwgIkNvbnN1bWlibGVzIC8gSW5zdW1vcyIsIDEsIDEsICI14oCTNyBkw61hcyIsICJHcmFpbmdlciIsICJFc3RhbnRlOiBSRVNJU1RFTkNJQVMiLCAzODAuMCwgIkxhdGEg4pyTIiwgIkxCIDc3MSIsICJKZXQtTHViZSJdLCBbIkFjZWl0ZSByZWZyaWdlcmFudGUgV8O8cnRoIDUwMG1sIHNwcmF5IiwgIkx1YnJpY2FudGUiLCAiQkFKQSIsICJDb25zdW1pYmxlcyAvIEluc3Vtb3MiLCAyLCAxLCAiM+KAkzUgZMOtYXMiLCAiV8O8cnRoIE1YIiwgIkVzdGFudGU6IFJPREFNSUVOVE9TIiwgMjgwLjAsICIiLCAiV8O8cnRoIDUyMCIsICIiXSwgWyJDb21wdWVzdG8gdMOpcm1pY28gQXJjdGljIiwgIkNvbnN1bWlibGUiLCAiQkFKQSIsICJDb25zdW1pYmxlcyAvIEluc3Vtb3MiLCAxLCAxLCAiM+KAkzUgZMOtYXMiLCAiQW1hem9uIiwgIkVzdGFudGU6IEhFUlJBTUlFTlRBIiwgMTUwLjAsICIiLCAiQXJjdGljIiwgIiJdLCBbIkNhYmxlIGNvbmR1Y3RvciBWaWFrb24gLyBDb25kdW1leCAocm9sbG8pIiwgIkNhYmxlIiwgIk1FRElBIiwgIkNvbnN1bWlibGVzIC8gSW5zdW1vcyIsIDEsIDEsICIz4oCTNSBkw61hcyIsICJWaWFrb24gLyBFTE1FU0kiLCAiRXN0YW50ZTogUkVTSVNURU5DSUFTIiwgMTIwMC4wLCAiQ2FsLiBzZWfDum4gYXBsaWNhY2nDs24iLCAiVmlha29uIiwgIkNvbmR1bWV4Il1d").decode("utf-8"))
    for _r in _seed:
        con.execute("INSERT OR IGNORE INTO refacciones (nombre,categoria,criticidad,seccion,cant_min,stock_actual,tiempo_entrega,proveedor,ubicacion,costo,notas,marca,modelo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", _r)
    con.commit()  # seed

    # -- Seed refacciones BATCH 2 (fotos almacen) --
    import base64 as _b64x, json as _jx
    _seed2 = _jx.loads(_b64x.b64decode("W1siQXV0b25pY3MgVENONFMtMjRSIENvbnRyb2xhZG9yIGRlIFRlbXBlcmF0dXJhIiwgIkNvbnRyb2wgdGVtcC4iLCAiQUxUQSIsICJFbGVjdHJpY28gLyBDb250cm9sIiwgMiwgMywgIjMtNSBkaWFzIiwgIkNPSU5TQSAvIEF1dG9uaWNzIiwgIkVzdGFudGU6IFRJTUVSIiwgMCwgIiIsICJBdXRvbmljcyIsICJUQ040Uy0yNFIiXSwgWyJBdXRvbmljcyBBVDhOIFRpbWVyIDEwMC0yNDBWQUMiLCAiVGltZXIiLCAiTUVESUEiLCAiRWxlY3RyaWNvIC8gQ29udHJvbCIsIDIsIDMsICIzLTUgZGlhcyIsICJDT0lOU0EgLyBBdXRvbmljcyIsICJFc3RhbnRlOiBUSU1FUiIsIDAsICIiLCAiQXV0b25pY3MiLCAiQVQ4TiJdLCBbIkNvbnRhY3RvciBDSElOVCBOWEMtMzIgMjIwViAzMkEiLCAiQ29udGFjdG9yIiwgIkFMVEEiLCAiRWxlY3RyaWNvIC8gQ29udHJvbCIsIDIsIDQsICIxLTIgZGlhcyIsICJFTE1FU0kgLyBDT0lOU0EiLCAiRXN0YW50ZTogQ09OVEFDVE9SRVMiLCAwLCAiIiwgIkNISU5UIiwgIk5YQy0zMiA5MjUyMTMiXSwgWyJSZWxldmFkb3IgdGVybWljbyBDSElOVCBOUjItMjUgMi41QSIsICJSZWxldmFkb3IiLCAiQUxUQSIsICJFbGVjdHJpY28gLyBDb250cm9sIiwgMiwgMSwgIjEtMiBkaWFzIiwgIkVMTUVTSSIsICJFc3RhbnRlOiBDT05UQUNUT1JFUyIsIDAsICIiLCAiQ0hJTlQiLCAiTlIyLTI1IDI2ODEwNiJdLCBbIlJlbGV2YWRvciBGaW5kZXIgMTBBIDIzMFZBQyA4LXBpbiIsICJSZWxldmFkb3IiLCAiTUVESUEiLCAiRWxlY3RyaWNvIC8gQ29udHJvbCIsIDQsIDQsICIxLTIgZGlhcyIsICJFTE1FU0kgLyBDT0lOU0EiLCAiRXN0YW50ZTogQ09OVEFDVE9SRVMiLCAwLCAiIiwgIkZpbmRlciIsICI2MC4xMi44LjIzMC4wMDQwIl0sIFsiUmVsZXZhZG9yIEFzaWFvbiAxMEEgMjUwVkFDIiwgIlJlbGV2YWRvciIsICJNRURJQSIsICJFbGVjdHJpY28gLyBDb250cm9sIiwgMiwgMSwgIjEtMiBkaWFzIiwgIkVMTUVTSSIsICJFc3RhbnRlOiBDT05UQUNUT1JFUyIsIDAsICIiLCAiQXNpYW9uIiwgIjkwLjItMS0yMiJdLCBbIlNTUiBHb2xkIFNBUDQ5NTBEIDUwQSAzMlZEQyIsICJTU1IiLCAiQUxUQSIsICJFbGVjdHJpY28gLyBDb250cm9sIiwgMSwgMSwgIjMtNSBkaWFzIiwgIkNPSU5TQSIsICJFc3RhbnRlOiBIRVJSQU1JRU5UQSIsIDAsICIiLCAiR29sZCIsICJTQVA0OTUwRCJdLCBbIkludGVycnVwdG9yIHRlcm1vbWFnbmV0aWNvIE1vZWxsZXIgWHBvbGUgQzIgMkEiLCAiUHJvdGVjY2lvbiIsICJNRURJQSIsICJFbGVjdHJpY28gLyBDb250cm9sIiwgMSwgMSwgIjMtNSBkaWFzIiwgIkVMTUVTSSIsICJFc3RhbnRlOiBDT05UQUNUT1JFUyIsIDAsICIiLCAiTW9lbGxlciIsICJYcG9sZSBDMiJdLCBbIkZ1ZW50ZSBNb2VsbGVyIGVhc3k0MDAtUE9XIDI0VkRDIiwgIkZ1ZW50ZSBEQyIsICJBTFRBIiwgIkVsZWN0cmljbyAvIENvbnRyb2wiLCAxLCAxLCAiNS03IGRpYXMiLCAiRUxNRVNJIiwgIkVzdGFudGU6IEhFUlJBTUlFTlRBIiwgMCwgIiIsICJNb2VsbGVyIiwgImVhc3k0MDAtUE9XIl0sIFsiUHVsc2Fkb3IgbmVncm8gMjJtbSBjb24gY29udGFjdG8gTkMiLCAiUHVsc2Fkb3IiLCAiQkFKQSIsICJFbGVjdHJpY28gLyBDb250cm9sIiwgNCwgNSwgIjEtMiBkaWFzIiwgIkNPSU5TQSAvIEVMTUVTSSIsICJFc3RhbnRlOiBDT05UQUNUT1JFUyIsIDAsICIiLCAiU2NobmVpZGVyIC8gWkIyIiwgIlpCMi1CQTMiXSwgWyJQdWxzYWRvciBhbWFyaWxsbyAyMm1tIGlsdW1pbmFkbyIsICJQdWxzYWRvciIsICJCQUpBIiwgIkVsZWN0cmljbyAvIENvbnRyb2wiLCAyLCAyLCAiMS0yIGRpYXMiLCAiQ09JTlNBIC8gRUxNRVNJIiwgIkVzdGFudGU6IENPTlRBQ1RPUkVTIiwgMCwgIiIsICJTY2huZWlkZXIgLyBaQjIiLCAiWkIyLUJXMzUiXSwgWyJQdWxzYWRvciBhenVsIDIybW0gaWx1bWluYWRvIiwgIlB1bHNhZG9yIiwgIkJBSkEiLCAiRWxlY3RyaWNvIC8gQ29udHJvbCIsIDIsIDIsICIxLTIgZGlhcyIsICJDT0lOU0EgLyBFTE1FU0kiLCAiRXN0YW50ZTogQ09OVEFDVE9SRVMiLCAwLCAiIiwgIlNjaG5laWRlciAvIFpCMiIsICJaQjItQlczNiJdLCBbIlNlbGVjdG9yIGRlIGxsYXZlIDIgcG9zaWNpb25lcyAyMm1tIiwgIlNlbGVjdG9yIiwgIkJBSkEiLCAiRWxlY3RyaWNvIC8gQ29udHJvbCIsIDIsIDIsICIxLTIgZGlhcyIsICJDT0lOU0EgLyBFTE1FU0kiLCAiRXN0YW50ZTogQ09OVEFDVE9SRVMiLCAwLCAiIiwgIlNjaG5laWRlciAvIFpCMiIsICJaQjItQkcyIl0sIFsiQmxvcXVlIGNvbnRhY3RvIFpCMi1CRTEwMSBOTyAxMEEiLCAiQWNjZXNvcmlvIiwgIkJBSkEiLCAiRWxlY3RyaWNvIC8gQ29udHJvbCIsIDQsIDIsICIxLTIgZGlhcyIsICJDT0lOU0EiLCAiRXN0YW50ZTogQ09OVEFDVE9SRVMiLCAwLCAiIiwgIlNjaG5laWRlciIsICJaQjItQkUxMDEiXSwgWyJUZXJtb21ldHJvIGRpZ2l0YWwgVHJhY2VhYmxlIGMvc29uZGEiLCAiSW5zdHJ1bWVudG8iLCAiTUVESUEiLCAiRWxlY3RyaWNvIC8gQ29udHJvbCIsIDEsIDEsICI1LTcgZGlhcyIsICJGaXNoZXIgLyBHcmFpbmdlciIsICJFc3RhbnRlOiBIRVJSQU1JRU5UQSIsIDAsICJQYXJhIHZlcmlmaWNhY2lvbiBkZSB0ZW1wZXJhdHVyYSIsICJUcmFjZWFibGUiLCAiVC9DIl0sIFsiQ29udGFkb3IgQXV0b25pY3MgTEVCTiIsICJJbnN0cnVtZW50byIsICJCQUpBIiwgIkVsZWN0cmljbyAvIENvbnRyb2wiLCAxLCAxLCAiMy01IGRpYXMiLCAiQXV0b25pY3MgLyBDT0lOU0EiLCAiRXN0YW50ZTogSEVSUkFNSUVOVEEiLCAwLCAiIiwgIkF1dG9uaWNzIiwgIkxFQk4iXSwgWyJSZXNpc3RlbmNpYSBjZXJhbWljYSBpbmZyYXJyb2phIEFFU0EiLCAiUmVzaXN0ZW5jaWEiLCAiQUxUQSIsICJSZXNpc3RlbmNpYXMgLyBDYWxlZmFjY2lvbiIsIDIsIDMsICI1LTEwIGRpYXMiLCAiQUVTQSAvIFRDUiIsICJFc3RhbnRlOiBSRVNJU1RFTkNJQVMiLCAwLCAiQ2VyYW1pYyBJbmZyYXJlZCBIZWF0ZXIiLCAiQUVTQSIsICIiXSwgWyJSZXNpc3RlbmNpYSBjZXJhbWljYSBpbmZyYXJyb2phIENlcmFtaWN4IiwgIlJlc2lzdGVuY2lhIiwgIkFMVEEiLCAiUmVzaXN0ZW5jaWFzIC8gQ2FsZWZhY2Npb24iLCAxLCAxLCAiNS0xMCBkaWFzIiwgIkNlcmFtaWN4IiwgIkVzdGFudGU6IFJFU0lTVEVOQ0lBUyIsIDAsICJJbmZyYXJlZCBmb3IgSW5kdXN0cnkgQ0UiLCAiQ2VyYW1pY3giLCAiIl0sIFsiUmVzaXN0ZW5jaWEgcGxhbmEgMjIwLzIzMFZBQyAzNTBXIHRlcm1vcGFyIEsgMTJ4Ni41Y20iLCAiUmVzaXN0ZW5jaWEiLCAiQUxUQSIsICJSZXNpc3RlbmNpYXMgLyBDYWxlZmFjY2lvbiIsIDEsIDEsICI1LTEwIGRpYXMiLCAiVENSIiwgIkVzdGFudGU6IFJFU0lTVEVOQ0lBUyIsIDAsICIxIHBpZXphIiwgIlRDUiIsICIyMjAvMjMwVkFDIDM1MFciXSwgWyJSZXNpc3RlbmNpYSBwbGFuYSAyMjAvMjMwVkFDIDMyNVcgMTJ4Ni41Y20gKHNpbiBzZW5zb3IpIiwgIlJlc2lzdGVuY2lhIiwgIkFMVEEiLCAiUmVzaXN0ZW5jaWFzIC8gQ2FsZWZhY2Npb24iLCAyLCAyLCAiNS0xMCBkaWFzIiwgIlRDUiIsICJFc3RhbnRlOiBSRVNJU1RFTkNJQVMiLCAwLCAiMiBwaWV6YXMiLCAiVENSIiwgIjIyMC8yMzBWQUMgMzI1VyJdLCBbIlJlc2lzdGVuY2lhIHBsYW5hIDIyMC8yMzBWQUMgMzI1VyB0ZXJtb3BhciBLIDEyeDYuNWNtIiwgIlJlc2lzdGVuY2lhIiwgIkFMVEEiLCAiUmVzaXN0ZW5jaWFzIC8gQ2FsZWZhY2Npb24iLCAyLCA0LCAiNS0xMCBkaWFzIiwgIlRDUiIsICJFc3RhbnRlOiBSRVNJU1RFTkNJQVMiLCAwLCAiMisyIHBpZXphcyBjb24gdGVybW9wYXIgSyIsICJUQ1IiLCAiMjIwLzIzMFZBQyAzMjVXIEsiXSwgWyJSZXNpc3RlbmNpYSBwbGFuYSAyMjAvMjMwVkFDIDMyNVcgMTJ4Ni41Y20gKDMgcHphcykiLCAiUmVzaXN0ZW5jaWEiLCAiQUxUQSIsICJSZXNpc3RlbmNpYXMgLyBDYWxlZmFjY2lvbiIsIDIsIDMsICI1LTEwIGRpYXMiLCAiVENSIiwgIkVzdGFudGU6IFJFU0lTVEVOQ0lBUyIsIDAsICIzIHBpZXphcyIsICJUQ1IiLCAiMjIwVkFDLzIzMCAzMjVXIl0sIFsiVmFsdnVsYSBzb2xlbm9pZGUgREUgV0lUIDJXLTI1LU5DLUUtVlQ1IiwgIkVsZWN0cm92YWx2dWxhIiwgIkFMVEEiLCAiTmV1bWF0aWNvIC8gSGlkcmF1bGljbyIsIDEsIDEsICIzLTUgZGlhcyIsICJERSBXSVQgLyBDT0lOU0EiLCAiRXN0YW50ZTogRUxFQ1RSTyBWQUxWVUxBUyIsIDAsICJOQyBub3JtYWxtZW50ZSBjZXJyYWRhIiwgIkRFIFdJVCIsICIyVy0yNS1OQy1FLVZUNSJdLCBbIlZhbHZ1bGEgc29sZW5vaWRlIG5ldW1hdGljYSA1LzIgdmlhcyBtYW5pZm9sZCIsICJFbGVjdHJvdmFsdnVsYSIsICJBTFRBIiwgIk5ldW1hdGljbyAvIEhpZHJhdWxpY28iLCAyLCAyLCAiMy01IGRpYXMiLCAiU01DIC8gQ09JTlNBIiwgIkVzdGFudGU6IEVMRUNUUk8gVkFMVlVMQVMiLCAwLCAiQ29uIGJvYmluYSAyMjBWQUMiLCAiU01DIC8gSFVZTyIsICIiXSwgWyJWYWx2dWxhIHNlZ3VyaWRhZCBLb21hdHN1IFNhZmUgVmFsdmUiLCAiVmFsdnVsYSIsICJBTFRBIiwgIk5ldW1hdGljbyAvIEhpZHJhdWxpY28iLCAxLCAxLCAiNy0xNCBkaWFzIiwgIktvbWF0c3UiLCAiRXN0YW50ZTogSEVSUkFNSUVOVEEiLCAwLCAiUGFydCBOby4gMDgwMTktMDA0OTgtMTAwIiwgIktvbWF0c3UiLCAiMDgwMTktMDA0OTgtMTAwIl0sIFsiTWFub21ldHJvIEFzaGNyb2Z0IDYzbW0gVkFDIGFjZXJvIGlub3giLCAiSW5zdHJ1bWVudG8iLCAiQkFKQSIsICJOZXVtYXRpY28gLyBIaWRyYXVsaWNvIiwgMSwgMSwgIjMtNSBkaWFzIiwgIkNPSU5TQSAvIEdyYWluZ2VyIiwgIkVzdGFudGU6IE1BTk9NRVRST1MiLCAwLCAiNjMgMTAwOCBBIDAyTCBYTEpaQyBWQUMiLCAiQXNoY3JvZnQiLCAiNjMgMTAwOCJdLCBbIkJhbGVybyAvIHJvZGFtaWVudG8gWlNHIiwgIlJvZGFtaWVudG8iLCAiTUVESUEiLCAiTmV1bWF0aWNvIC8gSGlkcmF1bGljbyIsIDIsIDIsICIzLTUgZGlhcyIsICJaU0cgLyBEaXN0cmlidWlkb3JhIiwgIkVzdGFudGU6IFJPREFNSUVOVE9TIiwgMCwgIiIsICJaU0ciLCAiQmVhcmluZ3MiXSwgWyJMb2N0aXRlIExCIDc3MSBOaWNrZWwgQW50aS1TZWl6ZSA0NTNnIiwgIkx1YnJpY2FudGUiLCAiTUVESUEiLCAiQ29uc3VtaWJsZXMgLyBJbnN1bW9zIiwgMSwgMSwgIjMtNSBkaWFzIiwgIkdyYWluZ2VyIC8gSGVua2VsIiwgIkVzdGFudGU6IFJFU0lTVEVOQ0lBUyIsIDAsICJBbnRpYWdhcnJvdGFtaWVudG8gaGFzdGEgMTMxNUMiLCAiTG9jdGl0ZSIsICJMQiA3NzEgMTM1NTQzIl0sIFsiUGFzdGEgdGVybWljYSBBcmN0aWMgTVgtNCIsICJDb25zdW1pYmxlIiwgIkJBSkEiLCAiQ29uc3VtaWJsZXMgLyBJbnN1bW9zIiwgMSwgMSwgIjMtNSBkaWFzIiwgIkFtYXpvbiIsICJFc3RhbnRlOiBIRVJSQU1JRU5UQSIsIDAsICIiLCAiQXJjdGljIiwgIk1YLTQiXSwgWyJUb3JuaWxsZXJpYSBhdXRvcnJvc2NhbnRlIHN1cnRpZGEgKGJvbHNhKSIsICJUb3JuaWxsZXJpYSIsICJCQUpBIiwgIkNvbnN1bWlibGVzIC8gSW5zdW1vcyIsIDIsIDIsICIxIGRpYSIsICJGZXJyZXRlcmlhIiwgIkJvZGVnYSAvIHBpc28iLCAwLCAiQm9sc2FzIHN1cnRpZGFzIiwgIkdlbmVyaWNvIiwgIiJdXQ==").decode("utf-8"))
    for _r2 in _seed2:
        try:
            con.execute("INSERT OR IGNORE INTO refacciones (nombre,categoria,criticidad,seccion,cant_min,stock_actual,tiempo_entrega,proveedor,ubicacion,costo,notas,marca,modelo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", _r2)
        except: pass
    con.commit()  # seed2

    # -- Seed refacciones BATCH 3 (fotos almacen 2) --
    import base64 as _b64y, json as _jy
    _seed3 = _jy.loads(_b64y.b64decode("W1siUmVzaXN0ZW5jaWEgcGxhbmEgVENSIDIyMC8yMzBWQUMgNjUwVyB0ZXJtb3BhciBLIDI1eDYuNWNtIiwgIlJlc2lzdGVuY2lhIiwgIkFMVEEiLCAiUmVzaXN0ZW5jaWFzIC8gQ2FsZWZhY2Npb24iLCAxLCAxLCAiNS0xMCBkaWFzIiwgIlRDUiIsICJFc3RhbnRlOiBSRVNJU1RFTkNJQVMiLCAwLCAiU0FMMDAwMDIsIDEgcGllemEsIDI1eDYuNWNtIiwgIlRDUiIsICIyMjAvMjMwVkFDIDY1MFcgSyJdLCBbIlJlc2lzdGVuY2lhIHBsYW5hIFRDUiAyMjAvMjMwVkFDIDYyNVcgdGVybW9wYXIgSyAyNXg2LjVjbSIsICJSZXNpc3RlbmNpYSIsICJBTFRBIiwgIlJlc2lzdGVuY2lhcyAvIENhbGVmYWNjaW9uIiwgMSwgMSwgIjUtMTAgZGlhcyIsICJUQ1IiLCAiRXN0YW50ZTogUkVTSVNURU5DSUFTIiwgMCwgIlNBTDAwMDAyIE5FR1UsIDEgcGllemEsIDI1eDYuNWNtIiwgIlRDUiIsICIyMjAvMjMwVkFDIDYyNVcgSyJdLCBbIlJlc2lzdGVuY2lhIHBsYW5hIFRDUiAyMjAvMjMwVkFDIDMwMFcgdGVybW9wYXIgSyAxMng2LjVjbSIsICJSZXNpc3RlbmNpYSIsICJBTFRBIiwgIlJlc2lzdGVuY2lhcyAvIENhbGVmYWNjaW9uIiwgMSwgMSwgIjUtMTAgZGlhcyIsICJUQ1IiLCAiRXN0YW50ZTogUkVTSVNURU5DSUFTIiwgMCwgIjEgcGllemEsIDEyeDYuNWNtIGNvbiB0ZXJtb3BhciBLIiwgIlRDUiIsICIyMjAvMjMwVkFDIDMwMFcgSyJdLCBbIlJlc2lzdGVuY2lhIHRpcG8gVSAyMjBWQUMgcGFyYSBjYWxlZmFjY2lvbiAoI0JOLTEpIiwgIlJlc2lzdGVuY2lhIiwgIkFMVEEiLCAiUmVzaXN0ZW5jaWFzIC8gQ2FsZWZhY2Npb24iLCA1LCAxNSwgIjUtMTAgZGlhcyIsICJUQ1IiLCAiRXN0YW50ZTogUkVTSVNURU5DSUFTIiwgMCwgIlJlc2lzdGVuY2lhcyBmb3JtYSBVLCBjYWphIEJOLTEsIG11bHRpcGxlcyB1bmlkYWRlcyIsICJHZW5lcmljbyIsICJVLXR5cGUgMjIwVkFDIl0sIFsiU1NSIEZvdGVrIFNTUi0yNVZBIDI1QSBTb2xpZCBTdGF0ZSBSZWxheSIsICJTU1IiLCAiQUxUQSIsICJFbGVjdHJpY28gLyBDb250cm9sIiwgMiwgMywgIjMtNSBkaWFzIiwgIkNPSU5TQSAvIEZvdGVrIiwgIkVzdGFudGU6IENPTlRBQ1RPUkVTIiwgMCwgIkxvdGUgMjMzRiwgMyB1bmlkYWRlcyBkaXNwb25pYmxlcyIsICJGb3RlayIsICJTU1ItMjVWQSJdLCBbIlNTUiBKTVAgSk8tMzRGIDkwQSA0ODBWQUMgNC0zMlZEQyIsICJTU1IiLCAiQUxUQSIsICJFbGVjdHJpY28gLyBDb250cm9sIiwgMSwgMSwgIjMtNSBkaWFzIiwgIkNPSU5TQSIsICJFc3RhbnRlOiBIRVJSQU1JRU5UQSIsIDAsICJELTQ4MEE1MFpTLUwsIDkwQSBjYXJnYSIsICJKTVAiLCAiSk8tMzRGIEQtNDgwQTUwWlMtTCJdLCBbIk1pY3Jvc3dpdGNoIGxpbWl0ZSBNb2RlbG8gMTE2LTAyMSAxNUEgMTI1LTQ4MFYiLCAiU3dpdGNoIiwgIk1FRElBIiwgIkVsZWN0cmljbyAvIENvbnRyb2wiLCAyLCAzLCAiMy01IGRpYXMiLCAiQ09JTlNBIC8gR3JhaW5nZXIiLCAiRXN0YW50ZTogQ09OVEFDVE9SRVMiLCAwLCAiMTVBIDEyNS00ODBWLCBwYWxhbmNhIiwgIkdlbmVyaWNvIiwgIjExNi0wMjEiXSwgWyJDb25kZW5zYWRvciBkZSBhcnJhbnF1ZS9tYXJjaGEgbW90b3IgMjIwVkFDIiwgIkNvbmRlbnNhZG9yIiwgIkFMVEEiLCAiRWxlY3RyaWNvIC8gQ29udHJvbCIsIDEsIDEsICIzLTUgZGlhcyIsICJFTE1FU0kgLyBHcmFpbmdlciIsICJFc3RhbnRlOiBIRVJSQU1JRU5UQSIsIDAsICJDYXBhY2l0b3IgZWxlY3Ryb2xpdGljbyBkZSBtb3RvciIsICJHZW5lcmljbyIsICIiXSwgWyJGdXNpYmxlcyBzdXJ0aWRvcyAoY2FqYSkiLCAiRnVzaWJsZSIsICJBTFRBIiwgIkVsZWN0cmljbyAvIENvbnRyb2wiLCAxMCwgMjAsICIxLTIgZGlhcyIsICJFTE1FU0kgLyBGZXJyZXRlcmlhIiwgIkVzdGFudGU6IEhFUlJBTUlFTlRBIiwgMCwgIkZ1c2libGVzIGRlIHZpZHJpbyB5IGNlcmFtaWNhIHN1cnRpZG9zIiwgIlN1cnRpZG8iLCAiIl0sIFsiQ2FibGUgTWljYSBUYXBlIEdsYXNzIEJyYWlkIDEwQVdHIDUwMEMgNjAwViBOaXF1ZWwgcHVybyAxMDBtIiwgIkNhYmxlIiwgIkFMVEEiLCAiQ29uc3VtaWJsZXMgLyBJbnN1bW9zIiwgMSwgMiwgIjUtMTAgZGlhcyIsICJQcm92ZWVkb3IgZXNwZWNpYWwiLCAiRXN0YW50ZTogVEVSTUlOQUxFUyIsIDAsICJNSUNBL1BURkUgVEFQRSwgUHVyZSBOaWNrZWwsIHJvbGxvIDEwMG0sIDQtSlVOLTIwMjUiLCAiR2VuZXJpY28iLCAiMTBBV0cgNzQvMC4zIDUwMEMiXSwgWyJDYWJsZSBWaWFrb24gWFhJIFJvSFMgMTQgQVdHIG5lZ3JvIDEwMG0iLCAiQ2FibGUiLCAiTUVESUEiLCAiQ29uc3VtaWJsZXMgLyBJbnN1bW9zIiwgMSwgMSwgIjEtMiBkaWFzIiwgIlZpYWtvbiAvIENvbmR1Y3RvcmVzIE1UWSIsICJFc3RhbnRlOiBURVJNSU5BTEVTIiwgMCwgIlRIVy1MUywgOTBDLCByb2xsbyAxMDBtIiwgIlZpYWtvbiIsICJYWEkgUm9IUyAxNEFXRyJdLCBbIkNhYmxlIFZpYWtvbiBURi1MUyAxNiBBV0cgbmVncm8gMTAwbSIsICJDYWJsZSIsICJNRURJQSIsICJDb25zdW1pYmxlcyAvIEluc3Vtb3MiLCAxLCAxLCAiMS0yIGRpYXMiLCAiVmlha29uIC8gQ29uZHVjdG9yZXMgTVRZIiwgIkVzdGFudGU6IFRFUk1JTkFMRVMiLCAwLCAiNjAwViA5MEMsIHJvbGxvIDEwMG0sIENhdCAxMjczMDgiLCAiVmlha29uIiwgIlRGLUxTIDE2IDEyNzMwOCJdLCBbIkNhYmxlIFZpYWtvbiAxMiBBV0cgcm9qbyA5MEMgMTAwbSIsICJDYWJsZSIsICJNRURJQSIsICJDb25zdW1pYmxlcyAvIEluc3Vtb3MiLCAxLCAxLCAiMS0yIGRpYXMiLCAiVmlha29uIC8gQ29uZHVjdG9yZXMgTVRZIiwgIkVzdGFudGU6IFRFUk1JTkFMRVMiLCAwLCAiVEhXLUxTIFRISFctTFMsIDkwQyIsICJWaWFrb24iLCAiWFhJIDEyQVdHIHJvam8iXSwgWyJSb2RhbWllbnRvIC8gY2h1bWFjZXJhIFVSQiBQaWxsb3cgQmxvY2sgQmVhcmluZyIsICJSb2RhbWllbnRvIiwgIk1FRElBIiwgIk5ldW1hdGljbyAvIEhpZHJhdWxpY28iLCAxLCAxLCAiMy01IGRpYXMiLCAiRGlzdHJpYnVpZG9yYSBNVFkiLCAiRXN0YW50ZTogUk9EQU1JRU5UT1MiLCAwLCAiRXhwb3J0IHRvIEdlcm1hbnksIElTTyA5MDAxIiwgIlVSQiAvIFJVTSIsICJQaWxsb3cgQmxvY2siXSwgWyJXdXJ0aCBXLU1vdG8gTHViZSBncmFzYSBjYWRlbmEgMzAwbWwiLCAiTHVicmljYW50ZSIsICJCQUpBIiwgIkNvbnN1bWlibGVzIC8gSW5zdW1vcyIsIDEsIDEsICIzLTUgZGlhcyIsICJXdXJ0aCIsICJFc3RhbnRlOiBIRVJSQU1JRU5UQSIsIDAsICJMdWJyaWNhbnRlLWFudGljb3Jyb3Npdm8gcGFyYSBjYWRlbmFzIiwgIld1cnRoIiwgIlctTW90byBMdWJlIl0sIFsiV3VydGggQWNlaXRlIFJlZnJpZ2VyYW50ZSBjb3J0ZSA0MDBtbCIsICJMdWJyaWNhbnRlIiwgIkJBSkEiLCAiQ29uc3VtaWJsZXMgLyBJbnN1bW9zIiwgMSwgMSwgIjMtNSBkaWFzIiwgIld1cnRoIiwgIkVzdGFudGU6IEhFUlJBTUlFTlRBIiwgMCwgIkx1YnJpY2EsIHJlZnJpZ2VyYSB5IGNvbnNlcnZhIGhlcnJhbWllbnRhIGRlIGNvcnRlIiwgIld1cnRoIiwgIkFjZWl0ZSBSZWZyaWdlcmFudGUiXSwgWyJFc3Rhbm8gVHJ1cGVyIDYwLzQwIDFtbSByb2xsbyA0NTBnIHBhcmEgZWxlY3Ryb25pY2EiLCAiQ29uc3VtaWJsZSIsICJNRURJQSIsICJDb25zdW1pYmxlcyAvIEluc3Vtb3MiLCAxLCAyLCAiMS0yIGRpYXMiLCAiVHJ1cGVyIC8gRmVycmV0ZXJpYSIsICJFc3RhbnRlOiBIRVJSQU1JRU5UQSIsIDAsICJFc3Rhbm8gZGUgcGxvbWVybyA2MC80MCwgcGFyYSBlbGVjdHJvbmljYSIsICJUcnVwZXIiLCAiU09MLTQ1ME0iXSwgWyJQYXN0YSBmbHV4IGRlIHNvbGRhZHVyYSBPbWVnYSAoZnJhc2NvIGFtYXJpbGxvKSIsICJDb25zdW1pYmxlIiwgIkJBSkEiLCAiQ29uc3VtaWJsZXMgLyBJbnN1bW9zIiwgMSwgMSwgIjEtMiBkaWFzIiwgIkZlcnJldGVyaWEgbG9jYWwiLCAiRXN0YW50ZTogSEVSUkFNSUVOVEEiLCAwLCAiRmx1eCBkZWNhcGFudGUgcGFyYSBzb2xkYWR1cmEgZWxlY3Ryb25pY2EiLCAiT21lZ2EiLCAiIl0sIFsiUGVnYW1lbnRvIGluc3RhbnRhbmVvIGNpYW5vYWNyaWxhdG8gKGJvdGVsbGEgYXp1bCkiLCAiQ29uc3VtaWJsZSIsICJCQUpBIiwgIkNvbnN1bWlibGVzIC8gSW5zdW1vcyIsIDEsIDEsICIxLTIgZGlhcyIsICJGZXJyZXRlcmlhIGxvY2FsIiwgIkJvZGVnYSIsIDAsICJTdXBlciBhZGhlc2l2byIsICJHZW5lcmljbyIsICIiXSwgWyJDb25lY3RvcmVzIHJhcGlkb3MgbmV1bWF0aWNvcyBwdXNoLWluIHN1cnRpZG8iLCAiQ29uZWN0b3IiLCAiTUVESUEiLCAiTmV1bWF0aWNvIC8gSGlkcmF1bGljbyIsIDUsIDE1LCAiMS0zIGRpYXMiLCAiQ09JTlNBIC8gRmVzdG8gLyBTTUMiLCAiRXN0YW50ZTogRUxFQ1RSTyBWQUxWVUxBUyIsIDAsICJQdXNoLWluIHBsYXN0aWNvIHkgbGF0b24sIHZhcmlhcyBtZWRpZGFzIDYtMTJtbSIsICJTTUMgLyBQYXJrZXIiLCAiUHVzaC1pbiJdLCBbIktpdCB0ZXJtaW5hbGVzIGFpc2xhZG9zIFZvbHRlY2sgNTUgcGllemFzIDIyLTEwIEFXRyIsICJUZXJtaW5hbCIsICJCQUpBIiwgIkNvbnN1bWlibGVzIC8gSW5zdW1vcyIsIDEsIDEsICIxLTIgZGlhcyIsICJWb2x0ZWNrIC8gRmVycmV0ZXJpYSIsICJFc3RhbnRlOiBURVJNSU5BTEVTIiwgMCwgIkFuaWxsbywgZXNwYWRhLCB1bmnDs24sIGhlbWJyYSwgbWFjaG87IDEyLTEwLzE2LTE0LzIyLTE2IEFXRyIsICJWb2x0ZWNrIiwgIlRETS00NTUiXSwgWyJUZXJtaW5hbGVzIGRlIGFyZ29sbGEgZGVzbnVkYXMgc3VydGlkbyAoY2FqaXRhKSIsICJUZXJtaW5hbCIsICJCQUpBIiwgIkNvbnN1bWlibGVzIC8gSW5zdW1vcyIsIDEwLCAzMCwgIjEgZGlhIiwgIkZlcnJldGVyaWEiLCAiRXN0YW50ZTogVEVSTUlOQUxFUyIsIDAsICJUZXJtaW5hbGVzIGRlIGNvYnJlIHNpbiBmb3JybyB2YXJpb3MgY2FsaWJyZXMiLCAiR2VuZXJpY28iLCAiIl0sIFsiVGVybWluYWxlcyBjZXJhbWljYSBhbHRhIHRlbXBlcmF0dXJhIDVUIChjaGFyb2xhKSIsICJUZXJtaW5hbCIsICJNRURJQSIsICJSZXNpc3RlbmNpYXMgLyBDYWxlZmFjY2lvbiIsIDUsIDE1LCAiMy01IGRpYXMiLCAiVENSIC8gUHJvdmVlZG9yIiwgIkVzdGFudGU6IFRFUk1JTkFMRVMiLCAwLCAiUGFyYSBjb25leGlvbiBkZSByZXNpc3RlbmNpYXMsIGFsdGEgdGVtcGVyYXR1cmEiLCAiR2VuZXJpY28iLCAiNVQgY2VyYW1pYyJdLCBbIkNpbnRhIGFpc2xhbnRlIDNNIG5lZ3JhIChyb2xsbyBncmFuZGUpIiwgIkNvbnN1bWlibGUiLCAiQkFKQSIsICJDb25zdW1pYmxlcyAvIEluc3Vtb3MiLCAxLCAxLCAiMS0yIGRpYXMiLCAiRmVycmV0ZXJpYSAvIDNNIiwgIkVzdGFudGU6IEhFUlJBTUlFTlRBIiwgMCwgIiIsICIzTSIsICJTY290Y2ggMzMrIl0sIFsiQ2ludGEgZmlicmEgZGUgdmlkcmlvIGFpc2xhbnRlIChyb2xsbykiLCAiQ29uc3VtaWJsZSIsICJNRURJQSIsICJSZXNpc3RlbmNpYXMgLyBDYWxlZmFjY2lvbiIsIDEsIDEsICIzLTUgZGlhcyIsICJQcm92ZWVkb3IgZXNwZWNpYWwiLCAiRXN0YW50ZTogUkVTSVNURU5DSUFTIiwgMCwgIlBhcmEgYWlzbGFtaWVudG8gZGUgcmVzaXN0ZW5jaWFzIGFsdGEgdGVtcGVyYXR1cmEiLCAiR2VuZXJpY28iLCAiRWxlY3RyaWNhbCBmaWJlcmdsYXNzIl1d").decode("utf-8"))
    for _r3 in _seed3:
        try:
            con.execute("INSERT OR IGNORE INTO refacciones (nombre,categoria,criticidad,seccion,cant_min,stock_actual,tiempo_entrega,proveedor,ubicacion,costo,notas,marca,modelo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", _r3)
        except: pass
    con.commit()  # seed3

    con.commit(); con.close()

def init_users_db():
    con = get_db()
    con.execute(
        """CREATE TABLE IF NOT EXISTS users
        (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL,
         email TEXT NOT NULL UNIQUE, pin_hash TEXT NOT NULL,
         created_at TEXT DEFAULT (datetime('now')))"""
    )
    con.commit(); con.close()

init_db()
init_users_db()

def hash_pin(pin):
    return hashlib.sha256(pin.encode()).hexdigest()

@app.route('/api/users/register', methods=['POST'])
def register_user():
    d = request.json
    nombre = d.get('nombre','').strip()
    email  = d.get('email','').strip().lower()
    pin    = d.get('pin','').strip()
    if not nombre or not email or not pin or len(pin) < 4:
        return jsonify({'error': 'Nombre, email y PIN (minimo 4 caracteres) requeridos'}), 400
    try:
        con = get_db()
        con.execute('INSERT INTO users (nombre, email, pin_hash) VALUES (?,?,?)',
                    (nombre, email, hash_pin(pin)))
        con.commit(); con.close()
        return jsonify({'ok': True, 'nombre': nombre, 'email': email})
    except Exception as e:
        if 'UNIQUE' in str(e):
            return jsonify({'error': 'Este email ya esta registrado'}), 409
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/login', methods=['POST'])
def login_user():
    d = request.json
    email = d.get('email','').strip().lower()
    pin   = d.get('pin','').strip()
    con = get_db()
    row = con.execute('SELECT id, nombre, email FROM users WHERE email=? AND pin_hash=?',
                      (email, hash_pin(pin))).fetchone()
    con.close()
    if not row:
        return jsonify({'error': 'Email o PIN incorrecto'}), 401
    return jsonify({'ok': True, 'id': row['id'], 'nombre': row['nombre'], 'email': row['email']})

@app.route('/api/users/verify', methods=['POST'])
def verify_user():
    d = request.json
    email = d.get('email','').strip().lower()
    pin   = d.get('pin','').strip()
    con = get_db()
    row = con.execute('SELECT id, nombre, email FROM users WHERE email=? AND pin_hash=?',
                      (email, hash_pin(pin))).fetchone()
    con.close()
    if not row:
        return jsonify({'ok': False, 'error': 'PIN incorrecto'}), 200
    return jsonify({'ok': True, 'nombre': row['nombre'], 'email': row['email']})

@app.route('/api/users', methods=['GET'])
def list_users():
    con = get_db()
    rows = con.execute('SELECT id, nombre, email, created_at FROM users ORDER BY nombre').fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

try:
    import openpyxl
    from openpyxl.utils import get_column_letter
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.page import PageMargins
except ImportError:
    os.system("pip install openpyxl -q")
    import openpyxl
    from openpyxl.utils import get_column_letter
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.page import PageMargins

MONTH_COLS = {"ENE":"B","FEB":"C","MAR":"D","ABR":"E","MAY":"F","JUN":"G",
              "JUL":"H","AGO":"I","SEP":"J","OCT":"K","NOV":"L","DIC":"M"}

def _wc(ws, row, col, value, alignment=None):
    cell = ws.cell(row=row, column=col)
    try:
        cell.value = value
    except AttributeError:
        return
    if alignment:
        cell.alignment = alignment

def apply_checklist_data(ws, data):
    SHEET_SIG = {
        'TF 1':45,'TF 2':45,'TF 3':45,'TF 4':45,'TF 5':45,'TF 6':45,'TF 7':45,
        'prensa 1':40,'Prensa 2':40,
        'Suajadora 1':26,'Suajadora 2':26,'Suajadora 5':26,'TCU':26,'Chiller':27,
        'Laminator':37,'Slitter Rewinder':37,'Komatsu OBS45':35,
        'Rotary Press':37,'Prensa PL':32,'IMESA':31,'Single Knife':31,
        'Hojeadora Robust':31,'Gapcutter':30,'Calender K1 Easy':41,
    }
    sheet_name = data.get('sheet', '')
    sig_row = SHEET_SIG.get(sheet_name) or data.get('sig_row')
    cal_row = data.get('cal_data_row')
    max_item_row = (sig_row - 1) if sig_row else 9999

    for item in data.get('items', []):
        row, st, cm = item['row'], item.get('status',''), item.get('comment','')
        if row > max_item_row:
            continue
        _wc(ws, row, 11, '( v )' if st == 'ok' else '(   )')
        _wc(ws, row, 12, '( v )' if st == 'ng' else '(   )')
        if cm:
            _wc(ws, row, 13, cm)

    months = set(data.get('month', []))
    if cal_row:
        for m, col in MONTH_COLS.items():
            _wc(ws, cal_row, ord(col)-ord('A')+1, '( v )' if m in months else '(   )')
        v = data.get('voltaje', {})
        if sheet_name == 'Rotary Press':
            if v.get('l1'):  _wc(ws, cal_row, 14, v['l1'])
            if v.get('vac'): _wc(ws, cal_row, 15, v['vac'])
        else:
            for col_n, key in [(14,'l1'),(15,'l2'),(16,'l3'),(17,'vac')]:
                if v.get(key):
                    _wc(ws, cal_row, col_n, v[key])

    if sig_row:
        tec = data.get('tecnico','_______________')
        fec = data.get('fecha','_______________')
        sup = data.get('supervisor','_______________')
        firma_row = sig_row + 1
        _wc(ws, sig_row, 2,  "Realizo:")
        _wc(ws, sig_row, 8,  "Fecha: " + fec)
        fecha_cell = ws.cell(row=sig_row, column=8)
        fecha_cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        fecha_cell.font = Font(bold=True, color='FFFFFF', size=11)
        fecha_cell.fill = PatternFill(fill_type='solid', fgColor='FF1A5C2A')
        _wc(ws, sig_row, 11, "Supervisor de Produccion:")

        tec_sig = data.get('sigTecnico') or {}
        sup_sig = data.get('sigSupervisor') or {}

        if isinstance(tec_sig, dict) and not tec_sig.get('nombre') and tec and tec != '_______________':
            tec_sig = dict(tec_sig); tec_sig['nombre'] = tec
        if isinstance(sup_sig, dict) and not sup_sig.get('nombre') and sup and sup != '_______________':
            sup_sig = dict(sup_sig); sup_sig['nombre'] = sup

        has_tec = isinstance(tec_sig, dict) and bool(tec_sig.get('nombre')) and bool(tec_sig.get('fecha'))
        has_sup = isinstance(sup_sig, dict) and bool(sup_sig.get('nombre')) and bool(sup_sig.get('fecha'))

        if has_tec or has_sup:
            ws.row_dimensions[firma_row].height = 70
            ws.row_dimensions[firma_row + 1].height = 0  # ocultar fila extra

        def write_pki(col, sig):
            pki_text = (sig.get('nombre','') + "\n"
                "Fecha:    " + sig.get('fecha','') + "\n"
                "Serie:    " + sig.get('serie','') + "\n"
                "Emisor:   AD-PACK Mexico")
            cell = ws.cell(row=firma_row, column=col)
            try:
                cell.value = pki_text
                cell.alignment = Alignment(wrap_text=True, vertical='top', horizontal='center')
                cell.font = Font(name='Calibri', size=10, bold=True, color='FF000000')
            except AttributeError:
                pass

        if has_tec:
            write_pki(2, tec_sig)
        if has_sup:
            write_pki(11, sup_sig)

        # --- UNIFICAR PAGE SETUP en todos los formatos ---
        last_print_row = firma_row  # no incluir fila extra
        start_print_row = 2 if sheet_name.startswith('TF') else 1
        ws.print_area = '$B${}:$Q${}'.format(start_print_row, last_print_row)
        ws.page_setup.orientation = 'portrait'
        if sheet_name == 'Rotary Press':
            ws.page_setup.fitToPage = True
            ws.page_setup.fitToHeight = 1
            ws.page_setup.fitToWidth = 1
        else:
            ws.page_setup.scale = 44
        ws.page_margins = PageMargins(
            left=0.70, right=0.70, top=0.75, bottom=0.75,
            header=0.3, footer=0.3
        )

@app.route('/api/reports', methods=['GET'])
def api_get_reports():
    con = get_db()
    rows = con.execute('SELECT data FROM reports ORDER BY id DESC').fetchall()
    con.close()
    return jsonify([json.loads(r['data']) for r in rows])

@app.route('/api/reports', methods=['POST'])
def api_save_report():
    r = request.json
    con = get_db()
    con.execute('DELETE FROM reports WHERE machine_id=? AND fecha=?', (r.get('machineId',''), r.get('fecha','')))
    con.execute('INSERT INTO reports (id, machine_id, fecha, data) VALUES (?,?,?,?)',
                (r['id'], r.get('machineId',''), r.get('fecha',''), json.dumps(r)))
    con.commit(); con.close()
    return jsonify({'ok': True})

@app.route('/api/reports/<int:report_id>', methods=['DELETE'])
def api_delete_report(report_id):
    con = get_db()
    con.execute('DELETE FROM reports WHERE id=?', (report_id,))
    con.commit(); con.close()
    return jsonify({'ok': True})
@app.route('/api/reports/export', methods=['GET'])
def api_export_reports():
    import datetime
    con = get_db()
    rows = con.execute('SELECT data FROM reports ORDER BY id DESC').fetchall()
    con.close()
    data = [json.loads(r['data']) for r in rows]
    fname = 'reportes_backup_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S') + '.json'
    resp = app.response_class(
        response=json.dumps(data, ensure_ascii=False, indent=2),
        status=200, mimetype='application/json'
    )
    resp.headers['Content-Disposition'] = f'attachment; filename="{fname}"'
    return resp

@app.route('/api/reports/import', methods=['POST'])
def api_import_reports():
    reports = request.json
    if not isinstance(reports, list):
        return jsonify({'error': 'Se esperaba una lista'}), 400
    con = get_db()
    imported = 0
    for r in reports:
        try:
            con.execute('INSERT OR IGNORE INTO reports (id, machine_id, fecha, data) VALUES (?,?,?,?)',
                        (r['id'], r.get('machineId',''), r.get('fecha',''), json.dumps(r)))
            imported += 1
        except Exception:
            pass
    con.commit(); con.close()
    return jsonify({'ok': True, 'imported': imported})


@app.route('/')
def index():
    html = open('index.html', encoding='utf-8').read()
    return html, 200, {'Content-Type':'text/html; charset=utf-8', 'Cache-Control':'no-store, no-cache, must-revalidate', 'Pragma':'no-cache'}

@app.route('/generar', methods=['POST'])
def generar():
    try:
        data = request.json
        file_key = data.get('file', 'termoformado')
        template = 'MTTO_Preventivo_Termoformado_2026.xlsx' if file_key == 'termoformado' else 'MTTO_Preventivo_Conversion_2026.xlsx'
        wb = openpyxl.load_workbook(template)
        ws = wb[data['sheet']]
        apply_checklist_data(ws, data)
        for s in [n for n in wb.sheetnames if n != ws.title]:
            del wb[s]
        buf = io.BytesIO()
        wb.save(buf); buf.seek(0)
        fname = "REPORTE_" + data.get('machineId','EQ') + "_" + data.get('fecha','').replace('/','-') + ".xlsx"
        return send_file(buf, as_attachment=True, download_name=fname,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        import traceback; traceback.print_exc()
        return {'error': str(e)}, 500

@app.route('/generar_pdf', methods=['POST'])
def generar_pdf():
    import tempfile, subprocess, shutil
    tmp_dir = tempfile.mkdtemp()
    try:
        data = request.json
        file_key = data.get('file', 'termoformado')
        template = 'MTTO_Preventivo_Termoformado_2026.xlsx' if file_key == 'termoformado' else 'MTTO_Preventivo_Conversion_2026.xlsx'
        wb = openpyxl.load_workbook(template)
        ws = wb[data['sheet']]
        apply_checklist_data(ws, data)
        for s in [s for s in wb.sheetnames if s != ws.title]:
            del wb[s]
        xlsx_path = os.path.join(tmp_dir, 'reporte.xlsx')
        wb.save(xlsx_path)
        result = subprocess.run(
            ['libreoffice', '--headless', '--convert-to', 'pdf', '--outdir', tmp_dir, xlsx_path],
            capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError("LibreOffice error: " + result.stderr)
        pdf_path = os.path.join(tmp_dir, 'reporte.pdf')
        if not os.path.exists(pdf_path):
            raise RuntimeError("PDF no generado por LibreOffice")
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
        fname = "REPORTE_" + data.get('machineId','EQ') + "_" + data.get('fecha','').replace('/','-') + ".pdf"
        return send_file(io.BytesIO(pdf_bytes), as_attachment=True, download_name=fname, mimetype='application/pdf')
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.route('/api/work-orders', methods=['GET'])
def api_get_work_orders():
    con = get_db()
    rows = con.execute('SELECT * FROM work_orders ORDER BY id DESC').fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/work-orders', methods=['POST'])
def api_save_work_order():
    data = request.json
    con = get_db()
    last = con.execute('SELECT MAX(CAST(numero AS INTEGER)) as mx FROM work_orders').fetchone()
    next_num = (last['mx'] or 257) + 1
    numero = str(next_num).zfill(4)
    con.execute(
        'INSERT INTO work_orders (numero,solicitante,fecha,equipo,planta,tipo,estatus,hora_inicio,hora_termino,'
        'tiempo_paro,descripcion_falla,actividad_realizada,refaccion,observaciones,'
        'firma_solicitante,firma_recibe,firma_liberacion,fotos) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (numero, data.get('solicitante',''), data.get('fecha',''), data.get('equipo',''),
         data.get('planta',''), data.get('tipo',''), data.get('estatus',''),
         data.get('hora_inicio',''), data.get('hora_termino',''), data.get('tiempo_paro',''),
         data.get('descripcion_falla',''), data.get('actividad_realizada',''),
         data.get('refaccion',''), data.get('observaciones',''),
         data.get('firma_solicitante',''), data.get('firma_recibe',''), data.get('firma_liberacion',''), data.get('fotos','[]'))
    )
    con.commit()
    new_id = con.execute('SELECT last_insert_rowid()').fetchone()[0]
    con.close()
    return jsonify({'ok': True, 'id': new_id, 'numero': numero})

@app.route('/api/work-orders/<int:order_id>', methods=['DELETE'])
def api_delete_work_order(order_id):
    con = get_db()
    con.execute('DELETE FROM work_orders WHERE id=?', (order_id,))
    con.commit(); con.close()
    return jsonify({'ok': True})

@app.route('/api/work-orders/next-number', methods=['GET'])
def api_next_order_number():
    con = get_db()
    last = con.execute('SELECT MAX(CAST(numero AS INTEGER)) as mx FROM work_orders').fetchone()
    next_num = (last['mx'] or 257) + 1
    con.close()
    return jsonify({'numero': str(next_num).zfill(4)})

@app.route('/version')
def version():
    return jsonify({'commit': 'a1f9c33', 'fix': 'unified_page_setup_all_formats'})


# ── PDF ORDEN DE TRABAJO ──────────────────────────────────────────
@app.route('/api/work-orders/<int:order_id>/pdf')
def api_orden_pdf(order_id):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import cm, mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfgen import canvas as pdfcanvas
    import io, json, base64

    con = get_db()
    o = con.execute('SELECT * FROM work_orders WHERE id=?',(order_id,)).fetchone()
    con.close()
    if not o: return jsonify({'error':'not found'}),404
    o = dict(o)

    buf = io.BytesIO()
    W, H = letter  # 612 x 792 pts
    c = pdfcanvas.Canvas(buf, pagesize=letter)

    GREEN = colors.HexColor('#1b5e20')
    RED   = colors.HexColor('#c62828')
    LGRAY = colors.HexColor('#f5f5f5')
    BLACK = colors.black

    margin = 1.5*cm
    w = W - 2*margin
    y = H - margin

    def line(y): c.setStrokeColor(colors.HexColor('#cccccc')); c.line(margin, y, margin+w, y)
    def chk(val, opt): return '[v]' if val==opt else '[ ]'
    def txt(t,x,yy,size=9,bold=False,color=BLACK):
        c.setFont('Helvetica-Bold' if bold else 'Helvetica', size)
        c.setFillColor(color)
        c.drawString(x,yy,str(t or ''))

    # ── BORDER ──
    c.setStrokeColor(GREEN); c.setLineWidth(2)
    c.rect(margin-2, margin-2, w+4, H-2*margin+4)

    # ── HEADER ──
    y -= 0.3*cm
    # AD-PACK box
    c.setStrokeColor(GREEN); c.setLineWidth(1.5)
    c.rect(margin+2, y-1.2*cm, 2.8*cm, 1.4*cm)
    c.setFont('Helvetica-Bold',14); c.setFillColor(GREEN)
    c.drawString(margin+8, y-0.5*cm, 'ad')
    c.setFont('Helvetica-Bold',9)
    c.drawString(margin+6, y-0.9*cm, 'AD-PACK')

    # Title
    c.setFont('Helvetica-Bold',14); c.setFillColor(GREEN)
    c.drawCentredString(W/2, y-0.3*cm, 'ORDEN DE TRABAJO PARA MANTENIMIENTO')

    # OT Number
    c.setFont('Helvetica-Bold',22); c.setFillColor(RED)
    c.drawRightString(margin+w-2, y-0.5*cm, str(o['numero']))

    y -= 1.6*cm
    c.setStrokeColor(GREEN); c.setLineWidth(1.5)
    c.line(margin, y, margin+w, y)
    y -= 0.1*cm

    # ── ROW 1: Solicitante / Fecha / Equipo ──
    y -= 0.55*cm
    txt('SOLICITANTE:', margin+2, y, 8, True)
    txt(o['solicitante'] or '', margin+2.5*cm, y, 9)
    txt('FECHA:', margin+w*0.55, y, 8, True)
    txt(o['fecha'] or '', margin+w*0.55+1.5*cm, y, 9)
    txt('EQUIPO:', margin+w*0.75, y, 8, True)
    txt(o['equipo'] or '', margin+w*0.75+1.5*cm, y, 9)
    c.setStrokeColor(LGRAY); c.line(margin, y-3, margin+w, y-3)

    # ── ROW 2: Planta / Tipo / Estatus ──
    y -= 0.7*cm
    txt('PLANTA:', margin+2, y, 8, True)
    txt(chk(o['planta'],'TERMOFORMADO')+' TERMOFORMADO', margin+1.8*cm, y, 9)
    txt(chk(o['planta'],'CONVERSIÓN')+' CONVERSIÓN', margin+5.5*cm, y, 9)
    txt('TIPO:', margin+w*0.48, y, 8, True)
    txt(chk(o['tipo'],'CORRECTIVO')+' CORRECTIVO', margin+w*0.48+1*cm, y, 9)
    txt(chk(o['tipo'],'PREVENTIVO')+' PREVENTIVO', margin+w*0.67, y, 9)
    txt('ESTATUS:', margin+w*0.83, y, 8, True)
    txt(chk(o['estatus'],'CERRADA')+' CERRADA', margin+w*0.83+1.5*cm, y, 9)
    y -= 0.4*cm
    txt(chk(o['estatus'],'ABIERTA')+' ABIERTA', margin+w*0.83+1.5*cm, y, 9)
    c.setStrokeColor(LGRAY); c.line(margin, y-3, margin+w, y-3)

    # ── ROW 3: Horas ──
    y -= 0.7*cm
    txt('HORA DE INICIO:', margin+2, y, 8, True)
    txt(o['hora_inicio'] or '_____', margin+3*cm, y, 10, True)
    txt('HORA DE TÉRMINO:', margin+w*0.35, y, 8, True)
    txt(o['hora_termino'] or '_____', margin+w*0.35+3.5*cm, y, 10, True)
    txt('TIEMPO DE PARO:', margin+w*0.67, y, 8, True)
    txt(o['tiempo_paro'] or '_____', margin+w*0.67+3*cm, y, 10, True, RED)
    c.setStrokeColor(GREEN); c.setLineWidth(1)
    y -= 0.3*cm; c.line(margin, y, margin+w, y)

    def text_box(label, value, yy, height=2.2*cm):
        c.setStrokeColor(BLACK); c.setLineWidth(0.5)
        c.rect(margin, yy-height, w, height)
        txt(label+':', margin+4, yy-0.35*cm, 8, True)
        if value:
            # wrap text
            from reportlab.pdfbase.pdfmetrics import stringWidth
            words = str(value).split()
            line_txt = ''; line_y = yy-0.7*cm; max_w = w-10
            for word in words:
                test = line_txt+(' ' if line_txt else '')+word
                if stringWidth(test,'Helvetica',9) < max_w:
                    line_txt = test
                else:
                    if line_txt: c.setFont('Helvetica',9); c.setFillColor(BLACK); c.drawString(margin+4, line_y, line_txt)
                    line_txt = word; line_y -= 0.45*cm
            if line_txt: c.setFont('Helvetica',9); c.setFillColor(BLACK); c.drawString(margin+4, line_y, line_txt)
        return yy - height - 0.2*cm

    y -= 0.1*cm
    y = text_box('DESCRIPCIÓN DE LA FALLA', o.get('descripcion_falla',''), y, 2.5*cm)
    y = text_box('ACTIVIDAD REALIZADA', o.get('actividad_realizada',''), y, 2.5*cm)
    y = text_box('REFACCIÓN UTILIZADA', o.get('refaccion',''), y, 1.8*cm)
    y = text_box('OBSERVACIONES', o.get('observaciones',''), y, 1.6*cm)

    # ── FOTOS ──
    try:
        imgs = json.loads(o.get('fotos','[]'))
        if imgs:
            y -= 0.2*cm
            txt('EVIDENCIA FOTOGRÁFICA ('+str(len(imgs))+')', margin+2, y, 8, True, GREEN)
            y -= 0.2*cm
            ix = margin
            for b64 in imgs[:5]:
                if ',' in b64: b64 = b64.split(',')[1]
                img_buf = io.BytesIO(base64.b64decode(b64))
                img = Image(img_buf, width=2.5*cm, height=2.5*cm)
                img.drawOn(c, ix, y-2.7*cm)
                ix += 2.7*cm
            y -= 3*cm
    except: pass

    # ── FIRMAS ──
    y -= 0.5*cm
    sig_w = w/3
    def draw_sig(label, data, sx):
        sd = None
        try:
            if data: sd = json.loads(data)
        except: pass
        c.setStrokeColor(BLACK); c.setLineWidth(0.8)
        c.line(sx+0.5*cm, y, sx+sig_w-0.5*cm, y)
        if sd and sd.get('nombre'):
            txt(sd['nombre'], sx+0.5*cm, y+0.15*cm, 7, True, GREEN)
            txt('✓ FIRMA ELECTRÓNICA VÁLIDA', sx+0.5*cm, y-0.35*cm, 6, False, GREEN)
            txt('CERT: '+str(sd.get('certCode','')), sx+0.5*cm, y-0.65*cm, 6)
            txt(str(sd.get('timestamp','')), sx+0.5*cm, y-0.9*cm, 6)
        c.setFont('Helvetica-Bold',8); c.setFillColor(BLACK)
        c.drawCentredString(sx+sig_w/2, y-1.3*cm, label)

    draw_sig('SOLICITANTE', o.get('firma_solicitante'), margin)
    draw_sig('RECIBE ORDEN DE TRABAJO', o.get('firma_recibe'), margin+sig_w)
    draw_sig('LIBERACIÓN DE PRODUCCIÓN', o.get('firma_liberacion'), margin+2*sig_w)

    # Footer
    c.setFont('Helvetica',7); c.setFillColor(colors.HexColor('#999999'))
    c.drawRightString(margin+w, margin+0.3*cm, 'A9.F4 Rev. 01')

    c.save()
    buf.seek(0)
    from flask import send_file
    return send_file(buf, mimetype='application/pdf',
                     download_name=f'OT-{o["numero"]}.pdf',
                     as_attachment=False)

# ══════════════════════════════════════════════════════════
#  REQUISICIONES DE COMPRA
# ══════════════════════════════════════════════════════════

def init_req_db():
    con = get_db()
    con.execute('''CREATE TABLE IF NOT EXISTS requisiciones
        (id TEXT PRIMARY KEY,
         folio INTEGER,
         fecha TEXT,
         solicitante TEXT,
         planta TEXT,
         departamento TEXT,
         tipo TEXT,
         data TEXT,
         created_at TEXT DEFAULT (datetime('now')))''')
    con.commit(); con.close()

init_req_db()

@app.route('/api/requisiciones', methods=['GET'])
def get_requisiciones():
    try:
        init_req_db()
        con = get_db()
        rows = con.execute('SELECT data FROM requisiciones ORDER BY folio DESC').fetchall()
        con.close()
        return jsonify([json.loads(r['data']) for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/requisiciones', methods=['POST'])
def save_requisicion():
    d = request.json
    con = get_db()
    if d.get('id'):
        existing = con.execute('SELECT folio FROM requisiciones WHERE id=?', (d['id'],)).fetchone()
        folio = existing['folio'] if existing else None
    else:
        folio = None
    if not folio:
        last = con.execute('SELECT MAX(folio) as m FROM requisiciones').fetchone()
        folio = (last['m'] or 0) + 1
        d['id'] = d.get('id') or (str(folio).zfill(4))
    d['folio'] = folio
    con.execute('''INSERT OR REPLACE INTO requisiciones
        (id, folio, fecha, solicitante, planta, departamento, tipo, data)
        VALUES (?,?,?,?,?,?,?,?)''',
        (d['id'], folio, d.get('fecha',''), d.get('solicitante',''),
         d.get('planta',''), d.get('departamento',''), d.get('tipo','Normal'),
         json.dumps(d, ensure_ascii=False)))
    con.commit(); con.close()
    return jsonify({'ok': True, 'id': d['id'], 'folio': folio})

@app.route('/api/requisicion/<rid>/firmar', methods=['POST'])
def firmar_requisicion(rid):
    d = request.json
    key = d.get('key')   # 'realizo', 'reviso', 'aprobo'
    firma = d.get('firma')
    if key not in ('realizo','reviso','aprobo') or not firma:
        return jsonify({'ok': False, 'error': 'Datos inválidos'}), 400
    con = get_db()
    row = con.execute('SELECT data FROM requisiciones WHERE id=?', (rid,)).fetchone()
    if not row:
        con.close()
        return jsonify({'ok': False, 'error': 'No encontrado'}), 404
    o = json.loads(row['data'])
    if 'firmas' not in o or not isinstance(o['firmas'], dict):
        o['firmas'] = {}
    o['firmas'][key] = firma
    con.execute('UPDATE requisiciones SET data=? WHERE id=?', (json.dumps(o, ensure_ascii=False), rid))
    con.commit(); con.close()
    return jsonify({'ok': True})

@app.route('/api/requisicion/<rid>/pdf')
def requisicion_pdf(rid):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.pdfgen import canvas as pdfcanvas

    con = get_db()
    row = con.execute('SELECT data FROM requisiciones WHERE id=?', (rid,)).fetchone()
    con.close()
    if not row:
        return jsonify({'error': 'No encontrado'}), 404
    o = json.loads(row['data'])

    buf = io.BytesIO()
    W, H = letter
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    margin = 1.5*cm
    w = W - 2*margin
    GREEN = colors.HexColor('#1a5c2a')
    BLACK = colors.black
    GRAY  = colors.HexColor('#888888')
    LGRAY = colors.HexColor('#cccccc')

    def txt(t, x, yy, size=8, bold=False, color=BLACK, align='left'):
        c.setFont('Helvetica-Bold' if bold else 'Helvetica', size)
        c.setFillColor(color)
        if align == 'center':
            c.drawCentredString(x, yy, str(t or ''))
        elif align == 'right':
            c.drawRightString(x, yy, str(t or ''))
        else:
            c.drawString(x, yy, str(t or ''))

    y = H - margin

    # ── LOGO ──
    c.setStrokeColor(GREEN); c.setLineWidth(1.5)
    c.rect(margin, y-1.2*cm, 2.5*cm, 1.3*cm)
    c.setFont('Helvetica-Bold', 14); c.setFillColor(GREEN)
    c.drawString(margin+4, y-0.5*cm, 'ad')
    c.setFont('Helvetica-Bold', 8); c.setFillColor(GREEN)
    c.drawString(margin+4, y-0.9*cm, 'AD-PACK')

    # ── TITLE ──
    c.setFont('Helvetica-Bold', 13); c.setFillColor(BLACK)
    c.drawCentredString(W/2, y-0.35*cm, 'Requisición de compra')

    # ── DOC INFO top-right ──
    folio = str(o.get('folio', '')).zfill(4)
    bx = margin + w - 4.5*cm
    c.setStrokeColor(LGRAY); c.setLineWidth(0.5)
    c.rect(bx, y-1.2*cm, 4.5*cm, 1.3*cm)
    c.line(bx, y-0.4*cm, bx+4.5*cm, y-0.4*cm)
    c.line(bx+2.2*cm, y-1.2*cm, bx+2.2*cm, y)
    txt('No. de Documento', bx+4, y-0.15*cm, 6, True)
    txt('Revisión', bx+2.2*cm+4, y-0.15*cm, 6, True)
    txt('REQ-' + folio, bx+4, y-0.75*cm, 9, True, GREEN)
    txt(o.get('fecha', ''), bx+2.2*cm+4, y-0.75*cm, 7)

    y -= 1.4*cm

    # ── ROW 1: Fecha / Solicitante / Planta / Depto ──
    c.setStrokeColor(LGRAY); c.setLineWidth(0.5)
    row_h = 0.55*cm
    c.rect(margin, y-row_h, w, row_h)
    cols = [2.5*cm, w*0.35, w*0.55, w*0.75]
    for cx in cols:
        c.line(margin+cx, y, margin+cx, y-row_h)
    txt('FECHA:', margin+4, y-row_h+4, 7, True)
    txt(o.get('fecha',''), margin+1.2*cm, y-row_h+4, 7)
    txt('SOLICITANTE:', margin+cols[0]+4, y-row_h+4, 7, True)
    txt(o.get('solicitante',''), margin+cols[0]+2.3*cm, y-row_h+4, 7)
    txt('PLANTA:', margin+cols[1]+4, y-row_h+4, 7, True)
    txt(o.get('planta',''), margin+cols[1]+1.4*cm, y-row_h+4, 7)
    txt('DEPARTAMENTO:', margin+cols[2]+4, y-row_h+4, 7, True)
    txt(o.get('departamento',''), margin+cols[2]+2.5*cm, y-row_h+4, 7)

    y -= row_h

    # ── ROW 2: Tipo solicitud ──
    c.rect(margin, y-row_h, w, row_h)
    c.line(margin+w*0.55, y, margin+w*0.55, y-row_h)
    tipo = o.get('tipo', 'Normal')
    txt('TIPO DE SOLICITUD:', margin+4, y-row_h+4, 7, True)
    txt('[v]' if tipo=='Normal' else '[ ]', margin+3.8*cm, y-row_h+4, 7)
    txt('Normal', margin+4.4*cm, y-row_h+4, 7)
    txt('[v]' if tipo=='Urgente' else '[ ]', margin+5.5*cm, y-row_h+4, 7)
    txt('Urgente', margin+6.1*cm, y-row_h+4, 7, False, colors.HexColor('#c62828'))

    y -= row_h + 0.1*cm

    # ── TABLE HEADER ──
    col_widths = [0.55*cm, 1.4*cm, 1.5*cm, 4.5*cm, 3.0*cm, 3.2*cm, 3.3*cm]
    # adjust last col to fill width
    col_widths[-1] = w - sum(col_widths[:-1])
    col_x = [margin]
    for cw in col_widths[:-1]:
        col_x.append(col_x[-1] + cw)

    hdr_h = 1.0*cm
    c.setFillColor(colors.HexColor('#e8f5e9'))
    c.rect(margin, y-hdr_h, w, hdr_h, fill=1, stroke=1)
    c.setStrokeColor(LGRAY)
    for cx in col_x[1:]:
        c.line(cx, y, cx, y-hdr_h)

    headers = ['#','CANTIDAD','UNIDAD\n(pieza,caja,\nmetros,litros,\nrollos etc.)','DESCRIPCIÓN\n(nombre,modelo,marca,\nNo.catálogo,color,medidas)','APLICACIÓN\nO USO','PROVEEDOR SUGERIDO\n(nombre,contacto,\ntelefono/correo)','PROVEEDOR ALTERNO\n(nombre,contacto,\ntelefono/correo)']
    c.setFont('Helvetica-Bold', 6); c.setFillColor(BLACK)
    for i, (htext, cx, cw) in enumerate(zip(headers, col_x, col_widths)):
        lines = htext.split('\n')
        ly = y - 0.15*cm
        for ln in lines:
            c.drawCentredString(cx + cw/2, ly, ln)
            ly -= 0.22*cm

    y -= hdr_h

    # ── TABLE ROWS (10 items) ──
    items = o.get('items', [{}]*10)
    while len(items) < 10:
        items.append({})

    row_h_item = 0.7*cm
    for idx, item in enumerate(items[:10]):
        ry = y - row_h_item
        if idx % 2 == 0:
            c.setFillColor(colors.HexColor('#fafffe'))
        else:
            c.setFillColor(colors.white)
        c.rect(margin, ry, w, row_h_item, fill=1, stroke=0)
        c.setStrokeColor(LGRAY); c.setLineWidth(0.4)
        c.rect(margin, ry, w, row_h_item, fill=0, stroke=1)
        for cx in col_x[1:]:
            c.line(cx, y, cx, ry)

        c.setFont('Helvetica', 7); c.setFillColor(BLACK)
        cy = ry + row_h_item*0.35
        c.drawCentredString(col_x[0]+col_widths[0]/2, cy, str(idx+1))
        c.drawCentredString(col_x[1]+col_widths[1]/2, cy, str(item.get('cantidad','')))
        c.drawCentredString(col_x[2]+col_widths[2]/2, cy, str(item.get('unidad','')))
        c.drawString(col_x[3]+3, cy, str(item.get('descripcion',''))[:55])
        c.drawString(col_x[4]+3, cy, str(item.get('aplicacion',''))[:30])
        c.drawString(col_x[5]+3, cy, str(item.get('proveedor',''))[:28])
        c.drawString(col_x[6]+3, cy, str(item.get('proveedor_alt',''))[:28])
        y -= row_h_item

    y -= 0.2*cm

    # ── JUSTIFICACIÓN ──
    c.setStrokeColor(LGRAY); c.setLineWidth(0.5)
    just_h = 2.0*cm
    c.rect(margin, y-just_h, w, just_h)
    txt('JUSTIFICACIÓN (necesidad de la compra del material):', margin+4, y-0.25*cm, 7, True)
    just_txt = o.get('justificacion', '')
    c.setFont('Helvetica', 8); c.setFillColor(BLACK)
    # wrap text
    words = just_txt.split()
    line_txt = ''; ly = y - 0.55*cm; max_w = w - 10
    from reportlab.pdfbase.pdfmetrics import stringWidth
    for word in words:
        test = line_txt + (' ' if line_txt else '') + word
        if stringWidth(test, 'Helvetica', 8) < max_w:
            line_txt = test
        else:
            if line_txt: c.drawString(margin+4, ly, line_txt)
            line_txt = word; ly -= 0.35*cm
    if line_txt: c.drawString(margin+4, ly, line_txt)

    y -= just_h + 0.5*cm

    # ── FIRMAS ──
    sig_w = w / 3
    firmas = o.get('firmas', {})
    labels = ['Realizó (Nombre y firma)', 'Revisó (Nombre y firma)', 'Aprobó (Nombre y firma)']
    keys   = ['realizo', 'reviso', 'aprobo']
    for i, (label, key) in enumerate(zip(labels, keys)):
        sx = margin + i * sig_w
        c.setStrokeColor(BLACK); c.setLineWidth(0.8)
        c.line(sx+0.5*cm, y, sx+sig_w-0.5*cm, y)
        sig = firmas.get(key, {})
        if isinstance(sig, dict) and sig.get('nombre'):
            c.setFont('Helvetica-Bold', 7); c.setFillColor(GREEN)
            c.drawString(sx+0.5*cm, y+0.15*cm, sig.get('nombre',''))
            c.setFont('Helvetica', 6); c.setFillColor(GREEN)
            c.drawString(sx+0.5*cm, y-0.3*cm, '[v] FIRMA ELECTRONICA VALIDA')
        c.setFont('Helvetica-Bold', 7); c.setFillColor(BLACK)
        c.drawCentredString(sx+sig_w/2, y-1.1*cm, label)

    # Footer
    c.setFont('Helvetica', 6); c.setFillColor(GRAY)
    c.drawRightString(margin+w, margin+0.3*cm, 'A9.F5 Rev. 01')

    c.save(); buf.seek(0)
    return send_file(buf, mimetype='application/pdf',
                     download_name=f'REQ-{folio}.pdf',
                     as_attachment=False)


@app.route('/api/refacciones', methods=['GET'])
def api_get_refacciones():
    con = get_db()
    rows = con.execute('SELECT * FROM refacciones ORDER BY seccion, nombre').fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/refacciones', methods=['POST'])
def api_create_refaccion():
    d = request.json
    con = get_db()
    con.execute("INSERT INTO refacciones (nombre,descripcion,marca,modelo,categoria,criticidad,seccion,cant_min,stock_actual,tiempo_entrega,proveedor,ubicacion,costo,notas,foto_b64) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (d.get('nombre',''),d.get('descripcion',''),d.get('marca',''),d.get('modelo',''),
         d.get('categoria',''),d.get('criticidad','MEDIA'),d.get('seccion',''),
         int(d.get('cant_min',1)),int(d.get('stock_actual',0)),
         d.get('tiempo_entrega',''),d.get('proveedor',''),d.get('ubicacion',''),
         float(d.get('costo',0)),d.get('notas',''),d.get('foto_b64','')))
    con.commit()
    new_id = con.execute('SELECT last_insert_rowid()').fetchone()[0]
    con.close()
    return jsonify({'ok': True, 'id': new_id})

@app.route('/api/refacciones/<int:ref_id>', methods=['PUT'])
def api_update_refaccion(ref_id):
    d = request.json
    con = get_db()
    con.execute("UPDATE refacciones SET nombre=?,descripcion=?,marca=?,modelo=?,categoria=?,criticidad=?,seccion=?,cant_min=?,stock_actual=?,tiempo_entrega=?,proveedor=?,ubicacion=?,costo=?,notas=?,foto_b64=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (d.get('nombre',''),d.get('descripcion',''),d.get('marca',''),d.get('modelo',''),
         d.get('categoria',''),d.get('criticidad','MEDIA'),d.get('seccion',''),
         int(d.get('cant_min',1)),int(d.get('stock_actual',0)),
         d.get('tiempo_entrega',''),d.get('proveedor',''),d.get('ubicacion',''),
         float(d.get('costo',0)),d.get('notas',''),d.get('foto_b64',''),ref_id))
    con.commit()
    con.close()
    return jsonify({'ok': True})

@app.route('/api/refacciones/<int:ref_id>', methods=['DELETE'])
def api_delete_refaccion(ref_id):
    con = get_db()
    con.execute('DELETE FROM refacciones WHERE id=?', (ref_id,))
    con.commit()
    con.close()
    return jsonify({'ok': True})


@app.route('/api/refacciones/export/excel', methods=['GET'])
def export_refacciones_excel():
    con = get_db()
    rows = con.execute('SELECT * FROM refacciones ORDER BY seccion, nombre').fetchall()
    con.close()

    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from datetime import date

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Refacciones"

    GREEN_DARK  = PatternFill("solid", fgColor="1F5C2E")
    GREEN_MED   = PatternFill("solid", fgColor="2E7D32")
    GREEN_LIGHT = PatternFill("solid", fgColor="C8E6C9")
    GRAY_LIGHT  = PatternFill("solid", fgColor="F5F5F5")
    RED_FILL    = PatternFill("solid", fgColor="C62828")
    ORG_FILL    = PatternFill("solid", fgColor="E65100")
    GREEN_FILL  = PatternFill("solid", fgColor="2E7D32")
    thin = Side(style="thin", color="BDBDBD")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    # Title row
    ws.merge_cells("A1:M1")
    ws["A1"] = "LISTA DE REFACCIONES  —  ALMACÉN MANTENIMIENTO  |  AD-PACK  Termoformado"
    ws["A1"].font = Font(bold=True, color="FFFFFF", size=13)
    ws["A1"].fill = GREEN_DARK
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    # Subtitle row
    ws.merge_cells("A2:D2"); ws["A2"] = f"Área:  Mantenimiento / Termoformado"
    ws.merge_cells("E2:H2"); ws["E2"] = "Responsable:  _________________"
    ws.merge_cells("I2:J2"); ws["I2"] = "Revisión:  00"
    ws.merge_cells("K2:M2"); ws["K2"] = f"Fecha:  {date.today()}"
    for cell in ["A2","E2","I2","K2"]:
        ws[cell].font = Font(bold=True, size=9, color="FFFFFF")
        ws[cell].fill = GREEN_MED
        ws[cell].alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[2].height = 18

    # Header row
    headers = ["#","REFACCION / DESCRIPCION","MARCA","MODELO","CATEGORIA","CRITICIDAD","SECCION","CANT.MIN.","STOCK ACT.","T. ENTREGA","PROVEEDOR","UBICACION ALMACEN"]
    col_w   = [5, 38, 18, 16, 14, 12, 20, 7, 7, 12, 22, 22]
    for i, (h, w) in enumerate(zip(headers, col_w), 1):
        c = ws.cell(row=3, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF", size=9)
        c.fill = GREEN_MED
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = border
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[3].height = 30

    # Group by section
    sections = {}
    for r in rows:
        sec = r["seccion"] or "Sin sección"
        sections.setdefault(sec, []).append(r)

    row_num = 4
    num = 1
    for sec, items in sections.items():
        # Section header
        ws.merge_cells(f"A{row_num}:M{row_num}")
        ws[f"A{row_num}"] = f"  ▌ {sec.upper()}"
        ws[f"A{row_num}"].font = Font(bold=True, color="FFFFFF", size=10)
        ws[f"A{row_num}"].fill = GREEN_MED
        ws[f"A{row_num}"].alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[row_num].height = 18
        row_num += 1

        for r in items:
            fill = GRAY_LIGHT if num % 2 == 0 else PatternFill("solid", fgColor="FFFFFF")
            crit = r["criticidad"] or "MEDIA"
            crit_fill = RED_FILL if crit=="ALTA" else (ORG_FILL if crit=="MEDIA" else GREEN_FILL)

            vals = [num, r["nombre"], r["marca"] or "", r["modelo"] or "",
                    r["categoria"] or "", crit, r["seccion"] or "",
                    r["cant_min"], r["stock_actual"],
                    r["tiempo_entrega"] or "", r["proveedor"] or "",
                    r["ubicacion"] or ""]

            for col, val in enumerate(vals, 1):
                cell = ws.cell(row=row_num, column=col, value=val)
                cell.border = border
                cell.font = Font(size=9)
                cell.alignment = Alignment(vertical="center", wrap_text=True,
                                           horizontal="center" if col in [1,8,9] else "left")
                if col == 6:
                    cell.fill = crit_fill
                    cell.font = Font(bold=True, color="FFFFFF", size=9)
                else:
                    cell.fill = fill

            # Stock bajo warning
            if r["stock_actual"] <= r["cant_min"]:
                ws.cell(row=row_num, column=9).font = Font(bold=True, color="C62828", size=9)

            ws.row_dimensions[row_num].height = 16
            row_num += 1
            num += 1

    # Footer
    ws.merge_cells(f"A{row_num}:M{row_num}")
    ws[f"A{row_num}"] = "  🔴 ALTA = Paro de producción    |    🟡 MEDIA = Afecta eficiencia    |    🟢 BAJA = Preventivo"
    ws[f"A{row_num}"].font = Font(italic=True, size=8, color="555555")
    ws[f"A{row_num}"].fill = GREEN_LIGHT

    ws.freeze_panes = "A4"

    buf = io.BytesIO()
    wb.save(buf); buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name=f"Lista_Refacciones_{date.today()}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route('/api/refacciones/export/pdf', methods=['GET'])
def export_refacciones_pdf():
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from datetime import date

    con = get_db()
    rows = con.execute('SELECT * FROM refacciones ORDER BY seccion, nombre').fetchall()
    con.close()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=8*mm, rightMargin=8*mm,
                            topMargin=8*mm, bottomMargin=8*mm)

    GREEN_DARK  = colors.HexColor('#1F5C2E')
    GREEN_MED   = colors.HexColor('#2E7D32')
    GREEN_LIGHT = colors.HexColor('#C8E6C9')
    RED   = colors.HexColor('#C62828')
    ORG   = colors.HexColor('#E65100')
    GRAY  = colors.HexColor('#F5F5F5')
    WHITE = colors.white

    def ps(size=7, bold=False, color=colors.black, align=TA_LEFT):
        return ParagraphStyle('x', fontSize=size, leading=size+2,
                              fontName='Helvetica-Bold' if bold else 'Helvetica',
                              textColor=color, alignment=align)

    crit_col = {'ALTA': RED, 'MEDIA': ORG, 'BAJA': GREEN_MED}
    CW = [7*mm,65*mm,22*mm,18*mm,16*mm,16*mm,10*mm,10*mm,14*mm,28*mm,30*mm]

    sections = {}
    for r in rows:
        sections.setdefault(r['seccion'] or 'Sin seccion', []).append(r)

    story = []

    # ---- Titulo ----
    t = Table([[Paragraph('LISTA DE REFACCIONES — ALMACÉN MANTENIMIENTO | AD-PACK Termoformado',
                          ps(12, True, WHITE, TA_CENTER))]],
              colWidths=[sum(CW)])
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),GREEN_DARK),
                           ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
    story.append(t)

    s = Table([[f'Área: Mantenimiento / Termoformado',
                'Responsable: _________________',
                f'Revisión: 00   |   Fecha: {date.today()}']],
              colWidths=[sum(CW)//3, sum(CW)//3, sum(CW)-2*(sum(CW)//3)])
    s.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),GREEN_MED),
                           ('TEXTCOLOR',(0,0),(-1,-1),WHITE),
                           ('FONTSIZE',(0,0),(-1,-1),7.5),
                           ('FONTNAME',(0,0),(-1,-1),'Helvetica-Bold'),
                           ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)]))
    story.append(s)
    story.append(Spacer(1,2*mm))

    num = 1
    HDRS = ['#','REFACCION / DESCRIPCION','MARCA','MODELO','CATEGORIA','CRITICIDAD',
            'MIN','STOCK','ENTREGA','PROVEEDOR','UBICACION ALMACEN']

    for sec, items in sections.items():
        sh = Table([[Paragraph(f'  ▌ {sec.upper()}', ps(8, True, WHITE))]], colWidths=[sum(CW)])
        sh.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),GREEN_MED),
                                ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)]))
        story.append(sh)

        tdata = [[Paragraph(h, ps(7,True,WHITE,TA_CENTER)) for h in HDRS]]
        tstyle = [
            ('BACKGROUND',(0,0),(-1,0),GREEN_MED),
            ('GRID',(0,0),(-1,-1),0.3,colors.HexColor('#BDBDBD')),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('TOPPADDING',(0,0),(-1,-1),2),('BOTTOMPADDING',(0,0),(-1,-1),2),
        ]

        for i, r in enumerate(items, 1):
            low = r['stock_actual'] <= r['cant_min']
            cc  = crit_col.get(r['criticidad'] or 'MEDIA', ORG)
            bg  = GRAY if i % 2 == 0 else WHITE
            tdata.append([
                Paragraph(str(num),           ps(7,align=TA_CENTER)),
                Paragraph(str(r['nombre'] or ''),     ps(7)),
                Paragraph(str(r['marca'] or ''),      ps(7)),
                Paragraph(str(r['modelo'] or ''),     ps(7)),
                Paragraph(str(r['categoria'] or ''),  ps(7)),
                Paragraph(str(r['criticidad'] or ''), ps(7,True,WHITE,TA_CENTER)),
                Paragraph(str(r['cant_min']),          ps(7,align=TA_CENTER)),
                Paragraph(str(r['stock_actual']),      ps(7,bold=low,color=RED if low else colors.black,align=TA_CENTER)),
                Paragraph(str(r['tiempo_entrega'] or ''), ps(7)),
                Paragraph(str(r['proveedor'] or ''),   ps(7)),
                Paragraph(str(r['ubicacion'] or ''),   ps(7)),
            ])
            tstyle += [('BACKGROUND',(0,i),(-1,i),bg),
                       ('BACKGROUND',(5,i),(5,i),cc)]
            num += 1

        dt = Table(tdata, colWidths=CW, repeatRows=1)
        dt.setStyle(TableStyle(tstyle))
        story.append(dt)
        story.append(Spacer(1,2*mm))

    # Footer
    ft = Table([[Paragraph('🔴 ALTA = Paro producción  |  🟡 MEDIA = Afecta eficiencia  |  🟢 BAJA = Preventivo  |  Stock rojo = bajo mínimo',
                            ps(6, color=colors.HexColor('#555555')))]],
               colWidths=[sum(CW)])
    ft.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),GREEN_LIGHT),
                            ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)]))
    story.append(ft)

    doc.build(story)
    buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name=f"Lista_Refacciones_{date.today()}.pdf",
                     mimetype='application/pdf')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 3000)), debug=False)
