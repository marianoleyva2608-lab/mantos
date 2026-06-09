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

# ── Firma digital PKI ─────────────────────────────────────────────────────────
CERT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'adpack_cert.p12')
CERT_PASS = b'adpack2026'

def ensure_certificate():
    """Genera un certificado auto-firmado si no existe."""
    if os.path.exists(CERT_PATH):
        return
    try:
        import datetime
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.serialization.pkcs12 import serialize_key_and_certificates

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "MX"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AD-PACK"),
            x509.NameAttribute(NameOID.COMMON_NAME, "AD-PACK Mantenimiento Preventivo"),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject).issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256(), default_backend())
        )
        p12 = serialize_key_and_certificates(
            name=b"AD-PACK", key=key, cert=cert, cas=None,
            encryption_algorithm=serialization.BestAvailableEncryption(CERT_PASS)
        )
        with open(CERT_PATH, 'wb') as f:
            f.write(p12)
        print("Certificado digital generado:", CERT_PATH)
    except Exception as e:
        print(f"[WARN] No se pudo generar certificado: {e}")

def sign_pdf(pdf_bytes, signer_name='AD-PACK', reason='Mantenimiento Preventivo'):
    """Firma un PDF con el certificado PKI de la app. Retorna bytes del PDF firmado."""
    try:
        from pyhanko.sign import signers, fields
        from pyhanko.sign.fields import SigFieldSpec
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
        from pyhanko.sign.signers.pdf_signer import PdfSignatureMetadata
        import pyhanko.sign.signers as pdf_signers

        ensure_certificate()
        if not os.path.exists(CERT_PATH):
            return pdf_bytes  # Sin certificado, devolver sin firmar

        signer = signers.SimpleSigner.load_pkcs12(CERT_PATH, passphrase=CERT_PASS)
        pdf_in = io.BytesIO(pdf_bytes)
        w = IncrementalPdfFileWriter(pdf_in)
        fields.append_signature_field(w, SigFieldSpec('FirmaDigital', on_page=0, box=(30, 15, 280, 55)))
        meta = PdfSignatureMetadata(
            field_name='FirmaDigital',
            reason=reason,
            location='AD-PACK México',
            signer_serial_number=None,
            certify=True,
        )
        out = io.BytesIO()
        pdf_signers.sign_pdf(w, signature_meta=meta, signer=signer, output=out)
        return out.getvalue()
    except Exception as e:
        print(f"[WARN] Error al firmar PDF: {e}")
        return pdf_bytes  # Si falla la firma, devolver el PDF sin firmar

ensure_certificate()
# ─────────────────────────────────────────────────────────────────────────────

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

def apply_checklist_data(ws, data):
    """Escribe los datos del checklist en la hoja ws."""
    for item in data.get('items', []):
        row, st, cm = item['row'], item.get('status', ''), item.get('comment', '')
        ws.cell(row=row, column=11).value = '( v )' if st == 'ok' else '(   )'
        ws.cell(row=row, column=12).value = '( v )' if st == 'ng' else '(   )'
        if cm:
            ws.cell(row=row, column=13).value = cm

    cal_row = data.get('cal_data_row')
    months = set(data.get('month', []))
    if cal_row:
        for m, col in MONTH_COLS.items():
            ws.cell(row=cal_row, column=ord(col) - ord('A') + 1).value = '( v )' if m in months else '(   )'
        v = data.get('voltaje', {})
        for col_n, key in [(14, 'l1'), (15, 'l2'), (16, 'l3'), (17, 'vac')]:
            if v.get(key):
                ws.cell(row=cal_row, column=col_n).value = v[key]

    sig_row = data.get('sig_row')
    if sig_row:
        tec = data.get('tecnico', '_______________')
        fec = data.get('fecha', '_______________')
        sup = data.get('supervisor', '_______________')
        firma_row = sig_row + 1

        ws.cell(row=sig_row, column=2).value  = f"Realizó: {tec}"
        ws.cell(row=sig_row, column=8).value  = f"Fecha: {fec}"
        ws.cell(row=sig_row, column=11).value = f"Supervisor de Producción: {sup}"

        tec_sig = data.get('sigTecnicoImg')
        if tec_sig:
            add_sig_anchored(ws, tec_sig, col_idx=1, row_idx=firma_row - 1, width_px=560, height_px=60)

        sup_sig = data.get('sigSupervisorImg')
        if sup_sig:
            add_sig_anchored(ws, sup_sig, col_idx=10, row_idx=firma_row - 1, width_px=660, height_px=60)

    sup_comments = data.get('supComments', '')
    if sup_comments and sig_row:
        ws.cell(row=sig_row + 2, column=2).value = f"Comentarios: {sup_comments}"


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
        template = 'MTTO_Preventivo_Termoformado_2026.xlsx' if file_key == 'termoformado' else 'MTTO_Preventivo_Conversion_2026.xlsx'

        wb = openpyxl.load_workbook(template)
        ws = wb[data['sheet']]
        apply_checklist_data(ws, data)

        # Solo guardar la hoja activa
        for s in [n for n in wb.sheetnames if n != ws.title]:
            del wb[s]
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        fname = f"REPORTE_{data.get('machineId','EQ')}_{data.get('fecha','').replace('/','-')}.xlsx"
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

        # Eliminar todas las hojas excepto la activa
        sheets_to_delete = [s for s in wb.sheetnames if s != ws.title]
        for s in sheets_to_delete:
            del wb[s]

        xlsx_path = os.path.join(tmp_dir, 'reporte.xlsx')
        wb.save(xlsx_path)

        result = subprocess.run(
            ['libreoffice', '--headless', '--convert-to', 'pdf',
             '--outdir', tmp_dir, xlsx_path],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            raise RuntimeError(f"LibreOffice error: {result.stderr}")

        pdf_path = os.path.join(tmp_dir, 'reporte.pdf')
        if not os.path.exists(pdf_path):
            raise RuntimeError("PDF no generado por LibreOffice")

        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()

        # Firmar el PDF con certificado digital PKI
        pdf_bytes = sign_pdf(pdf_bytes, reason=f"Mantenimiento Preventivo - {data.get('machineName', data.get('machineId', ''))}")

        fname = f"REPORTE_{data.get('machineId', 'EQ')}_{data.get('fecha', '').replace('/', '-')}.pdf"
        return send_file(io.BytesIO(pdf_bytes), as_attachment=True, download_name=fname, mimetype='application/pdf')

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 3000)), debug=False)
