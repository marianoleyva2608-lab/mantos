import os, io, base64, sqlite3, json, hashlib, hmac, secrets
from datetime import datetime, timezone, timedelta
from flask import Flask, request, send_file, jsonify

# ── PKI imports ──────────────────────────────────────────────────────────────
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend

# ── Image / Excel imports ────────────────────────────────────────────────────
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

# ─────────────────────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), 'reports.db')
ORG_NAME = "AD-PACK"
CA_CN    = "AD-PACK Mantenimiento CA"
EMU      = 9525

MONTH_COLS = {"ENE":"B","FEB":"C","MAR":"D","ABR":"E","MAY":"F","JUN":"G",
              "JUL":"H","AGO":"I","SEP":"J","OCT":"K","NOV":"L","DIC":"M"}

# ══════════════════════════════════════════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════════════════════════════════════════

def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_db()
    con.executescript('''
        CREATE TABLE IF NOT EXISTS reports
            (id INTEGER PRIMARY KEY, machine_id TEXT, fecha TEXT, data TEXT);

        CREATE TABLE IF NOT EXISTS ca_store
            (id INTEGER PRIMARY KEY CHECK(id=1),
             cert_pem TEXT NOT NULL,
             key_pem  TEXT NOT NULL);

        CREATE TABLE IF NOT EXISTS cert_users
            (id       INTEGER PRIMARY KEY AUTOINCREMENT,
             name     TEXT NOT NULL,
             role     TEXT NOT NULL,
             email    TEXT UNIQUE NOT NULL,
             pin_hash TEXT NOT NULL,
             cert_pem TEXT NOT NULL,
             key_enc  TEXT NOT NULL,
             created  TEXT NOT NULL);

        CREATE TABLE IF NOT EXISTS cert_signatures
            (id          INTEGER PRIMARY KEY AUTOINCREMENT,
             report_id   TEXT,
             role        TEXT,
             user_name   TEXT,
             cert_serial TEXT,
             sig_b64     TEXT,
             cert_pem    TEXT,
             signed_at   TEXT);
    ''')
    con.commit()
    con.close()

init_db()

# ══════════════════════════════════════════════════════════════════════════════
#  PKI HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _now_utc():
    return datetime.now(timezone.utc)

def _gen_key():
    return rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend())

def _key_to_pem(key):
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()

def _key_enc_pem(key, passphrase: str):
    """Serialize private key encrypted with passphrase."""
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(passphrase.encode())).decode()

def _load_key(pem: str, passphrase: str = None):
    pw = passphrase.encode() if passphrase else None
    return serialization.load_pem_private_key(pem.encode(), password=pw, backend=default_backend())

def _cert_to_pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM).decode()

def _load_cert(pem: str):
    return x509.load_pem_x509_certificate(pem.encode(), default_backend())

def _cert_info(cert):
    sub = cert.subject
    iss = cert.issuer
    return {
        "cn":           sub.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
        "org":          (sub.get_attributes_for_oid(NameOID.ORGANIZATION_NAME) or [None])[0].value
                        if sub.get_attributes_for_oid(NameOID.ORGANIZATION_NAME) else ORG_NAME,
        "serial":       format(cert.serial_number, 'X'),
        "valid_from":   cert.not_valid_before_utc.strftime("%d/%m/%Y"),
        "valid_to":     cert.not_valid_after_utc.strftime("%d/%m/%Y"),
        "issuer":       iss.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
        "fingerprint":  cert.fingerprint(hashes.SHA256()).hex().upper()[:16],
    }

def _hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode()).hexdigest()

def generate_ca():
    """Generate self-signed CA certificate for AD-PACK."""
    key  = _gen_key()
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME,            CA_CN),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME,      ORG_NAME),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Mantenimiento"),
        x509.NameAttribute(NameOID.COUNTRY_NAME,           "MX"),
    ])
    now  = _now_utc()
    cert = (x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, key_cert_sign=True, crl_sign=True,
            content_commitment=False, key_encipherment=False, data_encipherment=False,
            key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
        .sign(key, hashes.SHA256(), default_backend()))
    return cert, key

