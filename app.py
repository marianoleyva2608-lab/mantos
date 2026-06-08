import os, io, json, base64
from flask import Flask, request, send_file

try:
    import openpyxl
    from openpyxl.drawing.image import Image as XLImage
    from PIL import Image as PILImage
except ImportError:
    os.system("pip install openpyxl Pillow -q")
    import openpyxl
    from openpyxl.drawing.image import Image as XLImage
    from PIL import Image as PILImage

app = Flask(__name__)

MONTH_COLS = {"ENE":"B","FEB":"C","MAR":"D","ABR":"E","MAY":"F","JUN":"G",
              "JUL":"H","AGO":"I","SEP":"J","OCT":"K","NOV":"L","DIC":"M"}

def b64_to_xl_image(b64_str, width, height):
    """Convert base64 PNG to openpyxl image with given dimensions."""
    if not b64_str:
        return None
    try:
        # Strip data URL prefix if present
        if ',' in b64_str:
            b64_str = b64_str.split(',')[1]
        img_bytes = base64.b64decode(b64_str)
        pil_img = PILImage.open(io.BytesIO(img_bytes)).convert("RGBA")
        # White background for transparency
        bg = PILImage.new("RGBA", pil_img.size, (255,255,255,255))
        bg.paste(pil_img, mask=pil_img.split()[3])
        pil_img = bg.convert("RGB")
        pil_img = pil_img.resize((width, height), PILImage.LANCZOS)
        buf = io.BytesIO()
        pil_img.save(buf, format='PNG')
        buf.seek(0)
        xl_img = XLImage(buf)
        xl_img.width = width
        xl_img.height = height
        return xl_img
    except Exception as e:
        print(f"Image error: {e}")
        return None

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

        # ── Fill checklist items ──
        for item in data.get('items', []):
            row = item['row']
            st  = item.get('status','')
            cm  = item.get('comment','')
            ws.cell(row=row, column=11).value = '( ✓ )' if st=='ok' else '(   )'
            ws.cell(row=row, column=12).value = '( ✓ )' if st=='ng' else '(   )'
            if cm:
                ws.cell(row=row, column=13).value = cm

        # ── Fill calendar ──
        cal_row = data.get('cal_data_row')
        months  = set(data.get('month', []))
        if cal_row:
            for m, col in MONTH_COLS.items():
                ws.cell(row=cal_row, column=ord(col)-ord('A')+1).value = '( ✓ )' if m in months else '(   )'
            v = data.get('voltaje', {})
            if v.get('l1'):  ws.cell(row=cal_row, column=14).value = v['l1']
            if v.get('l2'):  ws.cell(row=cal_row, column=15).value = v['l2']
            if v.get('l3'):  ws.cell(row=cal_row, column=16).value = v['l3']
            if v.get('vac'): ws.cell(row=cal_row, column=17).value = v['vac']

        # ── Fill signature row text ──
        sig_row = data.get('sig_row')
        if sig_row:
            tec = data.get('tecnico','_______________')
            fec = data.get('fecha','_______________')
            sup = data.get('supervisor','_______________')
            ws.cell(row=sig_row, column=2).value  = f"Realizó: {tec}\n\nFirma:"
            ws.cell(row=sig_row, column=8).value  = f"Fecha: {fec}"
            ws.cell(row=sig_row, column=11).value = f"Supervisor: {sup}\n\nFirma:"

            # ── Embed technician signature image ──
            sig_tec_b64 = data.get('sigTecnicoImg')
            if sig_tec_b64:
                xl_img = b64_to_xl_image(sig_tec_b64, 160, 55)
                if xl_img:
                    # Place signature image at column D, same sig_row
                    xl_img.anchor = f'D{sig_row}'
                    ws.add_image(xl_img)

            # ── Embed supervisor signature image ──
            sig_sup_b64 = data.get('sigSupervisorImg')
            if sig_sup_b64:
                xl_img2 = b64_to_xl_image(sig_sup_b64, 160, 55)
                if xl_img2:
                    xl_img2.anchor = f'M{sig_row}'
                    ws.add_image(xl_img2)

        # ── Supervisor comments ──
        sup_comments = data.get('supComments','')
        if sup_comments and sig_row:
            ws.cell(row=sig_row+1, column=2).value = f"Comentarios del Supervisor: {sup_comments}"

        # ── Save and return ──
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        machine_id = data.get('machineId','EQUIPO')
        fec2 = data.get('fecha','').replace('/','-')
        filename = f"REPORTE_{machine_id}_{fec2}.xlsx"
        return send_file(buf, as_attachment=True, download_name=filename,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'error': str(e)}, 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    app.run(host='0.0.0.0', port=port, debug=False)
