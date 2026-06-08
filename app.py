import os, io, base64, sqlite3, json
from flask import Flask, request, send_file, jsonify

DB_PATH = os.path.join(os.path.dirname(__file__), 'reports.db')

def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_db()
    con.execute('''CREATE TABLE IF NOT EXISTS reports
                   (id INTEGER PRIMARY KEY, machine_id TEXT, fecha TEXT, data TEXT)''')
    con.commit(); con.close()

init_db()

try:
    import openpyxl
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.utils import get_column_letter
    from PIL import Image as PILImage
except ImportError:
    os.system("pip install openpyxl Pillow -q")
    import openpyxl
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.utils import get_column_letter
    from PIL import Image as PILImage

app = Flask(__name__)
EMU = 9525  # 1 pixel = 9525 EMU

MONTH_COLS = {"ENE":"B","FEB":"C","MAR":"D","ABR":"E","MAY":"F","JUN":"G",
              "JUL":"H","AGO":"I","SEP":"J","OCT":"K","NOV":"L","DIC":"M"}

def make_sig_image(b64_str, width_px, height_px):
    if not b64_str:
        return None
    try:
        if ',' in b64_str:
            b64_str = b64_str.split(',')[1]
        raw = base64.b64decode(b64_str)
        pil = PILImage.open(io.BytesIO(raw)).convert("RGBA")
        # Mantener fondo transparente — NO componer sobre blanco
        pil = pil.resize((width_px, height_px), PILImage.LANCZOS)
        buf = io.BytesIO()
        pil.save(buf, format='PNG')
        buf.seek(0)
        img = XLImage(buf)
        img.width = width_px
        img.height = height_px
        return img
    except Exception as e:
        print(f"Img error: {e}")
        return None

def add_sig_anchored(ws, b64_str, col_idx, row_idx, y_offset_px=0, width_px=170, height_px=50):
    """Add signature image anchored to a cell reference (col_idx 0-based, row_idx 0-based)"""
    img = make_sig_image(b64_str, width_px, height_px)
    if not img:
        return
    # Convertir a referencia de celda estilo Excel, ej. "D46"
    col_letter = get_column_letter(col_idx + 1)   # 0-based → 1-based → letra
    excel_row  = row_idx + 1                       # 0-based → 1-based
    img.anchor = f"{col_letter}{excel_row}"
    ws.add_image(img)

@app.route('/')
def index():
    return open('index.html', encoding='utf-8').read(), 200, {'Content-Type':'text/html; charset=utf-8'}

# ── API REPORTES (guardado en servidor) ──────────────────────

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
    # Reemplazar si ya existe misma máquina + fecha
    con.execute('DELETE FROM reports WHERE machine_id=? AND fecha=?',
                (r.get('machineId',''), r.get('fecha','')))
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

@app.route('/generar', methods=['POST'])
def generar():
    try:
        data = request.json
        file_key = data.get('file', 'termoformado')
        template = 'MTTO_Preventivo_Termoformado_2026.xlsx' if file_key=='termoformado' else 'MTTO_Preventivo_Conversion_2026.xlsx'

        wb = openpyxl.load_workbook(template)
        ws = wb[data['sheet']]

        # Fill checklist
        for item in data.get('items', []):
            row, st, cm = item['row'], item.get('status',''), item.get('comment','')
            ws.cell(row=row, column=11).value = '( ✓ )' if st=='ok' else '(   )'
            ws.cell(row=row, column=12).value = '( ✓ )' if st=='ng' else '(   )'
            if cm: ws.cell(row=row, column=13).value = cm

        # Fill calendar
        cal_row = data.get('cal_data_row')
        months  = set(data.get('month', []))
        if cal_row:
            for m, col in MONTH_COLS.items():
                ws.cell(row=cal_row, column=ord(col)-ord('A')+1).value = '( ✓ )' if m in months else '(   )'
            v = data.get('voltaje', {})
            for col_n, key in [(14,'l1'),(15,'l2'),(16,'l3'),(17,'vac')]:
                if v.get(key): ws.cell(row=cal_row, column=col_n).value = v[key]

        # Signature row
        sig_row = data.get('sig_row')
        if sig_row:
            tec = data.get('tecnico','_______________')
            fec = data.get('fecha','_______________')
            sup = data.get('supervisor','_______________')

            # sig_row (del JS) = fila "Realizó:"
            # firma_row       = sig_row + 1 = fila "Firma:" (celda combinada B:G y K:Q)
            firma_row = sig_row + 1
            ws.cell(row=sig_row, column=2).value  = f"Realizó: {tec}"
            ws.cell(row=sig_row, column=8).value  = f"Fecha: {fec}"
            ws.cell(row=sig_row, column=11).value = f"Supervisor de Producción: {sup}"

            # Firma técnico → celda combinada B:G (col B=idx 1), 560x60 px
            tec_sig = data.get('sigTecnicoImg')
            if tec_sig:
                add_sig_anchored(ws, tec_sig,
                    col_idx=1,              # Columna B — inicio de celda combinada 