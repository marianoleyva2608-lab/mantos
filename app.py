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
    con.commit(); con.close()

def init_users_db():
    con = get_db()
    con.execute('''CREATE TABLE IF NOT EXISTS users
        (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL,
         email TEXT NOT NULL UNIQUE, pin_hash TEXT NOT NULL,
         created_at TEXT DEFAULT (datetime('now')))''')
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

@app.route('/api/users', methods=['GET'])
def list_users():
    con = get_db()
    rows = con.execute('SELECT id, nombre, email, created_at FROM users ORDER BY nombre').fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

try:
    import openpyxl
    from openpyxl.utils import get_column_letter
    from openpyxl.styles import Alignment, Font
except ImportError:
    os.system("pip install openpyxl -q")
    import openpyxl
    from openpyxl.utils import get_column_letter
    from openpyxl.styles import Alignment, Font

MONTH_COLS = {"ENE":"B","FEB":"C","MAR":"D","ABR":"E","MAY":"F","JUN":"G",
              "JUL":"H","AGO":"I","SEP":"J","OCT":"K","NOV":"L","DIC":"M"}

def _wc(ws, row, col, value, alignment=None):
    """Escribe en celda solo si es top-left (no MergedCell)."""
    cell = ws.cell(row=row, column=col)
    try:
        cell.value = value
    except AttributeError:
        return  # MergedCell de solo lectura — saltar
    if alignment:
        cell.alignment = alignment

def apply_checklist_data(ws, data):
    # Row limits from known templates — override any stale value in saved reports
    SHEET_SIG = {
        'TF 1':45,'TF 2':45,'TF 3':45,'TF 4':45,'TF 5':45,'TF 6':45,'TF 7':45,
        'prensa 1':40,'Prensa 2':40,
        'Suajadora 1':26,'Suajadora 2':26,'Suajadora 5':26,'TCU':26,'Chiller':27,
        'Laminator':37,'Slitter Rewinder':37,'Komatsu OBS45':32,
        'Rotary Press':37,'Prensa PL':32,'IMESA':31,'Single Knife':31,
        'Hojeadora Robust':31,'Gapcutter':30,
    }
    sheet_name = data.get('sheet', '')
    sig_row = SHEET_SIG.get(sheet_name) or data.get('sig_row')
    cal_row  = data.get('cal_data_row')
    # Guard: don't write items into calendar/firma rows
    max_item_row = (sig_row - 1) if sig_row else 9999

    for item in data.get('items', []):
        row, st, cm = item['row'], item.get('status',''), item.get('comment','')
        if row > max_item_row:
            continue  # skip stale items from old checklists
        _wc(ws, row, 11, '( v )' if st == 'ok' else '(   )')
        _wc(ws, row, 12, '( v )' if st == 'ng' else '(   )')
        if cm:
            _wc(ws, row, 13, cm)

    months = set(data.get('month', []))
    if cal_row:
        for m, col in MONTH_COLS.items():
            _wc(ws, cal_row, ord(col)-ord('A')+1, '( v )' if m in months else '(   )')
        v = data.get('voltaje', {})
        for col_n, key in [(14,'l1'),(15,'l2'),(16,'l3'),(17,'vac')]:
            if v.get(key):
                _wc(ws, cal_row, col_n, v[key])

    if sig_row:
        tec = data.get('tecnico','_______________')
        fec = data.get('fecha','_______________')
        sup = data.get('supervisor','_______________')
        firma_row = sig_row + 1
        _wc(ws, sig_row, 2,  "Realizo: " + tec)
        _wc(ws, sig_row, 8,  "Fecha: " + fec)
        _wc(ws, sig_row, 11, "Supervisor de Produccion: " + sup)

        tec_sig = data.get('sigTecnico') or {}
        sup_sig = data.get('sigSupervisor') or {}

        # Fallback: use plain tecnico/supervisor name if PKI nombre is missing
        if isinstance(tec_sig, dict) and not tec_sig.get('nombre') and tec:
            tec_sig = dict(tec_sig); tec_sig['nombre'] = tec
        if isinstance(sup_sig, dict) and not sup_sig.get('nombre') and sup:
            sup_sig = dict(sup_sig); sup_sig['nombre'] = sup

        has_tec = isinstance(tec_sig, dict) and bool(tec_sig.get('nombre')) and bool(tec_sig.get('fecha'))
        has_sup = isinstance(sup_sig, dict) and bool(sup_sig.get('nombre')) and bool(sup_sig.get('fecha'))

        if has_tec or has_sup:
            ws.row_dimensions[firma_row].height = 130
            ws.row_dimensions[firma_row + 1].height = 20

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

@app.route('/')
def index():
    return open('index.html', encoding='utf-8').read(), 200, {'Content-Type':'text/html; charset=utf-8'}

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
        result = subproce