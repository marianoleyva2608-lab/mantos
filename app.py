import os, io, base64
from flask import Flask, request, send_file

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
                    col_idx=1,              # Columna B — inicio de celda combinada B:G
                    row_idx=firma_row - 1,  # 0-based → Excel row = firma_row
                    width_px=560,
                    height_px=60)

            # Firma supervisor → celda combinada K:Q (col K=idx 10), 660x60 px
            sup_sig = data.get('sigSupervisorImg')
            if sup_sig:
                add_sig_anchored(ws, sup_sig,
                    col_idx=10,             # Columna K — inicio de celda combinada K:Q
                    row_idx=firma_row - 1,
                    width_px=660,
                    height_px=60)

        # Supervisor comments
        sup_comments = data.get('supComments','')
        if sup_comments and sig_row:
            ws.cell(row=sig_row + 2, column=2).value = f"Comentarios del Supervisor: {sup_comments}"

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
