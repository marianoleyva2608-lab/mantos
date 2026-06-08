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
    con.commit()
    con.close()

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
EMU = 9525

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

def add_sig_anchored(ws, b64_str, col_idx, row_idx, width_px=170, height_px=50):
    img = make_sig_image(b64_str, width_px, height_px)
    if not img:
        return
    col_letter = get_column_letter(col_idx + 1)
    excel_row = row_idx + 1
    img.anchor = f"{col_letter}{excel_row}"
    ws.add_image(img)

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
    con.execute('DELETE FROM reports WHERE machine_id=? AND fecha=?',
                (r.get('machineId',''), r.get('fecha','')))
    con.execute('INSERT INTO reports (id, machine_id, fecha, data) VALUES (?,?,?,?)',
                (r['id'], r.get('machineId',''), r.get('fecha',''), json.dumps(r)))
    con.commit()
    con.close()
    return jsonify({'ok': True})

@app.route('/api/reports/<int:report_id>', methods=['DELETE'])
def api_delete_report(report_id):
    con = get_db()
    con.execute('DELETE FROM reports WHERE id=?', (report_id,))
    con.commit()
    con.close()
    return jsonify({'ok': True})

@app.route('/')
def index():
    return open('index.html', encoding='utf-8').read(), 200, {'Content-Type':'text/html; charset=utf-8'}

