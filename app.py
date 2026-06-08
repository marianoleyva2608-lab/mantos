import os, io, base64
from flask import Flask, request, send_file

try:
    import openpyxl
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.drawing.xdr import XDRPoint2D, XDRPositiveSize2D
    from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor
    from PIL import Image as PILImage
except ImportError:
    os.system("pip install openpyxl Pillow -q")
    import openpyxl
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.drawing.xdr import XDRPoint2D, XDRPositiveSize2D
    from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor
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

def add_sig_anchored(ws, b64_str, col_idx, row_idx, y_offset_px, width_px=170, height_px=50):
    """Add signature image anchored next to Firma: text"""
    img = make_sig_image(b64_str, width_px, height_px)
    if not img:
        return
    # col_idx and row_idx are 0-based
    p = XDRPoint2D(col=col_idx, colOff=5*EMU, row=row_idx, rowOff=y_offset_px*EMU)
    s = XDRPositiveSize2D(width_px*EMU, height_px*EMU)
    img.anchor = OneCellAnchor(_from=p, ext=s)
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

            # Escribir solo el nombre en la fila superior; "Firma:" queda en la plantilla
            ws.cell(row=sig_row, column=2).value  = f"Realizó: {tec}"
            ws.cell(row=sig_row, column=8).value  = f"Fecha: {fec}"
            ws.cell(row=sig_row, column=11).value = f"Supervisor de Producción: {sup}"

            # La fila de "Firma:" es la siguiente (sig_row + 1)
            firma_row = sig_row + 1
            firma_y = 8  # pequeño offset desde la parte superior de la fila Firma:

            # Firma del técnico → columna D (idx 3), fila "Firma:"
            tec_sig = data.get('sigTecnicoImg')
            if tec_sig:
                add_sig_anchored(ws, tec_sig,
                    col_idx=3,              # Column D, junto a "Firma:"
                    row_idx=firma_row-1,    # 0-based
                    y_offset_px=firma_y)

            # Firma del supervisor → columna M (idx 12), fila "Firma:"
            sup_sig = data.get('sigSupervisorImg')
            if sup_sig:
                add_sig_anchored(ws, sup_sig,
                    col_idx=12,             # Column M, junto a "Firma:"
                    row_idx=firma_row-1,    # 0-based
                    y_offset_px=firma_y)

        # Supervisor comments
        sup_comments = data.get('supComments','')
        if sup_comments and sig_row:
            ws.cell(row=sig_row+1, column=2).value = f"Comentarios del Supervisor: {sup_comments}"

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
