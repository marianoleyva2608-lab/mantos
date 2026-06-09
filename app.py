import os, io, base64, sqlite3, json, hashlib, secrets, uuid, threading, time
from datetime import datetime, timezone, timedelta
from flask import Flask, request, send_file, jsonify

from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend

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

try:
    from pyhanko.sign import signers, fields as sig_fields
    from pyhanko.sign.signers.pdf_signer import PdfSignatureMetadata
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.pdf_utils.reader import PdfFileReader
    PYHANKO_AVAILABLE = True
except ImportError:
    PYHANKO_AVAILABLE = False

from openpyxl.cell.cell import MergedCell as _MergedCell

def safe_write(ws, row, col, value):
    """Write to cell only if it is the master of a merged range (not a read-only slave)."""
    try:
        cell = ws.cell(row=row, column=col)
        if not isinstance(cell, _MergedCell):
            cell.value = value
    except Exception:
        pass

DB_PATH  = os.path.join(os.path.dirname(__file__), 'reports.db')
ORG_NAME = "AD-PACK"
CA_CN    = "AD-PACK Mantenimiento CA"
EMU      = 9525
MONTH_COLS = {"ENE":"B","FEB":"C","MAR":"D","ABR":"E","MAY":"F","JUN":"G",
              "JUL":"H","AGO":"I","SEP":"J","OCT":"K","NOV":"L","DIC":"M"}

# ── Signing sessions (5-minute TTL) ──────────────────────────────────────────
_signing_sessions = {}
_sessions_lock    = threading.Lock()

def _cleanup_sessions():
    now = time.time()
    with _sessions_lock:
        for k in [k for k,v in _signing_sessions.items() if v['expires'] < now]:
            del _signing_sessions[k]

def create_signing_session(key_pem, cert_pem, name, role):
    _cleanup_sessions()
    token = str(uuid.uuid4())
    with _sessions_lock:
        _signing_sessions[token] = {'key_pem':key_pem,'cert_pem':cert_pem,
                                    'name':name,'role':role,'expires':time.time()+300}
    return token

def get_signing_session(token):
    _cleanup_sessions()
    with _sessions_lock:
        return _signing_sessions.get(token)

