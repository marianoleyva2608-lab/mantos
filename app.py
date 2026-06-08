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
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT

        data = request.json
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4,
                                leftMargin=12*mm, rightMargin=12*mm,
                                topMargin=12*mm, bottomMargin=12*mm)

        styles = getSampleStyleSheet()
        GREEN  = colors.HexColor('#1a5c2a')
        LGREEN = colors.HexColor('#e8f5e9')
        WHITE  = colors.white
        GRAY   = colors.HexColor('#f5f5f5')

        s_title  = ParagraphStyle('t', fontSize=13, textColor=WHITE, fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=0)
        s_sub    = ParagraphStyle('s', fontSize=9,  textColor=WHITE, fontName='Helvetica', alignment=TA_CENTER)
        s_label  = ParagraphStyle('l', fontSize=8,  fontName='Helvetica-Bold')
        s_value  = ParagraphStyle('v', fontSize=8,  fontName='Helvetica')
        s_small  = ParagraphStyle('sm', fontSize=7, fontName='Helvetica')
        s_head   = ParagraphStyle('h', fontSize=8,  fontName='Helvetica-Bold', textColor=WHITE)
        s_ok     = ParagraphStyle('ok', fontSize=9, fontName='Helvetica-Bold', textColor=colors.HexColor('#2e7d32'), alignment=TA_CENTER)
        s_ng     = ParagraphStyle('ng', fontSize=9, fontName='Helvetica-Bold', textColor=colors.HexColor('#c62828'), alignment=TA_CENTER)

        story = []
        W = A4[0] - 24*mm

        # ── HEADER ──────────────────────────────────────────────
        header_data = [[
            Paragraph(f"MANTENIMIENTO PREVENTIVO", s_title),
            Paragraph(f"{data.get('machineName','')}", s_title),
        ]]
        header_table = Table(header_data, colWidths=[W*0.5, W*0.5])
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), GREEN),
            ('TEXTCOLOR',  (0,0), (-1,-1), WHITE),
            ('ALIGN',      (0,0), (-1,-1), 'CENTER'),
            ('VALIGN',     (0,0), (-1,-1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [GREEN]),
            ('TOPPADDING',    (0,0),(-1,-1), 8),
            ('BOTTOMPADDING', (0,0),(-1,-1), 8),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 3*mm))

        # ── INFO GENERAL ────────────────────────────────────────
        info_data = [
            [Paragraph('Técnico:', s_label), Paragraph(data.get('tecnico',''), s_value),
             Paragraph('Fecha:', s_label),   Paragraph(data.get('fecha',''), s_value),
             Paragraph('Supervisor:', s_label), Paragraph(data.get('supervisor',''), s_value)],
        ]
        info_table = Table(info_data, colWidths=[W*0.1, W*0.23, W*0.07, W*0.18, W*0.1, W*0.32])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0),(-1,-1), LGREEN),
            ('GRID', (0,0),(-1,-1), 0.3, colors.HexColor('#c8e6c9')),
            ('TOPPADDING',(0,0),(-1,-1),5), ('BOTTOMPADDING',(0,0),(-1,-1),5),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 3*mm))

        # ── CHECKLIST ───────────────────────────────────────────
        ch_header = [
            Paragraph('#', s_head),
            Paragraph('Descripción', s_head),
            Paragraph('OK', s_head),
            Paragraph('NG', s_head),
            Paragraph('Comentario', s_head),
        ]
        ch_rows = [ch_header]
        for i, item in enumerate(data.get('items', []), 1):
            st = item.get('status','')
            ok_mark = Paragraph('✓', s_ok) if st=='ok' else Paragraph('', s_small)
            ng_mark = Paragraph('✓', s_ng) if st=='ng' else Paragraph('', s_small)
            bg = colors.HexColor('#f1faf2') if st=='ok' else (colors.HexColor('#fff5f5') if st=='ng' else WHITE)
            ch_rows.append([
                Paragraph(str(i), s_small),
                Paragraph(item.get('desc', item.get('description', '')), s_small),
                ok_mark, ng_mark,
                Paragraph(item.get('comment',''), s_small),
            ])

        col_w = [W*0.05, W*0.52, W*0.07, W*0.07, W*0.29]
        ch_table = Table(ch_rows, colWidths=col_w, repeatRows=1)
        style_ch = [
            ('BACKGROUND', (0,0),(-1,0), GREEN),
            ('TEXTCOLOR',  (0,0),(-1,0), WHITE),
            ('GRID', (0,0),(-1,-1), 0.3, colors.HexColor('#c8e6c9')),
            ('ALIGN', (2,0),(3,-1), 'CENTER'),
            ('VALIGN', (0,0),(-1,-1), 'MIDDLE'),
            ('TOPPADDING',(0,0),(-1,-1),3), ('BOTTOMPADDING',(0,0),(-1,-1),3),
            ('FONTSIZE',(0,0),(-1,-1),7),
        ]
        for i in range(1, len(ch_rows)):
            st = data['items'][i-1].get('status','')
            if st=='ok': style_ch.append(('BACKGROUND',(0,i),(-1,i), colors.HexColor('#f1faf2')))
            elif st=='ng': style_ch.append(('BACKGROUND',(0,i),(-1,i), colors.HexColor('#fff5f5')))
            else: style_ch.append(('BACKGROUND',(0,i),(-1,i), WHITE if i%2==0 else GRAY))
        ch_table.setStyle(TableStyle(style_ch))
        story.append(ch_table)
        story.append(Spacer(1, 3*mm))

        # ── CALENDARIO ──────────────────────────────────────────
        months = set(data.get('month', []))
        all_months = ['ENE','FEB','MAR','ABR','MAY','JUN','JUL','AGO','SEP','OCT','NOV','DIC']
        cal_header = [Paragraph(m, ParagraphStyle('mc', fontSize=7, fontName='Helvetica-Bold', textColor=WHITE, alignment=TA_CENTER)) for m in all_months]
        cal_vals   = [Paragraph('( ✓ )' if m in months else '(   )', ParagraphStyle('mv', fontSize=8, alignment=TA_CENTER)) for m in all_months]
        cal_table  = Table([cal_header, cal_vals], colWidths=[W/12]*12)
        cal_table.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0), GREEN),
            ('BACKGROUND',(0,1),(-1,1), LGREEN),
            ('GRID',(0,0),(-1,-1), 0.3, colors.HexColor('#c8e6c9')),
            ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
        ]))
        story.append(cal_table)
        story.append(Spacer(1, 4*mm))

        # ── FIRMAS ──────────────────────────────────────────────
        def sig_cell(label, name, b64img):
            content = [Paragraph(f'<b>{label}:</b> {name}', s_small), Spacer(1,1*mm)]
            if b64img:
                try:
                    raw = base64.b64decode(b64img.split(',')[1] if ',' in b64img else b64img)
                    pil = PILImage.open(io.BytesIO(raw)).convert("RGBA")
                    bg  = PILImage.new("RGBA", pil.size, (255,255,255,255))
                    bg.paste(pil, mask=pil.split()[3])
                    pil = bg.convert("RGB")
                    ibuf = io.BytesIO(); pil.save(ibuf, format='PNG'); ibuf.seek(0)
                    img = RLImage(ibuf, width=55*mm, height=16*mm)
                    content.append(img)
                except:
                    content.append(Paragraph('[ firma ]', s_small))
            content.append(Paragraph('Firma: ________________________', s_small))
            return content

        tec_cell = sig_cell('Realizó', data.get('tecnico',''), data.get('sigTecnicoImg'))
        sup_cell = sig_cell('Supervisor', data.get('supervisor',''), data.get('sigSupervisorImg'))

        from reportlab.platypus import KeepInFrame
        sig_table = Table([[tec_cell, sup_cell]], colWidths=[W*0.5, W*0.5])
        sig_table.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1), LGREEN),
            ('GRID',(0,0),(-1,-1), 0.3, colors.HexColor('#c8e6c9')),
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
            ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
        ]))
        story.append(sig_table)

        doc.build(story)
        buf.seek(0)
        fname = f"REPORTE_{data.get('machineId','EQ')}_{data.get('fecha','').replace('/','-')}.pdf"
        return send_file(buf, as_attachment=True, download_name=fname, mimetype='application/pdf')
    except Exception as e:
        import traceback; traceback.print_exc()
        return {'error': str(e)}, 500
