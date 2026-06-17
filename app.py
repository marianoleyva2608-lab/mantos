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
        'Laminator':37,'Slitter Rewinder':37,'Komatsu OBS45':32,
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
        fecha_cell.fill = PatternFill(fill_type='solid', fgColor='1a5c2a')
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
        ws.page_setup.fitToPage = True
        ws.page_setup.fitToHeight = 1
        ws.page_setup.fitToWidth = 1
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
    def chk(val, opt): return '☑' if val==opt else '☐'
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 3000)), debug=False)
                                                                                                        