@app.route('/generar', methods=['POST'])
def generar():
    try:
        data = request.json
        file_key = data.get('file', 'termoformado')
        template = 'MTTO_Preventivo_Termoformado_2026.xlsx' if file_key=='termoformado' else 'MTTO_Preventivo_Conversion_2026.xlsx'

        wb = openpyxl.load_workbook(template)
        ws = wb[data['sheet']]

        for item in data.get('items', []):
            row, st, cm = item['row'], item.get('status',''), item.get('comment','')
            ws.cell(row=row, column=11).value = '( v )' if st=='ok' else '(   )'
            ws.cell(row=row, column=12).value = '( v )' if st=='ng' else '(   )'
            if cm:
                ws.cell(row=row, column=13).value = cm

        cal_row = data.get('cal_data_row')
        months = set(data.get('month', []))
        if cal_row:
            for m, col in MONTH_COLS.items():
                ws.cell(row=cal_row, column=ord(col)-ord('A')+1).value = '( v )' if m in months else '(   )'
            v = data.get('voltaje', {})
            for col_n, key in [(14,'l1'),(15,'l2'),(16,'l3'),(17,'vac')]:
                if v.get(key):
                    ws.cell(row=cal_row, column=col_n).value = v[key]

        sig_row = data.get('sig_row')
        if sig_row:
            tec = data.get('tecnico', '_______________')
            fec = data.get('fecha',   '_______________')
            sup = data.get('supervisor', '_______________')
            firma_row = sig_row + 1

            ws.cell(row=sig_row, column=2).value  = f"Realizo: {tec}"
            ws.cell(row=sig_row, column=8).value  = f"Fecha: {fec}"
            ws.cell(row=sig_row, column=11).value = f"Supervisor de Produccion: {sup}"

            tec_sig = data.get('sigTecnicoImg')
            if tec_sig:
                add_sig_anchored(ws, tec_sig, col_idx=1, row_idx=firma_row-1, width_px=560, height_px=60)

            sup_sig = data.get('sigSupervisorImg')
            if sup_sig:
                add_sig_anchored(ws, sup_sig, col_idx=10, row_idx=firma_row-1, width_px=660, height_px=60)

        sup_comments = data.get('supComments', '')
        if sup_comments and sig_row:
            ws.cell(row=sig_row+2, column=2).value = f"Comentarios: {sup_comments}"

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        fname = f"REPORTE_{data.get('machineId','EQ')}_{data.get('fecha','').replace('/','-')}.xlsx"
        return send_file(buf, as_attachment=True, download_name=fname,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        import traceback; traceback.print_exc()
        return {'error': str(e)}, 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',3000)), debug=False)


@app.route('/generar_pdf', methods=['POST'])
def generar_pdf():
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.platypus import Image as RLImage

        data   = request.json
        buf    = io.BytesIO()
        doc    = SimpleDocTemplate(buf, pagesize=landscape(A4),
                                   leftMargin=10*mm, rightMargin=10*mm,
                                   topMargin=10*mm, bottomMargin=10*mm)
        W = landscape(A4)[0] - 20*mm

        GREEN  = colors.HexColor('#1a5c2a')
        LGREEN = colors.HexColor('#e8f5e9')
        GRAY   = colors.HexColor('#f5f5f5')
        RED    = colors.HexColor('#c62828')
        WHITE  = colors.white

        def sty(size=8, bold=False, color=colors.black, align=TA_LEFT, bg=None):
            return ParagraphStyle('x', fontSize=size,
                                  fontName='Helvetica-Bold' if bold else 'Helvetica',
                                  textColor=color, alignment=align)

        story = []

        # ── HEADER ──────────────────────────────────────────────
        hdr = Table([[
            Paragraph(f"MANTENIMIENTO PREVENTIVO", sty(12, True, WHITE, TA_CENTER)),
            Paragraph(f"{data.get('machineName','')}", sty(12, True, WHITE, TA_CENTER)),
        ]], colWidths=[W*0.5, W*0.5])
        hdr.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1),GREEN),
            ('TOPPADDING',(0,0),(-1,-1),8), ('BOTTOMPADDING',(0,0),(-1,-1),8),
        ]))
        story.append(hdr)
        story.append(Spacer(1,2*mm))

        # ── INFO ────────────────────────────────────────────────
        info = Table([[
            Paragraph(f"<b>Técnico:</b> {data.get('tecnico','')}", sty(8)),
            Paragraph(f"<b>Fecha:</b> {data.get('fecha','')}", sty(8)),
            Paragraph(f"<b>Supervisor:</b> {data.get('supervisor','')}", sty(8)),
        ]], colWidths=[W*0.4, W*0.2, W*0.4])
        info.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1),LGREEN),
            ('GRID',(0,0),(-1,-1),0.3,colors.HexColor('#c8e6c9')),
            ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
            ('LEFTPADDING',(0,0),(-1,-1),6),
        ]))
        story.append(info)
        story.append(Spacer(1,2*mm))

        # ── CHECKLIST ───────────────────────────────────────────
        rows = [[
            Paragraph('#', sty(7, True, WHITE, TA_CENTER)),
            Paragraph('Descripción', sty(7, True, WHITE)),
            Paragraph('OK', sty(7, True, WHITE, TA_CENTER)),
            Paragraph('NG', sty(7, True, WHITE, TA_CENTER)),
            Paragraph('Comentario', sty(7, True, WHITE)),
        ]]
        for i, item in enumerate(data.get('items', []), 1):
            st = item.get('status','')
            bg = colors.HexColor('#f1faf2') if st=='ok' else (colors.HexColor('#fff5f5') if st=='ng' else (WHITE if i%2==0 else GRAY))
            rows.append([
                Paragraph(str(i), sty(7, align=TA_CENTER)),
                Paragraph(item.get('desc', item.get('description','')), sty(7)),
                Paragraph('✓' if st=='ok' else '', sty(9, True, colors.HexColor('#2e7d32'), TA_CENTER)),
                Paragraph('✓' if st=='ng' else '', sty(9, True, RED, TA_CENTER)),
                Paragraph(item.get('comment',''), sty(7)),
            ])
        ct = Table(rows, colWidths=[W*0.04, W*0.53, W*0.06, W*0.06, W*0.31], repeatRows=1)
        cts = [('BACKGROUND',(0,0),(-1,0),GREEN),('GRID',(0,0),(-1,-1),0.3,colors.HexColor('#c8e6c9')),
               ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
               ('TOPPADDING',(0,0),(-1,-1),2),('BOTTOMPADDING',(0,0),(-1,-1),2)]
        for i in range(1, len(rows)):
            st = data['items'][i-1].get('status','')
            cts.append(('BACKGROUND',(0,i),(-1,i),
                        colors.HexColor('#f1faf2') if st=='ok' else
                        colors.HexColor('#fff5f5') if st=='ng' else
                        (WHITE if i%2==0 else GRAY)))
        ct.setStyle(TableStyle(cts))
        story.append(ct)
        story.append(Spacer(1,2*mm))

        # ── CALENDARIO ──────────────────────────────────────────
        meses = ['ENE','FEB','MAR','ABR','MAY','JUN','JUL','AGO','SEP','OCT','NOV','DIC']
        months = set(data.get('month',[]))
        cal = Table(
            [[Paragraph(m, sty(7, True, WHITE, TA_CENTER)) for m in meses],
             [Paragraph('✓' if m in months else '', sty(9, True, GREEN, TA_CENTER)) for m in meses]],
            colWidths=[W/12]*12)
        cal.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),GREEN),('BACKGROUND',(0,1),(-1,1),LGREEN),
            ('GRID',(0,0),(-1,-1),0.3,colors.HexColor('#c8e6c9')),
            ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
        ]))
        story.append(cal)
        story.append(Spacer(1,3*mm))

        # ── FIRMAS ──────────────────────────────────────────────
        def sig_img(b64):
            if not b64: return None
            try:
                raw = base64.b64decode(b64.split(',')[1] if ',' in b64 else b64)
                pil = PILImage.open(io.BytesIO(raw)).convert("RGBA")
                bg  = PILImage.new("RGBA", pil.size, (255,255,255,255))
                bg.paste(pil, mask=pil.split()[3])
                ibuf = io.BytesIO(); bg.convert("RGB").save(ibuf, 'PNG'); ibuf.seek(0)
                return RLImage(ibuf, width=60*mm, height=18*mm)
            except: return None

        tec_img = sig_img(data.get('sigTecnicoImg'))
        sup_img = sig_img(data.get('sigSupervisorImg'))

        sig = Table([[
            [Paragraph(f"<b>Realizó:</b> {data.get('tecnico','')}", sty(8)),
             tec_img or Paragraph('Firma: ___________________________', sty(8)),
             Paragraph('Firma:', sty(8))],
            [Paragraph(f"<b>Supervisor:</b> {data.get('supervisor','')}", sty(8)),
             sup_img or Paragraph('Firma: ___________________________', sty(8)),
             Paragraph('Firma:', sty(8))],
        ]], colWidths=[W*0.5, W*0.5])
        sig.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1),LGREEN),
            ('GRID',(0,0),(-1,-1),0.3,colors.HexColor('#c8e6c9')),
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
            ('LEFTPADDING',(0,0),(-1,-1),6),
        ]))
        story.append(sig)

        doc.build(story)
        buf.seek(0)
        fname = f"REPORTE_{data.get('machineId','EQ')}_{data.get('fecha','').replace('/','-')}.pdf"
        return send_file(buf, as_attachment=True, download_name=fname, mimetype='application/pdf')
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',3000)), debug=False)
