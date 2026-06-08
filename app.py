import os, io, json
from flask import Flask, request, send_file, Response

try:
    import openpyxl
except ImportError:
    os.system("pip install openpyxl -q")
    import openpyxl

app = Flask(__name__)

MONTH_COLS = {"ENE":"B","FEB":"C","MAR":"D","ABR":"E","MAY":"F","JUN":"G",
              "JUL":"H","AGO":"I","SEP":"J","OCT":"K","NOV":"L","DIC":"M"}

@app.route('/')
def index():
    return open('index.html', encoding='utf-8').read(), 200, {'Content-Type':'text/html; charset=utf-8'}

@app.route('/generar', methods=['POST'])
def generar():
    try:
        data = request.json
        file_key = data.get('file','termoformado')
        template = 'MTTO_Preventivo_Termoformado_2026.xlsx' if file_key=='termoformado' else 'MTTO_Preventivo_Conversion_2026.xlsx'

        wb = openpyxl.load_workbook(template)
        ws = wb[data['sheet']]

        # Fill checklist items
        for item in data.get('items', []):
            row = item['row']
            st = item.get('status','')
            cm = item.get('comment','')
            ws.cell(row=row, column=11).value = '( ✓ )' if st=='ok' else '(   )'
            ws.cell(row=row, column=12).value = '( ✓ )' if st=='ng' else '(   )'
            if cm:
                ws.cell(row=row, column=13).value = cm

        # Fill calendar
        cal_row = data.get('cal_data_row')
        months = set(data.get('month', []))
        if cal_row:
            for m, col in MONTH_COLS.items():
                col_idx = ord(col)-ord('A')+1
                ws.cell(row=cal_row, column=col_idx).value = '( ✓ )' if m in months else '(   )'
            v = data.get('voltaje', {})
            if v.get('l1'): ws.cell(row=cal_row, column=14).value = v['l1']
            if v.get('l2'): ws.cell(row=cal_row, column=15).value = v['l2']
            if v.get('l3'): ws.cell(row=cal_row, column=16).value = v['l3']
            if v.get('vac'): ws.cell(row=cal_row, column=17).value = v['vac']

        # Fill signatures
        sig_row = data.get('sig_row')
        if sig_row:
            tec = data.get('tecnico','_______________')
            fec = data.get('fecha','_______________')
            sup = data.get('supervisor','_______________')
            ws.cell(row=sig_row, column=2).value  = f"Realizó: {tec}\n\nFirma: _________________________"
            ws.cell(row=sig_row, column=8).value  = f"Fecha: {fec}"
            ws.cell(row=sig_row, column=11).value = f"Supervisor de Producción: {sup}\n\nFirma: _____________________________"

        # Supervisor comments
        sup_comments = data.get('supComments','')
        if sup_comments and sig_row:
            ws.cell(row=sig_row+1, column=2).value = f"Comentarios del Supervisor: {sup_comments}"

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        machine_id = data.get('machineId','EQUIPO')
        fec2 = data.get('fecha','').replace('/','-')
        filename = f"REPORTE_{machine_id}_{fec2}.xlsx"

        return send_file(buf, as_attachment=True, download_name=filename,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        return {'error': str(e)}, 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    app.run(host='0.0.0.0', port=port, debug=False)