def generate_user_cert(name: str, email: str, role: str, ca_cert, ca_key):
    """Issue a user certificate signed by the CA."""
    key  = _gen_key()
    subj = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME,            name),
        x509.NameAttribute(NameOID.EMAIL_ADDRESS,          email),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME,      ORG_NAME),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, role.capitalize()),
        x509.NameAttribute(NameOID.COUNTRY_NAME,           "MX"),
    ])
    now  = _now_utc()
    cert = (x509.CertificateBuilder()
        .subject_name(subj)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=365 * 3))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=True,
            key_encipherment=False, data_encipherment=False, key_agreement=False,
            key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False),
            critical=True)
        .add_extension(x509.ExtendedKeyUsage([
            ExtendedKeyUsageOID.CLIENT_AUTH,
            x509.ObjectIdentifier("1.3.6.1.5.5.7.3.8"),  # time stamping
        ]), critical=False)
        .sign(ca_key, hashes.SHA256(), default_backend()))
    return cert, key

def sign_data(data_bytes: bytes, key_pem: str, passphrase: str) -> str:
    """Sign arbitrary bytes with user's private key. Returns base64 signature."""
    key = _load_key(key_pem, passphrase)
    sig = key.sign(data_bytes, padding.PSS(
        mgf=padding.MGF1(hashes.SHA256()),
        salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())
    return base64.b64encode(sig).decode()

def verify_signature(data_bytes: bytes, sig_b64: str, cert_pem: str) -> bool:
    try:
        cert = _load_cert(cert_pem)
        sig  = base64.b64decode(sig_b64)
        cert.public_key().verify(sig, data_bytes,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256())
        return True
    except Exception:
        return False

def get_or_create_ca():
    """Return (ca_cert, ca_key) — creating them on first call."""
    con = get_db()
    row = con.execute('SELECT cert_pem, key_pem FROM ca_store WHERE id=1').fetchone()
    con.close()
    if row:
        ca_cert = _load_cert(row['cert_pem'])
        ca_key  = _load_key(row['key_pem'])
        return ca_cert, ca_key
    # First time: generate
    ca_cert, ca_key = generate_ca()
    con = get_db()
    con.execute('INSERT OR REPLACE INTO ca_store(id, cert_pem, key_pem) VALUES(1,?,?)',
                (_cert_to_pem(ca_cert), _key_to_pem(ca_key)))
    con.commit()
    con.close()
    return ca_cert, ca_key

# ══════════════════════════════════════════════════════════════════════════════
#  FLASK APP
# ══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)

# ── Existing report endpoints ─────────────────────────────────────────────────

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
    con.execute('INSERT INTO reports(id, machine_id, fecha, data) VALUES(?,?,?,?)',
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

# ── PKI endpoints ─────────────────────────────────────────────────────────────

@app.route('/api/pki/ca-cert', methods=['GET'])
def api_ca_cert():
    """Download the CA certificate (PEM). Install in browsers/OS for full chain validation."""
    ca_cert, _ = get_or_create_ca()
    pem = _cert_to_pem(ca_cert)
    return send_file(io.BytesIO(pem.encode()), as_attachment=True,
                     download_name='AD-PACK_CA.crt', mimetype='application/x-pem-file')

@app.route('/api/pki/create-user', methods=['POST'])
def api_create_user():
    """Create a user with X.509 certificate.
    Body: { name, role, email, pin }
    """
    try:
        d = request.json
        name  = d['name'].strip()
        role  = d['role'].strip()   # 'tecnico' | 'supervisor'
        email = d['email'].strip().lower()
        pin   = d['pin']

        ca_cert, ca_key = get_or_create_ca()
        u_cert, u_key   = generate_user_cert(name, email, role, ca_cert, ca_key)

        cert_pem = _cert_to_pem(u_cert)
        key_enc  = _key_enc_pem(u_key, pin)   # private key encrypted with PIN
        pin_hash = _hash_pin(pin)
        created  = _now_utc().strftime("%Y-%m-%d %H:%M:%S UTC")

        con = get_db()
        try:
            con.execute('''INSERT INTO cert_users(name, role, email, pin_hash, cert_pem, key_enc, created)
                           VALUES(?,?,?,?,?,?,?)''',
                        (name, role, email, pin_hash, cert_pem, key_enc, created))
            con.commit()
        except sqlite3.IntegrityError:
            # email ya existe — actualizar cert
            con.execute('''UPDATE cert_users SET name=?, role=?, pin_hash=?, cert_pem=?, key_enc=?, created=?
                           WHERE email=?''',
                        (name, role, pin_hash, cert_pem, key_enc, created, email))
            con.commit()
        con.close()

        return jsonify({'ok': True, 'cert': _cert_info(u_cert)})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 400

@app.route('/api/pki/users', methods=['GET'])
def api_list_users():
    con = get_db()
    rows = con.execute('SELECT name, role, email, created, cert_pem FROM cert_users ORDER BY role, name').fetchall()
    con.close()
    result = []
    for r in rows:
        info = _cert_info(_load_cert(r['cert_pem']))
        result.append({
            'name': r['name'], 'role': r['role'],
            'email': r['email'], 'created': r['created'],
            'cert': info
        })
    return jsonify(result)

@app.route('/api/pki/sign', methods=['POST'])
def api_pki_sign():
    """Authenticate user and sign report data.
    Body: { email, pin, report_id, payload_json }
    Returns: { ok, cert_info, sig_b64, signed_at }
    """
    try:
        d         = request.json
        email     = d['email'].strip().lower()
        pin       = d['pin']
        report_id = d.get('report_id', '')
        payload   = d.get('payload_json', '')  # the data being signed (JSON string)

        con = get_db()
        row = con.execute('SELECT * FROM cert_users WHERE email=?', (email,)).fetchone()
        con.close()

        if not row:
            return jsonify({'error': 'Usuario no encontrado'}), 404
        if row['pin_hash'] != _hash_pin(pin):
            return jsonify({'error': 'PIN incorrecto'}), 401

        # Decrypt private key with PIN and sign
        data_bytes = payload.encode() if payload else report_id.encode()
        sig_b64    = sign_data(data_bytes, row['key_enc'], pin)
        signed_at  = _now_utc().strftime("%d/%m/%Y %H:%M:%S UTC")

        # Persist signature
        cert       = _load_cert(row['cert_pem'])
        cert_info  = _cert_info(cert)
        con = get_db()
        con.execute('''INSERT INTO cert_signatures(report_id, role, user_name, cert_serial, sig_b64, cert_pem, signed_at)
                       VALUES(?,?,?,?,?,?,?)''',
                    (report_id, row['role'], row['name'],
                     cert_info['serial'], sig_b64, row['cert_pem'], signed_at))
        con.commit()
        con.close()

        return jsonify({
            'ok': True,
            'cert_info': cert_info,
            'sig_b64': sig_b64,
            'signed_at': signed_at,
            'role': row['role'],
            'name': row['name'],
        })
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 400

@app.route('/api/pki/verify', methods=['POST'])
def api_pki_verify():
    """Verify a signature.
    Body: { sig_b64, cert_pem, payload_json }
    """
    try:
        d    = request.json
        ok   = verify_signature(d['payload_json'].encode(), d['sig_b64'], d['cert_pem'])
        cert = _load_cert(d['cert_pem'])
        return jsonify({'valid': ok, 'cert_info': _cert_info(cert)})
    except Exception as e:
        return jsonify({'valid': False, 'error': str(e)}), 400

@app.route('/api/pki/user-cert/<email>', methods=['GET'])
def api_user_cert(email):
    """Download user's certificate (public only) as .crt."""
    con = get_db()
    row = con.execute('SELECT cert_pem, name FROM cert_users WHERE email=?', (email.lower(),)).fetchone()
    con.close()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    return send_file(io.BytesIO(row['cert_pem'].encode()), as_attachment=True,
                     download_name=f"{row['name'].replace(' ','_')}.crt",
                     mimetype='application/x-pem-file')

# ── Main page ─────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return open('index.html', encoding='utf-8').read(), 200, {'Content-Type':'text/html; charset=utf-8'}

# ── Excel / PDF generation ───────────────────────────────────────────────────

def _build_wb(data):
    """Populate workbook from report data. Returns (wb, ws)."""
    file_key = data.get('file', 'termoformado')
    template = ('MTTO_Preventivo_Termoformado_2026.xlsx'
                if file_key == 'termoformado'
                else 'MTTO_Preventivo_Conversion_2026.xlsx')
    wb = openpyxl.load_workbook(template)
    ws = wb[data['sheet']]

    for item in data.get('items', []):
        row, st, cm = item['row'], item.get('status',''), item.get('comment','')
        ws.cell(row=row, column=11).value = '( v )' if st == 'ok' else '(   )'
        ws.cell(row=row, column=12).value = '( v )' if st == 'ng' else '(   )'
        if cm:
            ws.cell(row=row, column=13).value = cm

    cal_row = data.get('cal_data_row')
    months  = set(data.get('month', []))
    if cal_row:
        for m, col in MONTH_COLS.items():
            ws.cell(row=cal_row, column=ord(col)-ord('A')+1).value = \
                '( v )' if m in months else '(   )'
        v = data.get('voltaje', {})
        for col_n, key in [(14,'l1'),(15,'l2'),(16,'l3'),(17,'vac')]:
            if v.get(key):
                ws.cell(row=cal_row, column=col_n).value = v[key]

    sig_row = data.get('sig_row')
    if sig_row:
        tec = data.get('tecnico', '_______________')
        fec = data.get('fecha',   '_______________')
        sup = data.get('supervisor', '_______________')
        ws.cell(row=sig_row, column=2).value  = f"Realizo: {tec}"
        ws.cell(row=sig_row, column=8).value  = f"Fecha: {fec}"
        ws.cell(row=sig_row, column=11).value = f"Supervisor de Produccion: {sup}"

        # ── Embed digital certificate stamp instead of canvas image ──────────
        tec_cert = data.get('certTecnico')   # { cert_info, sig_b64, signed_at }
        sup_cert = data.get('certSupervisor')
        firma_row = sig_row + 1

        def cert_stamp_text(cert_data, label):
            if not cert_data:
                return None
            ci = cert_data.get('cert_info', {})
            return (f"✔ FIRMA DIGITAL X.509 — {label}\n"
                    f"  Firmado por: {ci.get('cn','')}\n"
                    f"  Organización: {ci.get('org','')}\n"
                    f"  No. Serie: {ci.get('serial','')}\n"
                    f"  Emitido por: {ci.get('issuer','')}\n"
                    f"  Válido: {ci.get('valid_from','')} – {ci.get('valid_to','')}\n"
                    f"  Fecha firma: {cert_data.get('signed_at','')}\n"
                    f"  Huella: {ci.get('fingerprint','')}")

        tec_stamp = cert_stamp_text(tec_cert, "TÉCNICO")
        sup_stamp = cert_stamp_text(sup_cert, "SUPERVISOR")

        if tec_stamp:
            ws.cell(row=firma_row, column=2).value = tec_stamp
        if sup_stamp:
            ws.cell(row=firma_row, column=11).value = sup_stamp

    sup_comments = data.get('supComments', '')
    if sup_comments and sig_row:
        ws.cell(row=sig_row+2, column=2).value = f"Comentarios: {sup_comments}"

    return wb, ws

@app.route('/generar', methods=['POST'])
def generar():
    try:
        data = request.json
        wb, _ = _build_wb(data)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        fname = f"REPORTE_{data.get('machineId','EQ')}_{data.get('fecha','').replace('/','-')}.xlsx"
        return send_file(buf, as_attachment=True, download_name=fname,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/generar_pdf', methods=['POST'])
def generar_pdf():
    try:
        import weasyprint
        data = request.json
        _, ws = _build_wb(data)
        wb_temp, ws = _build_wb(data)  # rebuild for column widths

        merged_map = {}
        for mc in ws.merged_cells.ranges:
            for r in range(mc.min_row, mc.max_row+1):
                for c in range(mc.min_col, mc.max_col+1):
                    if r == mc.min_row and c == mc.min_col:
                        merged_map[(r,c)] = (mc.max_row-mc.min_row+1, mc.max_col-mc.min_col+1)
                    else:
                        merged_map[(r,c)] = None

        def hex_color(color):
            if not color or color.type == 'theme': return None
            rgb = color.rgb
            if rgb and rgb != '00000000' and len(rgb) == 8:
                return '#' + rgb[2:]
            return None

        col_widths = {}
        for col_idx in range(ws.min_column, ws.max_column+1):
            letter = get_column_letter(col_idx)
            w = ws.column_dimensions[letter].width or 8
            col_widths[col_idx] = max(int(w * 7), 20)

        rows_html = ''
        for row_idx in range(ws.min_row, ws.max_row+1):
            row_h = ws.row_dimensions[row_idx].height or 15
            row_h_px = max(int(row_h * 1.33), 14)
            cells_html = ''
            for col_idx in range(ws.min_column, ws.max_column+1):
                if (row_idx, col_idx) in merged_map and merged_map[(row_idx,col_idx)] is None:
                    continue
                cell = ws.cell(row=row_idx, column=col_idx)
                span_attrs = ''
                if (row_idx, col_idx) in merged_map:
                    rs, cs = merged_map[(row_idx,col_idx)]
                    if rs > 1: span_attrs += f' rowspan="{rs}"'
                    if cs > 1: span_attrs += f' colspan="{cs}"'
                style = f'height:{row_h_px}px;'
                if cell.fill and cell.fill.fgColor:
                    bg = hex_color(cell.fill.fgColor)
                    if bg: style += f'background:{bg};'
                if cell.font:
                    if cell.font.bold: style += 'font-weight:bold;'
                    if cell.font.size: style += f'font-size:{max(int(cell.font.size),7)}px;'
                    if cell.font.color:
                        fc = hex_color(cell.font.color)
                        if fc: style += f'color:{fc};'
                align = cell.alignment.horizontal if cell.alignment else 'left'
                if align in ('center','right'): style += f'text-align:{align};'
                val = cell.value or ''
                if isinstance(val, str): val = val.replace('\n','<br>').replace('  ','&nbsp;&nbsp;')
                cells_html += f'<td{span_attrs} style="{style}padding:2px 4px;border:1px solid #ddd;overflow:hidden;">{val}</td>'
            rows_html += f'<tr>{cells_html}</tr>'

        col_css = ''.join(
            f'<col style="width:{col_widths.get(i,60)}px">'
            for i in range(ws.min_column, ws.max_column+1))

        page_css = '@page { size: A4 landscape; margin: 8mm; }'
        html = (f'<!DOCTYPE html><html><head><meta charset="UTF-8">'
                f'<style>{page_css} body{{font-family:Calibri,Arial,sans-serif;font-size:9px;margin:0}}'
                f'table{{border-collapse:collapse;width:100%;table-layout:fixed}}'
                f'td{{overflow:hidden;vertical-align:middle}}'
                f'.cert-stamp{{background:#e8f5e9;border:1px solid #1a5c2a;padding:4px;'
                f'font-size:7px;color:#1b5e20;border-radius:4px;}}</style></head>'
                f'<body><table>{col_css}<tbody>{rows_html}</tbody></table></body></html>')

        pdf_bytes = weasyprint.HTML(string=html).write_pdf()
        fname = f"REPORTE_{data.get('machineId','EQ')}_{data.get('fecha','').replace('/','-')}.pdf"
        return send_file(io.BytesIO(pdf_bytes), as_attachment=True,
                         download_name=fname, mimetype='application/pdf')
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# ── Cleanup endpoint ──────────────────────────────────────────────────────────

@app.route('/api/clear-reports', methods=['POST'])
def api_clear_reports():
    con = get_db()
    con.execute('DELETE FROM reports')
    con.commit()
    con.close()
    return jsonify({'ok': True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 3000)), debug=False)