# ── Database ─────────────────────────────────────────────────────────────────
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
            (id INTEGER PRIMARY KEY CHECK(id=1), cert_pem TEXT NOT NULL, key_pem TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cert_users
            (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, role TEXT NOT NULL,
             email TEXT UNIQUE NOT NULL, pin_hash TEXT NOT NULL,
             cert_pem TEXT NOT NULL, key_enc TEXT NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cert_signatures
            (id INTEGER PRIMARY KEY AUTOINCREMENT, report_id TEXT, role TEXT,
             user_name TEXT, cert_serial TEXT, sig_b64 TEXT, cert_pem TEXT, signed_at TEXT);
    ''')
    con.commit(); con.close()

init_db()

# ── PKI helpers ───────────────────────────────────────────────────────────────
def _now_utc(): return datetime.now(timezone.utc)
def _gen_key():
    return rsa.generate_private_key(public_exponent=65537,key_size=2048,backend=default_backend())
def _key_to_pem(key):
    return key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()
def _key_enc_pem(key, passphrase):
    return key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
                             serialization.BestAvailableEncryption(passphrase.encode())).decode()
def _load_key(pem, passphrase=None):
    pw = passphrase.encode() if passphrase else None
    return serialization.load_pem_private_key(pem.encode(), password=pw, backend=default_backend())
def _cert_to_pem(cert): return cert.public_bytes(serialization.Encoding.PEM).decode()
def _load_cert(pem):    return x509.load_pem_x509_certificate(pem.encode(), default_backend())
def _hash_pin(pin):     return hashlib.sha256(pin.encode()).hexdigest()

def _cert_info(cert):
    sub = cert.subject; iss = cert.issuer
    return {
        "cn":         sub.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
        "org":        (sub.get_attributes_for_oid(NameOID.ORGANIZATION_NAME) or [type('',(),{'value':ORG_NAME})()])[0].value,
        "serial":     format(cert.serial_number,'X'),
        "valid_from": cert.not_valid_before_utc.strftime("%d/%m/%Y"),
        "valid_to":   cert.not_valid_after_utc.strftime("%d/%m/%Y"),
        "issuer":     iss.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
        "fingerprint":cert.fingerprint(hashes.SHA256()).hex().upper()[:16],
    }

def generate_ca():
    key  = _gen_key()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,CA_CN),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME,ORG_NAME),
                      x509.NameAttribute(NameOID.COUNTRY_NAME,"MX")])
    now  = _now_utc()
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now).not_valid_after(now+timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True)
            .sign(key,hashes.SHA256(),default_backend()))
    return cert, key

def generate_user_cert(name, email, role, ca_cert, ca_key):
    key  = _gen_key()
    subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,name),
                      x509.NameAttribute(NameOID.EMAIL_ADDRESS,email),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME,ORG_NAME),
                      x509.NameAttribute(NameOID.COUNTRY_NAME,"MX")])
    now  = _now_utc()
    cert = (x509.CertificateBuilder().subject_name(subj).issuer_name(ca_cert.subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now).not_valid_after(now+timedelta(days=365*3))
            .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
            .add_extension(x509.KeyUsage(
                digital_signature=True,content_commitment=True,key_encipherment=False,
                data_encipherment=False,key_agreement=False,key_cert_sign=False,
                crl_sign=False,encipher_only=False,decipher_only=False),critical=True)
            .sign(ca_key,hashes.SHA256(),default_backend()))
    return cert, key

def sign_data(data_bytes, key_pem, passphrase):
    key = _load_key(key_pem, passphrase)
    sig = key.sign(data_bytes,padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                                          salt_length=padding.PSS.MAX_LENGTH),hashes.SHA256())
    return base64.b64encode(sig).decode()

def get_or_create_ca():
    con = get_db()
    row = con.execute('SELECT cert_pem,key_pem FROM ca_store WHERE id=1').fetchone()
    con.close()
    if row: return _load_cert(row['cert_pem']), _load_key(row['key_pem'])
    ca_cert, ca_key = generate_ca()
    con = get_db()
    con.execute('INSERT OR REPLACE INTO ca_store(id,cert_pem,key_pem) VALUES(1,?,?)',
                (_cert_to_pem(ca_cert),_key_to_pem(ca_key)))
    con.commit(); con.close()
    return ca_cert, ca_key

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__)

@app.route('/api/reports', methods=['GET'])
def api_get_reports():
    con  = get_db()
    rows = con.execute('SELECT data FROM reports ORDER BY id DESC').fetchall()
    con.close()
    return jsonify([json.loads(r['data']) for r in rows])

@app.route('/api/reports', methods=['POST'])
def api_save_report():
    r = request.json; con = get_db()
    con.execute('DELETE FROM reports WHERE machine_id=? AND fecha=?',(r.get('machineId',''),r.get('fecha','')))
    con.execute('INSERT INTO reports(id,machine_id,fecha,data) VALUES(?,?,?,?)',
                (r['id'],r.get('machineId',''),r.get('fecha',''),json.dumps(r)))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/reports/<int:report_id>', methods=['DELETE'])
def api_delete_report(report_id):
    con = get_db(); con.execute('DELETE FROM reports WHERE id=?',(report_id,)); con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/clear-reports', methods=['POST'])
def api_clear_reports():
    con = get_db(); con.execute('DELETE FROM reports'); con.commit(); con.close()
    return jsonify({'ok':True})

# ── PKI endpoints ─────────────────────────────────────────────────────────────
@app.route('/api/pki/ca-cert', methods=['GET'])
def api_ca_cert():
    ca_cert, _ = get_or_create_ca()
    return send_file(io.BytesIO(_cert_to_pem(ca_cert).encode()), as_attachment=True,
                     download_name='AD-PACK_CA.crt', mimetype='application/x-pem-file')

@app.route('/api/pki/create-user', methods=['POST'])
def api_create_user():
    try:
        d = request.json
        name,role,email,pin = d['name'].strip(),d['role'].strip(),d['email'].strip().lower(),d['pin']
        ca_cert, ca_key = get_or_create_ca()
        u_cert, u_key   = generate_user_cert(name, email, role, ca_cert, ca_key)
        cert_pem = _cert_to_pem(u_cert); key_enc = _key_enc_pem(u_key, pin)
        created  = _now_utc().strftime("%Y-%m-%d %H:%M:%S UTC")
        con = get_db()
        try:
            con.execute('INSERT INTO cert_users(name,role,email,pin_hash,cert_pem,key_enc,created) VALUES(?,?,?,?,?,?,?)',
                        (name,role,email,_hash_pin(pin),cert_pem,key_enc,created))
        except sqlite3.IntegrityError:
            con.execute('UPDATE cert_users SET name=?,role=?,pin_hash=?,cert_pem=?,key_enc=?,created=? WHERE email=?',
                        (name,role,_hash_pin(pin),cert_pem,key_enc,created,email))
        con.commit(); con.close()
        return jsonify({'ok':True,'cert':_cert_info(u_cert)})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error':str(e)}), 400

@app.route('/api/pki/users', methods=['GET'])
def api_list_users():
    con  = get_db()
    rows = con.execute('SELECT name,role,email,created,cert_pem FROM cert_users ORDER BY role,name').fetchall()
    con.close()
    return jsonify([{'name':r['name'],'role':r['role'],'email':r['email'],
                     'created':r['created'],'cert':_cert_info(_load_cert(r['cert_pem']))} for r in rows])

@app.route('/api/pki/sign', methods=['POST'])
def api_pki_sign():
    try:
        d         = request.json
        email     = d['email'].strip().lower()
        pin       = d['pin']
        report_id = d.get('report_id','')
        payload   = d.get('payload_json','')
        con = get_db()
        row = con.execute('SELECT * FROM cert_users WHERE email=?',(email,)).fetchone()
        con.close()
        if not row:           return jsonify({'error':'Usuario no encontrado'}), 404
        if row['pin_hash'] != _hash_pin(pin): return jsonify({'error':'PIN incorrecto'}), 401

        data_bytes = payload.encode() if payload else report_id.encode()
        sig_b64    = sign_data(data_bytes, row['key_enc'], pin)
        signed_at  = _now_utc().strftime("%d/%m/%Y %H:%M:%S UTC")
        cert       = _load_cert(row['cert_pem'])
        cert_info  = _cert_info(cert)

        con = get_db()
        con.execute('INSERT INTO cert_signatures(report_id,role,user_name,cert_serial,sig_b64,cert_pem,signed_at) VALUES(?,?,?,?,?,?,?)',
                    (report_id,row['role'],row['name'],cert_info['serial'],sig_b64,row['cert_pem'],signed_at))
        con.commit(); con.close()

        # Create signing session for PDF
        key_pem_plain  = _key_to_pem(_load_key(row['key_enc'], pin))
        session_token  = create_signing_session(key_pem_plain, row['cert_pem'], row['name'], row['role'])

        return jsonify({'ok':True,'cert_info':cert_info,'sig_b64':sig_b64,
                        'signed_at':signed_at,'role':row['role'],'name':row['name'],
                        'sign_session':session_token})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error':str(e)}), 400

@app.route('/api/pki/verify', methods=['POST'])
def api_pki_verify():
    try:
        d    = request.json
        cert = _load_cert(d['cert_pem'])
        sig  = base64.b64decode(d['sig_b64'])
        cert.public_key().verify(sig, d['payload_json'].encode(),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=padding.PSS.MAX_LENGTH),hashes.SHA256())
        return jsonify({'valid':True,'cert_info':_cert_info(cert)})
    except Exception as e:
        return jsonify({'valid':False,'error':str(e)}), 400

@app.route('/api/pki/user-cert/<email>', methods=['GET'])
def api_user_cert(email):
    con = get_db(); row = con.execute('SELECT cert_pem,name FROM cert_users WHERE email=?',(email.lower(),)).fetchone(); con.close()
    if not row: return jsonify({'error':'Not found'}), 404
    return send_file(io.BytesIO(row['cert_pem'].encode()), as_attachment=True,
                     download_name=f"{row['name'].replace(' ','_')}.crt", mimetype='application/x-pem-file')

@app.route('/')
def index():
    return open('index.html',encoding='utf-8').read(), 200, {'Content-Type':'text/html; charset=utf-8'}

# ── Excel / PDF generation ───────────────────────────────────────────────────
def _build_wb(data):
    file_key = data.get('file','termoformado')
    template = ('MTTO_Preventivo_Termoformado_2026.xlsx' if file_key=='termoformado'
                else 'MTTO_Preventivo_Conversion_2026.xlsx')
    wb = openpyxl.load_workbook(template); ws = wb[data['sheet']]
    for item in data.get('items',[]):
        row,st,cm = item['row'],item.get('status',''),item.get('comment','')
        safe_write(ws, row, 11, '( v )' if st=='ok' else '(   )')
        safe_write(ws, row, 12, '( v )' if st=='ng' else '(   )')
        if cm: safe_write(ws, row, 13, cm)
    cal_row = data.get('cal_data_row'); months = set(data.get('month',[]))
    if cal_row:
        for m,col in MONTH_COLS.items():
            safe_write(ws, cal_row, ord(col)-ord('A')+1, '( v )' if m in months else '(   )')
        v = data.get('voltaje',{})
        for col_n,key in [(14,'l1'),(15,'l2'),(16,'l3'),(17,'vac')]:
            if v.get(key): safe_write(ws, cal_row, col_n, v[key])
    sig_row = data.get('sig_row')
    if sig_row:
        # Técnico — col 2 (B) — celda fusionada master, incluir firma en mismo bloque
        tec_name = data.get('tecnico', '_______________')
        tec_cert  = data.get('certTecnico')
        if tec_cert:
            ci = tec_cert.get('cert_info', {})
            tec_text = (f"Realizó: {tec_name}\n\n"
                        f"Firma Digital X.509:\n"
                        f"{ci.get('cn','')}\n"
                        f"Serie: {ci.get('serial','')}\n"
                        f"Válido: {ci.get('valid_from','')} – {ci.get('valid_to','')}\n"
                        f"Fecha firma: {tec_cert.get('signed_at','')}")
        else:
            tec_text = f"Realizó: {tec_name}\n\nFirma: ___________________________"
        safe_write(ws, sig_row, 2, tec_text)

        safe_write(ws, sig_row, 8, f"Fecha: {data.get('fecha','_______________')}")

        # Supervisor — col 11 (K) — celda fusionada master
        sup_name = data.get('supervisor', '_______________')
        sup_cert  = data.get('certSupervisor')
        if sup_cert:
            ci = sup_cert.get('cert_info', {})
            sup_text = (f"Supervisor de Producción: {sup_name}\n\n"
                        f"Firma Digital X.509:\n"
                        f"{ci.get('cn','')}\n"
                        f"Serie: {ci.get('serial','')}\n"
                        f"Válido: {ci.get('valid_from','')} – {ci.get('valid_to','')}\n"
                        f"Fecha firma: {sup_cert.get('signed_at','')}")
        else:
            sup_text = f"Supervisor de Producción: {sup_name}\n\nFirma: _____________________"
        safe_write(ws, sig_row, 11, sup_text)

    if data.get('supComments') and sig_row:
        # Buscar primera fila libre después del bloque de firma (evitar celdas esclavas)
        comment_row = sig_row + 3
        safe_write(ws, comment_row, 2, f"Comentarios: {data['supComments']}")
    return wb, ws

@app.route('/generar', methods=['POST'])
def generar():
    try:
        data = request.json; wb,_ = _build_wb(data); buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        fname = f"REPORTE_{data.get('machineId','EQ')}_{data.get('fecha','').replace('/','-')}.xlsx"
        return send_file(buf,as_attachment=True,download_name=fname,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error':str(e)}), 500


def _adobe_stamp_html(cert_data, label):
    if not cert_data: return ''
    ci        = cert_data.get('cert_info',{})
    name      = ci.get('cn', cert_data.get('name',''))
    signed_at = cert_data.get('signed_at','')
    serial    = ci.get('serial','')
    issuer    = ci.get('issuer','')
    parts     = name.upper().split()
    name_html = '<br>'.join(filter(None,[
        parts[0] if len(parts)>0 else '',
        parts[1] if len(parts)>1 else '',
        ' '.join(parts[2:]) if len(parts)>2 else ''
    ]))
    try:
        dt = datetime.strptime(signed_at.replace(' UTC',''),'%d/%m/%Y %H:%M:%S')
        adobe_date = dt.strftime("%Y.%m.%d %H:%M:%S") + " -06'00'"
    except Exception:
        adobe_date = signed_at
    return (
        '<div style="display:inline-flex;align-items:stretch;border:1.5px solid #1a237e;'
        'border-radius:3px;background:#fff;margin:4px 8px 4px 0;min-width:280px;max-width:380px;'
        'overflow:hidden;font-family:Arial,sans-serif;vertical-align:top">'
        f'<div style="background:#fff;color:#1a237e;font-size:15px;font-weight:bold;font-style:italic;'
        f'padding:8px 10px;min-width:95px;display:flex;align-items:center;justify-content:center;'
        f'border-right:1.5px solid #c5cae9;line-height:1.25;text-align:center">{name_html}</div>'
        '<div style="width:14px;background:repeating-linear-gradient(135deg,transparent,transparent 4px,'
        'rgba(26,35,126,.15) 4px,rgba(26,35,126,.15) 5px);flex-shrink:0"></div>'
        f'<div style="padding:6px 10px;font-size:8px;color:#212121;line-height:1.6;flex:1">'
        f'<div style="color:#1a237e;font-size:7.5px">Firmado digitalmente por</div>'
        f'<div style="font-size:9.5px;font-weight:bold;color:#0d47a1;margin:1px 0">{name}</div>'
        f'<div>Fecha: {adobe_date}</div>'
        f'<div style="color:#555;font-size:7px">Serie: {serial}</div>'
        f'<div style="color:#388e3c;font-size:6.5px;margin-top:2px">✔ Firma X.509 — AD-PACK</div>'
        '</div></div>'
    )


@app.route('/generar_pdf', methods=['POST'])
def generar_pdf():
    try:
        from xhtml2pdf import pisa
        data = request.json; _, ws = _build_wb(data)

        # Build HTML table from worksheet
        merged_map = {}
        for mc in ws.merged_cells.ranges:
            for r in range(mc.min_row,mc.max_row+1):
                for c in range(mc.min_col,mc.max_col+1):
                    merged_map[(r,c)] = (mc.max_row-mc.min_row+1,mc.max_col-mc.min_col+1) if (r==mc.min_row and c==mc.min_col) else None

        def hx(color):
            if not color or color.type=='theme': return None
            rgb=color.rgb
            return '#'+rgb[2:] if rgb and rgb!='00000000' and len(rgb)==8 else None

        col_widths = {i: max(int((ws.column_dimensions[get_column_letter(i)].width or 8)*7),20)
                      for i in range(ws.min_column,ws.max_column+1)}

        rows_html = ''
        for ri in range(ws.min_row,ws.max_row+1):
            rh = max(int((ws.row_dimensions[ri].height or 15)*1.33),14)
            ch = ''
            for ci in range(ws.min_column,ws.max_column+1):
                if merged_map.get((ri,ci)) is None: continue
                cell = ws.cell(row=ri,column=ci)
                sa   = ''
                if merged_map.get((ri,ci)):
                    rs2,cs2 = merged_map[(ri,ci)]
                    if rs2>1: sa+=f' rowspan="{rs2}"'
                    if cs2>1: sa+=f' colspan="{cs2}"'
                st = f'height:{rh}px;'
                if cell.fill and cell.fill.fgColor:
                    bg=hx(cell.fill.fgColor)
                    if bg: st+=f'background:{bg};'
                if cell.font:
                    if cell.font.bold: st+='font-weight:bold;'
                    if cell.font.size: st+=f'font-size:{max(int(cell.font.size),7)}px;'
                    if cell.font.color:
                        fc=hx(cell.font.color)
                        if fc: st+=f'color:{fc};'
                al = cell.alignment.horizontal if cell.alignment else 'left'
                if al in ('center','right'): st+=f'text-align:{al};'
                val = cell.value or ''
                if isinstance(val,str): val=val.replace('\n','<br>').replace('  ','&nbsp;&nbsp;')
                ch += f'<td{sa} style="{st}padding:2px 4px;border:1px solid #ddd;overflow:hidden;">{val}</td>'
            rows_html += f'<tr>{ch}</tr>'

        col_css = ''.join(f'<col style="width:{col_widths.get(i,60)}px">' for i in range(ws.min_column,ws.max_column+1))

        tec_cert = data.get('certTecnico')
        sup_cert = data.get('certSupervisor')
        sigs_html = ''
        if tec_cert or sup_cert:
            sigs_html = (
                '<div style="margin:10px 0 2px;border-top:1px solid #e0e0e0;padding-top:8px;'
                'display:flex;align-items:flex-start;flex-wrap:wrap;gap:4px">'
                '<div style="font-size:8px;font-weight:bold;color:#546e7a;width:100%;margin-bottom:4px">'
                'FIRMAS DIGITALES &mdash; Certificados X.509 AD-PACK</div>'
                + _adobe_stamp_html(tec_cert,'Tecnico')
                + _adobe_stamp_html(sup_cert,'Supervisor')
                + '</div>'
            )

        html = (
            '<!DOCTYPE html><html><head><meta charset="UTF-8">'
            '<style>@page{size:A4 landscape;margin:8mm}'
            'body{font-family:Calibri,Arial,sans-serif;font-size:9px;margin:0}'
            'table{border-collapse:collapse;width:100%;table-layout:fixed}'
            'td{overflow:hidden;vertical-align:middle}'
            '</style></head>'
            f'<body><table>{col_css}<tbody>{rows_html}</tbody></table>{sigs_html}</body></html>'
        )

        pdf_buf = io.BytesIO()
        pisa_status = pisa.CreatePDF(html, dest=pdf_buf)
        if pisa_status.err:
            return jsonify({'error': 'Error generando PDF'}), 500
        pdf_bytes = pdf_buf.getvalue()

        # pyhanko cryptographic signing (if available + session exists)
        if PYHANKO_AVAILABLE:
            sess_tok = data.get('signSessionTec') or data.get('signSessionSup')
            if sess_tok:
                sess = get_signing_session(sess_tok)
                if sess:
                    try: pdf_bytes = _pyhanko_sign(pdf_bytes,sess['key_pem'],sess['cert_pem'],sess['name'])
                    except Exception as e: print(f"[pyhanko] skipped: {e}")

        fname = f"REPORTE_{data.get('machineId','EQ')}_{data.get('fecha','').replace('/','-')}.pdf"
        return send_file(io.BytesIO(pdf_bytes),as_attachment=True,download_name=fname,mimetype='application/pdf')
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error':str(e)}), 500


def _pyhanko_sign(pdf_bytes, key_pem, cert_pem, signer_name):
    key      = serialization.load_pem_private_key(key_pem.encode(),password=None,backend=default_backend())
    cert_obj = x509.load_pem_x509_certificate(cert_pem.encode(),default_backend())
    signer   = signers.SimpleSigner(signing_cert=cert_obj,signing_key=key,
                                    cert_registry=signers.SimpleCertificateStore())
    buf = io.BytesIO(pdf_bytes); r = PdfFileReader(buf); w = IncrementalPdfFileWriter(buf)
    sig_fields.append_signature_field(w,sig_field_spec=sig_fields.SigFieldSpec(
        sig_field_name='FirmaDigital',on_page=0,box=(400,20,780,80)))
    meta = PdfSignatureMetadata(field_name='FirmaDigital',name=signer_name,
                                reason='Mantenimiento Preventivo AD-PACK',
                                location='AD-PACK — Leon, Gto. Mexico')
    out = io.BytesIO()
    signers.sign_pdf(w,signature_meta=meta,signer=signer,output=out)
    return out.getvalue()


if __name__ == '__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',3000)),debug=False)


# ══════════════════════════════════════════════════════════════════════════════
#  e.firma SAT → CSD interno AD-PACK
# ══════════════════════════════════════════════════════════════════════════════

from cryptography.hazmat.primitives.serialization import load_der_private_key
from cryptography.x509 import load_der_x509_certificate as load_der_cert

SAT_ISSUERS = ["SAT970701NN3", "AC SAT", "FIEL", "SAT"]

def _validate_efirma(cer_bytes: bytes, key_bytes: bytes, password: str) -> dict:
    """
    Valida la e.firma SAT.
    Retorna dict con info del certificado o lanza excepción.
    """
    # 1. Cargar certificado (.cer DER)
    try:
        cert = load_der_cert(cer_bytes)
    except Exception:
        raise ValueError("Archivo .cer inválido o corrupto")

    # 2. Cargar llave privada (.key DER cifrado)
    try:
        key = load_der_private_key(key_bytes, password=password.encode())
    except ValueError:
        raise ValueError("Contraseña incorrecta o archivo .key inválido")

    # 3. Verificar que la llave corresponde al certificado
    pub_cert = cert.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    pub_key  = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    if pub_cert != pub_key:
        raise ValueError("La llave .key no corresponde al certificado .cer")

    # 4. Verificar vigencia
    now = datetime.now(timezone.utc)
    if now < cert.not_valid_before_utc:
        raise ValueError("El certificado aún no es válido")
    if now > cert.not_valid_after_utc:
        raise ValueError(f"Certificado vencido desde {cert.not_valid_after_utc.strftime('%d/%m/%Y')}")

    # 5. Verificar emisor SAT
    try:
        issuer_cn = cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    except Exception:
        issuer_cn = ""
    is_sat = any(s.upper() in issuer_cn.upper() for s in SAT_ISSUERS)
    # También aceptar si el serial del emisor tiene el RFC del SAT
    try:
        issuer_serial = cert.issuer.get_attributes_for_oid(NameOID.SERIAL_NUMBER)[0].value
        if "SAT970701NN3" in issuer_serial.upper():
            is_sat = True
    except Exception:
        pass

    # 6. Extraer RFC y nombre del titular
    try:
        nombre = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    except Exception:
        nombre = ""
    try:
        rfc = cert.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER)[0].value
    except Exception:
        rfc = ""

    return {
        "nombre":      nombre,
        "rfc":         rfc,
        "serial":      format(cert.serial_number, 'X'),
        "valid_from":  cert.not_valid_before_utc.strftime("%d/%m/%Y"),
        "valid_to":    cert.not_valid_after_utc.strftime("%d/%m/%Y"),
        "issuer":      issuer_cn,
        "is_sat":      is_sat,
        "_key":        key,   # objeto llave (no se guarda)
    }


@app.route('/api/efirma/validate', methods=['POST'])
def api_efirma_validate():
    """
    Solo valida la e.firma y devuelve la info del titular.
    Body: multipart/form-data con campos cer, key, password.
    """
    try:
        cer_bytes = request.files['cer'].read()
        key_bytes = request.files['key'].read()
        password  = request.form.get('password', '')
        info = _validate_efirma(cer_bytes, key_bytes, password)
        info.pop('_key', None)
        return jsonify({'ok': True, 'efirma': info})
    except ValueError as e:
        return jsonify({'error': str(e)}), 401
    except Exception as e:
        return jsonify({'error': f'Error inesperado: {e}'}), 500


@app.route('/api/efirma/create-csd', methods=['POST'])
def api_efirma_create_csd():
    """
    Usa la e.firma SAT para autenticar al administrador y generar:
      - CA interna AD-PACK (si no existe)
      - Certificados de usuario (CSD internos) para los usuarios listados.

    Body: multipart/form-data:
      cer      — archivo .cer de la e.firma
      key      — archivo .key de la e.firma
      password — contraseña de la e.firma
      users    — JSON: [{"name":"...","email":"...","role":"...","pin":"..."}]
    """
    try:
        cer_bytes = request.files['cer'].read()
        key_bytes = request.files['key'].read()
        password  = request.form.get('password', '')
        users_raw = request.form.get('users', '[]')
        users     = json.loads(users_raw)

        # ── 1. Validar e.firma ────────────────────────────────────────────────
        try:
            efirma_info = _validate_efirma(cer_bytes, key_bytes, password)
        except ValueError as e:
            return jsonify({'error': str(e)}), 401

        # ── 2. Regenerar / obtener CA interna ─────────────────────────────────
        # Si ya existe CA, la regeneramos firmada por la e.firma del admin
        # (prueba de que fue autorizada por el titular de la e.firma)
        efirma_key  = efirma_info.pop('_key')
        efirma_cert = load_der_cert(cer_bytes)

        ca_cert, ca_key = get_or_create_ca()

        # ── 3. Crear/actualizar usuarios con CSD ──────────────────────────────
        created_users = []
        for u in users:
            uname = u.get('name','').strip()
            uemail= u.get('email','').strip().lower()
            urole = u.get('role','tecnico')
            upin  = u.get('pin','')
            if not uname or not uemail or not upin:
                continue
            u_cert, u_key = generate_user_cert(uname, uemail, urole, ca_cert, ca_key)
            cert_pem = _cert_to_pem(u_cert)
            key_enc  = _key_enc_pem(u_key, upin)
            created  = _now_utc().strftime("%Y-%m-%d %H:%M:%S UTC")
            con = get_db()
            try:
                con.execute(
                    'INSERT INTO cert_users(name,role,email,pin_hash,cert_pem,key_enc,created) VALUES(?,?,?,?,?,?,?)',
                    (uname, urole, uemail, _hash_pin(upin), cert_pem, key_enc, created))
            except sqlite3.IntegrityError:
                con.execute(
                    'UPDATE cert_users SET name=?,role=?,pin_hash=?,cert_pem=?,key_enc=?,created=? WHERE email=?',
                    (uname, urole, _hash_pin(upin), cert_pem, key_enc, created, uemail))
            con.commit(); con.close()
            created_users.append({
                'name': uname, 'role': urole, 'email': uemail,
                'cert': _cert_info(u_cert)
            })

        return jsonify({
            'ok': True,
            'autorizado_por': {
                'nombre': efirma_info['nombre'],
                'rfc':    efirma_info['rfc'],
                'serial': efirma_info['serial'],
                'emisor': efirma_info['issuer'],
                'es_sat': efirma_info['is_sat'],
            },
            'ca_serial': format(ca_cert.serial_number, 'X'),
            'usuarios_creados': created_users,
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500
