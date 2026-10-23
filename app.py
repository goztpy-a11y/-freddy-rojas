import os, json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from io import BytesIO
from flask import Flask, request, redirect, url_for, session, render_template_string, flash, abort, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "development-only-change-me")
app.config["ADMIN_CONFIGURED"] = bool(os.environ.get("ADMIN_PASSWORD"))
db_url = os.environ.get("DATABASE_URL", "sqlite:///freddy_rojas_demo.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
db = SQLAlchemy(app)

AREAS = {
 "admin": "Administración", "caja": "Caja", "tesoreria": "Tesorería",
 "estacion": "Estación de servicio", "gomeria": "Gomería",
 "inventario": "Inventario", "auditoria": "Auditoría"
}
MODULES = {
 "clientes": ("Proveedores", "caja", [
  ("nombre","Nombre / razón social","text",True),("documento","RUC / documento","text",False),
  ("telefono","Teléfono","text",False),("direccion","Dirección","text",False),
  ("datos_bancarios","Datos bancarios del cliente (no cuenta de la empresa)","text",False)]),
 "materiales": ("Materiales", "admin", [("nombre","Nombre del material","text",True)]),
 "inventario": ("Inventario de materiales", "inventario", [
  ("nombre","Nombre del material","text",True),("cantidad","Cantidad disponible","number",True)]),
 "tickets": ("Tickets de entrada", "caja", [
  ("cliente","Cliente / proveedor","text",True),("material","Material","text",True),
  ("cantidad","Cantidad / kg","number",True),("precio","Precio aplicado (automático al elegir material)","number",False),
  ("total","Total calculado","number",False),("cuenta_cliente","Cuenta bancaria del cliente elegida para el pago","text",False),
  ("observaciones","Observaciones","text",False)]),
 "solicitudes": ("Solicitudes de pago", "caja", [
  ("cliente","Cliente / proveedor","text",True),("concepto","Concepto / ticket relacionado","text",True),
  ("importe","Importe solicitado","number",True),("cuenta_cliente","Cuenta bancaria del cliente","text",True),
  ("comprobante","Referencia del comprobante / archivo pendiente","text",False),("observaciones","Observaciones","text",False)]),
 "cuentas_empresa": ("Cuentas bancarias de El Toro S.A.", "admin", [
  ("nombre","Nombre de la cuenta","text",True),("banco","Banco","text",True),("numero","Número / alias de cuenta","text",True),
  ("moneda","Moneda (PYG / USD)","text",True),("saldo_inicial","Saldo inicial","number",True)]),
 "gastos": ("Gastos", "caja", [
  ("fecha","Fecha del gasto","date",True),("categoria","Categoría","text",True),("detalle","Detalle completo","text",True),
  ("importe","Importe","number",True),("medio","Medio de pago / cuenta utilizada","text",False),("comprobante","Comprobante","text",False)]),
 "ventas": ("Venta", "inventario", [
  ("fecha","Fecha","date",True),("destino","Empresa / destino","text",True),("material","Material","text",True),
  ("cantidad","Kilogramos","number",True),("chofer","Chofer","text",True),("camion","Camión","text",True)]),
 "cuentas_pagar": ("Cuentas por pagar", "tesoreria", [
  ("beneficiario","Beneficiario","text",True),("concepto","Concepto","text",True),("importe","Importe adeudado","number",True),
  ("vencimiento","Vencimiento","date",False),("cheque_adelantado","Incluye cheque adelantado","checkbox",False)]),
 "cuentas_cobrar": ("Cuentas por cobrar", "tesoreria", [
  ("cliente","Cliente","text",True),("concepto","Concepto","text",True),("importe","Importe por cobrar","number",True),
  ("vencimiento","Vencimiento","date",False),("estado","Estado / seguimiento","select",False)]),
 "cheques": ("Cheques adelantados", "tesoreria", [
  ("beneficiario","Beneficiario","text",True),("numero","Número de cheque","text",True),("importe","Importe","number",True),
  ("fecha","Fecha del cheque","date",True),("vencimiento","Fecha de vencimiento","date",True),("estado","Estado","select",True)]),
 "combustible": ("Combustible por camión", "estacion", [
  ("camion","Camión / chapa / código","text",True),("litros","Cantidad cargada (litros)","number",True),
  ("fecha","Fecha y hora de carga","datetime-local",True),("responsable","Responsable","text",False)]),
 "gomeria": ("Gomería y servicios", "gomeria", [
  ("fecha","Fecha","date",True),("camion","Camión / chapa / código","text",True),("servicio","Tipo de servicio","select",True),
  ("detalle","Descripción del trabajo","text",True),("cantidad","Cantidad (si aplica)","number",False),("costo","Costo pagado (Gs., opcional)","number",False),
  ("responsable","Responsable","text",False),("observaciones","Observaciones","text",False)]),
 "repuestos": ("Inventario de repuestos hidráulicos", "inventario", [
  ("nombre","Repuesto","text",True),("codigo","Código / referencia","text",False),("stock","Stock disponible","number",True),
  ("stock_minimo","Stock mínimo","number",False),("ubicacion","Ubicación","text",False)]),
 "movimientos_stock": ("Movimientos de stock", "inventario", [
  ("repuesto","Repuesto","text",True),("tipo","Movimiento (entrada / uso / salida)","select",True),
  ("cantidad","Cantidad","number",True),("motivo","Motivo / camión / trabajo relacionado","text",True)]),
 "auditoria": ("Revisión y auditoría", "auditoria", [
  ("referencia","Ticket / transferencia / proveedor / hoja","text",True),("verificacion","Qué se verificó","text",True),
  ("resultado","Resultado (correcto / observado)","text",True),("observaciones","Observaciones y diferencias","text",False)])
}

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default="caja")
    areas = db.Column(db.Text, nullable=False, default="caja")
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class Material(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, unique=True)
    price = db.Column(db.Numeric(16, 2), nullable=False, default=0)
    wholesale_price = db.Column(db.Numeric(16, 2), nullable=True)
    unit = db.Column(db.String(30), nullable=False, default="kg")
    stock = db.Column(db.Numeric(16, 3), nullable=False, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class CompanyAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    bank = db.Column(db.String(120), nullable=False)
    number = db.Column(db.String(180), nullable=False)
    currency = db.Column(db.String(10), nullable=False, default="PYG")
    opening_balance = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    balance = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class Record(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    module = db.Column(db.String(40), nullable=False, index=True)
    title = db.Column(db.String(220), nullable=False)
    data = db.Column(db.Text, nullable=False, default="{}")
    amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default="Registrado")
    company_account_id = db.Column(db.Integer, db.ForeignKey("company_account.id"))
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    approved_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    paid_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    action = db.Column(db.String(80), nullable=False)
    module = db.Column(db.String(40), nullable=False)
    record_id = db.Column(db.Integer)
    detail = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

with app.app_context():
    db.create_all()
    from sqlalchemy import inspect
    if "material" in inspect(db.engine).get_table_names():
        cols = {c["name"] for c in inspect(db.engine).get_columns("material")}
        if "wholesale_price" not in cols:
            with db.engine.begin() as conn:
                conn.exec_driver_sql("ALTER TABLE material ADD COLUMN wholesale_price NUMERIC(16, 2)")
    initial_password = os.environ.get("ADMIN_PASSWORD")
    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    if initial_password and not User.query.filter_by(username=admin_username).first():
        db.session.add(User(username=admin_username,
            password_hash=generate_password_hash(initial_password), role="admin", areas=",".join(AREAS.keys())))
        db.session.commit()
    # Cuentas iniciales por área. No se sobrescriben cuentas existentes.
    for username, area in [("caja","caja"),("tesoreria","tesoreria"),("estacion","estacion"),("gomeria","gomeria"),("inventario","inventario"),("auditoria","auditoria")]:
        if not User.query.filter_by(username=username).first():
            db.session.add(User(username=username, password_hash=generate_password_hash("12345678910"),
                role=area, areas=area, active=True))
    db.session.commit()

def current_user():
    uid = session.get("uid")
    return db.session.get(User, uid) if uid else None

def log_action(action, module, record_id=None, detail=""):
    db.session.add(AuditLog(user_id=current_user().id if current_user() else None,
        action=action, module=module, record_id=record_id, detail=detail[:2000]))

def allowed(module):
    user = current_user()
    if not user:
        return False
    if user.role == "admin":
        return True
    # Las cuentas normales acceden solo a los módulos de las áreas asignadas.
    assigned = {area.strip() for area in (user.areas or "").split(",") if area.strip()}
    required_area = MODULES.get(module, (None, module))[1]
    return required_area in assigned

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        if current_user().role != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapper

BASE = """
<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }} · Freddy Rojas</title><style>
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;color:#182536;background:#f3f6fa;font-synthesis:none;text-rendering:optimizeLegibility}
*{box-sizing:border-box}html{min-height:100%;background:#f3f6fa}body{margin:0;min-height:100vh;background:#f3f6fa;color:#182536;font-size:14px;line-height:1.5}
a{color:#2459a9;text-decoration:none}a:hover{color:#153d7a;text-decoration:underline}
header{position:fixed;z-index:30;top:0;left:258px;right:0;height:78px;background:#fff;color:#182536;padding:0 30px;display:flex;justify-content:space-between;gap:16px;align-items:center;border-bottom:1px solid #e3e9f1;box-shadow:0 3px 14px rgba(24,37,54,.035)}
header>div:first-child{display:flex;align-items:center;gap:12px}header strong{font-size:18px;font-weight:750;letter-spacing:-.4px;color:#152b47}header .small{font-size:12px;color:#7a8798;margin-top:1px}header a{color:#2459a9;font-weight:650}
.sidebar{position:fixed;z-index:40;inset:0 auto 0 0;width:258px;background:#142b46;color:#d8e3f2;padding:23px 15px 20px;overflow-y:auto;box-shadow:5px 0 22px rgba(17,35,57,.08)}
.sidebar-brand{padding:5px 10px 24px;margin-bottom:17px;border-bottom:1px solid rgba(255,255,255,.12);display:flex;gap:12px;align-items:center}
.brand-mark{width:40px;height:40px;border-radius:12px;background:linear-gradient(145deg,#4e8ce7,#2860b5);display:grid;place-items:center;color:#fff;font-size:17px;font-weight:850;box-shadow:0 5px 13px #0b1d34}
.brand-copy strong{display:block;color:white;font-size:15px;letter-spacing:.1px}.brand-copy span{display:block;color:#9fb3cc;font-size:11px;margin-top:2px}
nav{display:flex;flex-direction:column;gap:5px;margin:0}
nav a{display:flex;align-items:center;min-height:41px;padding:10px 12px;border-radius:8px;color:#c5d3e5;font-size:13px;font-weight:550;line-height:1.3;transition:background .15s,color .15s}
nav a:hover{background:rgba(255,255,255,.08);color:white;text-decoration:none}
nav a:first-child{margin-bottom:7px;background:rgba(83,139,220,.17);color:#fff}
main{max-width:none;margin:0 0 0 258px;padding:106px 30px 34px;min-height:100vh}
body:not(:has(.sidebar)) header{left:0}
body:not(:has(.sidebar)) main{margin-left:0;max-width:1120px;margin-right:auto;padding:110px 20px 34px}
.card{background:#fff;border:1px solid #e4eaf1;border-radius:13px;padding:22px;margin:0 0 18px;box-shadow:0 4px 16px rgba(25,45,72,.035)}
h1,h2,h3,h4{color:#172d49;line-height:1.25;letter-spacing:-.35px}h2{font-size:21px;font-weight:750;margin:0 0 17px}h3{font-size:15px;font-weight:700;margin:0 0 10px}p{margin:8px 0 13px}.muted{color:#748297}.small{font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(225px,1fr));gap:15px}
label{display:block;font-size:12px;color:#46566b;font-weight:700;margin:12px 0 6px;letter-spacing:.1px}
input,select,textarea{width:100%;padding:11px 12px;border:1px solid #d6dee8;border-radius:8px;font:inherit;font-size:13px;color:#1c2d43;background:#fff;outline:none;transition:border-color .15s,box-shadow .15s}
input:focus,select:focus,textarea:focus{border-color:#4a82d4;box-shadow:0 0 0 3px rgba(63,124,211,.12)}
input::placeholder,textarea::placeholder{color:#9aa7b7}
button,.btn{background:#245bb0;color:#fff;padding:10px 15px;border-radius:8px;border:1px solid #245bb0;display:inline-flex;align-items:center;justify-content:center;gap:7px;font-size:13px;font-weight:700;cursor:pointer;transition:background .15s,border-color .15s,transform .15s;min-height:38px}
button:hover,.btn:hover{background:#19478f;border-color:#19478f;color:white;text-decoration:none}
button:active,.btn:active{transform:translateY(1px)}
.actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.actions input{min-width:105px;max-width:180px}
table{width:100%;border-collapse:separate;border-spacing:0;background:#fff;font-size:13px}
th,td{text-align:left;padding:12px 13px;border-bottom:1px solid #e9eef4;vertical-align:top;overflow-wrap:anywhere}
th{background:#f5f8fc;color:#506078;font-size:11px;text-transform:uppercase;letter-spacing:.45px;font-weight:800;white-space:nowrap}
tr:last-child td{border-bottom:0}tbody tr:hover td{background:#fafcff}
.card:has(table){overflow-x:auto}
.warn{background:#fff7e5;border:1px solid #f2dfb2;color:#79561a;padding:13px 15px;border-radius:9px}
.danger{color:#b42332;font-weight:650}.ok{color:#19734a;font-weight:650}
.flash{background:#eaf7ef;border:1px solid #ccebd7;color:#216a3c;padding:12px 15px;border-radius:9px;margin:0 0 16px;font-size:13px}
footer{text-align:center;color:#8290a2;padding:24px 12px;font-size:11px}
section.card>p:first-of-type{margin-top:0}
/* Eliminar textos auxiliares pequeños en todas las pantallas; conservar etiquetas y avisos importantes */
.muted,.small,.brand-copy span,footer{display:none!important}
/* Acabado empresarial: jerarquía visual, navegación y panel ejecutivo */
body{letter-spacing:.05px}
header>div:last-child{background:#f3f6fb;border:1px solid #e5ebf3;border-radius:999px;padding:8px 13px;font-size:12px;color:#40536c;font-weight:650}
header>div:last-child a{margin-left:4px}
.sidebar{background:linear-gradient(180deg,#132b47 0%,#10243c 100%)}
.sidebar-brand{padding-bottom:20px}
.brand-mark{border-radius:11px;background:linear-gradient(145deg,#69a4fa,#2b63bd);font-size:16px}
nav a{border:1px solid transparent;min-height:42px}
nav a:first-child{border-color:rgba(125,174,244,.2)}
nav a:hover{transform:translateX(2px)}
main>section:first-of-type>h2{font-size:25px;letter-spacing:-.7px;margin-bottom:20px}
main>section.card>h2{display:flex;align-items:center;gap:10px}
main>section.card>h2:before{content:"";display:block;width:4px;height:23px;border-radius:4px;background:#3676cc}
.grid{gap:16px}
.grid>.card{position:relative;overflow:hidden;border-radius:14px;border-color:#e0e8f2;box-shadow:0 6px 20px rgba(24,49,79,.045);transition:transform .18s,box-shadow .18s}
.grid>.card:hover{transform:translateY(-2px);box-shadow:0 10px 24px rgba(24,49,79,.09)}
.grid>.card h3{font-size:13px;text-transform:uppercase;letter-spacing:.45px;color:#65758b}
.grid>.card>strong{display:block;font-size:34px;line-height:1.15;letter-spacing:-1px;color:#183c68;margin:8px 0 13px}
.grid>.card p a{font-size:12px;font-weight:750;display:inline-flex;align-items:center;gap:6px;background:#edf4ff;padding:8px 11px;border-radius:7px}
.grid>.card p a:hover{background:#dceaff;text-decoration:none}
table{border:1px solid #e6ecf3;border-radius:10px;overflow:hidden}
th{padding-top:13px;padding-bottom:13px}
td{color:#35465c}
tbody tr:hover td{background:#f4f8fe}
label{font-size:13px;color:#34465d}
input,select,textarea{font-size:14px;min-height:42px}
button,.btn{min-height:41px;box-shadow:0 2px 5px rgba(36,91,176,.12)}
.flash{font-weight:650}
@media(max-width:900px){header>div:last-child{padding:6px 9px;font-size:11px}nav a:hover{transform:none}main>section:first-of-type>h2{font-size:22px}}
@media(max-width:520px){header>div:last-child{max-width:58%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}main>section:first-of-type>h2{font-size:21px}.grid>.card>strong{font-size:30px}}

@media(max-width:900px){header{left:0;height:68px;padding:0 16px}.sidebar{position:relative;top:68px;width:100%;height:auto;max-height:none;padding:10px 12px;display:block}.sidebar-brand{display:none}nav{flex-direction:row;overflow-x:auto;gap:6px;padding-bottom:3px}nav a{white-space:nowrap;min-height:37px;padding:9px 11px;font-size:12px}nav a:first-child{margin-bottom:0}main{margin-left:0;padding:94px 15px 24px}body:not(:has(.sidebar)) main{padding:94px 15px 24px}.card{padding:17px;margin-bottom:14px}h2{font-size:19px}}
@media(max-width:520px){header{height:64px;padding:0 12px}header strong{font-size:16px}header .small{display:none}header>div:last-child{font-size:11px}.sidebar{top:64px}main{padding:88px 10px 18px}.grid{grid-template-columns:1fr}.card{border-radius:10px;padding:15px}table{min-width:650px}th,td{padding:10px}.actions input{max-width:100%;min-width:0}}
@media print{.sidebar,header,button,.btn,form,nav,.flash{display:none!important}body{background:#fff!important;color:#000!important;font-size:11pt}main,body:not(:has(.sidebar)) main{margin:0!important;padding:0!important;max-width:none!important}.card{box-shadow:none!important;border:0!important;padding:8px!important;break-inside:avoid}table{width:100%;font-size:9pt}th,td{padding:5px;border:1px solid #bbb!important}th{background:#eee!important;color:#000!important}a{color:#000!important;text-decoration:none!important}.inventory-qty{font-size:24pt;font-weight:800}}.inventory-list table{font-size:17px}.inventory-list th,.inventory-list td{padding:16px 18px}.inventory-qty{font-size:25px;font-weight:800;color:#183c68}
.nav-caption{margin:17px 11px 5px;color:#89a5c5;font-size:10px;font-weight:800;letter-spacing:1.5px}
.sidebar{background:linear-gradient(180deg,#102844 0%,#17395f 100%);border-right:1px solid rgba(255,255,255,.08)}
nav{gap:4px}nav a{min-height:42px;border:1px solid transparent;border-radius:9px;letter-spacing:.05px}
nav a:hover{background:rgba(255,255,255,.09);border-color:rgba(255,255,255,.08)}
nav a:first-child{background:rgba(90,151,235,.19);border-color:rgba(127,177,245,.16)}
header{backdrop-filter:blur(12px);background:rgba(255,255,255,.96)}
.card{border-color:#e1e8f1;border-radius:15px;box-shadow:0 7px 24px rgba(20,45,75,.045)}
button,.btn{border-radius:9px;transition:transform .15s,box-shadow .15s}
button:hover,.btn:hover{transform:translateY(-1px);box-shadow:0 5px 12px rgba(21,61,113,.14)}
input,select,textarea{border-radius:9px!important;border-color:#d5deea!important;min-height:40px}
input:focus,select:focus,textarea:focus{outline:3px solid rgba(52,117,205,.15);border-color:#4a83cc!important}
.area-hero{padding:30px 32px;background:linear-gradient(120deg,#fff 0%,#f1f6fd 100%);border-color:#dce7f5;margin-bottom:22px}
.area-eyebrow{font-size:10px;font-weight:850;letter-spacing:1.7px;color:#3268a9;margin-bottom:10px}
.area-hero h1{font-size:clamp(25px,3vw,34px);margin:0 0 8px;letter-spacing:-1px}
.area-hero p{font-size:14px;color:#65768b;max-width:680px;margin:0 0 19px}
.area-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}
.area-link{display:flex;align-items:center;gap:14px;min-height:92px;padding:17px 18px;border:1px solid #e0e8f2;border-radius:13px;background:#fff;color:#1b304a;box-shadow:0 4px 14px rgba(22,48,78,.035);transition:transform .16s,border-color .16s,box-shadow .16s}
.area-link:hover{transform:translateY(-2px);border-color:#b8cce6;box-shadow:0 10px 24px rgba(22,48,78,.08);text-decoration:none}
.area-link-icon{width:40px;height:40px;display:grid;place-items:center;flex-shrink:0;border-radius:12px;background:#edf4fd;color:#2d63a7;font-weight:850;font-size:13px}
.area-link-copy{display:flex;flex-direction:column;gap:4px;min-width:0}
.area-link-copy strong{font-size:14px;color:#1c3452}
.area-link-copy small{font-size:12px;line-height:1.4;color:#738399}
.area-arrow{margin-left:auto;font-size:19px;color:#7e9abc}
@media(max-width:700px){.area-grid{grid-template-columns:1fr}.area-hero{padding:23px 20px}.area-link{min-height:78px}.nav-caption{display:none}}
/* Acabado profesional de la plataforma Freddy Rojas */
:root{--fr-navy:#12263f;--fr-blue:#2864ad;--fr-teal:#168d93;--fr-line:#e1e8f0}
html,body{background:#f4f7fb}
header{height:74px;box-shadow:0 2px 12px rgba(16,38,63,.045);border-bottom-color:#e3eaf2;padding:0 28px}
header strong{font-size:19px;letter-spacing:-.55px;color:var(--fr-navy)}
.sidebar{background:linear-gradient(180deg,#12263f 0%,#183654 100%);width:252px;padding:22px 14px}
.sidebar-brand{padding:6px 9px 23px;margin-bottom:18px}
.brand-mark{width:42px;height:42px;border-radius:12px;background:linear-gradient(145deg,#27a4a6,#2864ad);box-shadow:0 5px 14px rgba(5,20,40,.24);font-size:15px;letter-spacing:.5px}
.brand-copy strong{font-size:14px;letter-spacing:.7px}
nav{gap:4px}
nav a{min-height:42px;padding:10px 12px;border-radius:9px;border:1px solid transparent;color:#d0dcec;font-size:13px}
nav a:first-child{margin-bottom:0;background:transparent;border-color:transparent;color:#d0dcec}
nav a:hover{background:rgba(255,255,255,.075);border-color:rgba(255,255,255,.07);transform:none}
.card{border:1px solid var(--fr-line);border-radius:14px;box-shadow:0 5px 18px rgba(23,47,76,.035);padding:23px}
h1,h2,h3,h4{color:var(--fr-navy)}
main>section:first-of-type>h2{font-size:26px;letter-spacing:-.8px}
main>section.card>h2:before{background:linear-gradient(180deg,#24a4a5,#3476c0)}
label{font-size:12px;letter-spacing:.1px;color:#3c5068}
input,select,textarea{border-color:#d7e0eb!important;border-radius:9px!important;min-height:43px}
input:focus,select:focus,textarea:focus{border-color:#3987bc!important;box-shadow:0 0 0 3px rgba(36,139,161,.12);outline:0}
button,.btn{background:#245fa8;border-color:#245fa8;border-radius:9px;min-height:41px;padding:10px 15px;box-shadow:none}
button:hover,.btn:hover{background:#194b86;border-color:#194b86;box-shadow:0 4px 10px rgba(26,75,134,.15)}
table{border-color:#e4ebf3;border-radius:10px;font-variant-numeric:tabular-nums}
th{background:#f3f7fb;color:#53667d;font-size:10px;letter-spacing:.65px;padding:13px 14px}
td{padding:13px 14px;color:#31455e}
tbody tr:hover td{background:#f5f9fc}
.flash{background:#ecf8f4;border-color:#ccebe1;color:#176a59;border-radius:10px}
@media(max-width:900px){header{height:68px;padding:0 16px}.sidebar{width:100%;padding:9px 12px}main{margin-left:0;padding:94px 15px 24px}}
@media(max-width:520px){header{height:64px;padding:0 12px}header strong{font-size:16px}.sidebar{padding:8px 10px}main{padding:88px 10px 18px}.card{padding:15px}}

/* Panel principal: indicadores y accesos de trabajo */
.dashboard-heading,.section-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
.dashboard-heading h2{font-size:28px;margin:2px 0 7px}.dashboard-heading p{margin:0;color:#718198}
.dashboard-heading .eyebrow{font-size:10px;font-weight:850;letter-spacing:1.6px;color:#3975c5}
.dashboard-date{padding:9px 13px;background:#f3f7fc;border:1px solid #e1eaf5;border-radius:9px;color:#415873;font-weight:750}
.dashboard-metrics{grid-template-columns:repeat(auto-fit,minmax(185px,1fr));margin-top:22px}
.dashboard-metrics>.metric-card{margin:0;padding:19px;border-top:3px solid #3978c9}
.metric-card>span{display:block;color:#66778d;font-size:12px;font-weight:750}
.metric-card>strong{display:block;font-size:34px;line-height:1.2;color:#183b65;margin:9px 0}
.metric-card>small{display:block;color:#8290a2;font-size:11px}
.metric-card>a{display:inline-block;margin-top:7px;font-size:12px;font-weight:750}
.section-heading{margin-bottom:16px}.section-heading h2{margin:0}.section-heading>a{font-size:12px;font-weight:750}
.quick-action-grid{grid-template-columns:repeat(auto-fit,minmax(230px,1fr))}
.quick-action{display:flex;align-items:center;gap:12px;min-height:78px;padding:14px;background:#fff;border:1px solid #e2eaf3;border-radius:11px;color:#1e3654;transition:transform .15s,border-color .15s,box-shadow .15s}
.quick-action:hover{transform:translateY(-2px);border-color:#a9c5ea;box-shadow:0 7px 18px rgba(29,67,112,.07);text-decoration:none}
.quick-action-icon{display:grid;place-items:center;flex:0 0 37px;height:37px;border-radius:10px;background:#eaf2ff;color:#2e67b7;font-size:20px;font-weight:800}
.quick-action>span:nth-child(2){flex:1;min-width:0}.quick-action strong,.quick-action small{display:block}
.quick-action strong{font-size:13px;color:#213d60}.quick-action small{font-size:11px;color:#7b899a;margin-top:3px}
.quick-action>b{color:#4279bf;font-size:16px}
.status-pill{display:inline-block;padding:4px 8px;border-radius:999px;background:#edf3fb;color:#385c87;font-size:11px;font-weight:750}
.table-wrap{overflow-x:auto}
@media(max-width:520px){.dashboard-heading h2{font-size:23px}.dashboard-date{font-size:12px}.dashboard-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.dashboard-metrics>.metric-card{padding:13px}.metric-card>strong{font-size:28px}.quick-action-grid{grid-template-columns:1fr}}

/* Refinamiento visual solicitado: panel de gestión empresarial */
.dashboard-overview{background:linear-gradient(135deg,#ffffff 0%,#f1f7fc 68%,#eaf5f6 100%);border-color:#dce7f2;position:relative;overflow:hidden}
.dashboard-overview:after{content:"";position:absolute;right:-58px;top:-88px;width:230px;height:230px;border-radius:50%;background:radial-gradient(circle,rgba(36,139,161,.10),rgba(36,139,161,0));pointer-events:none}
.dashboard-heading,.dashboard-metrics{position:relative;z-index:1}
.dashboard-heading .eyebrow{display:inline-flex;align-items:center;gap:8px;padding:6px 9px;border-radius:6px;background:#e7f2fa;color:#2864ad;letter-spacing:1.35px}
.dashboard-heading h2{font-size:clamp(25px,3vw,32px);margin-top:9px}
.dashboard-metrics>.metric-card{position:relative;border:1px solid #e1e9f2;border-top:0;border-left:4px solid #3978c9;border-radius:12px;box-shadow:0 5px 18px rgba(20,45,75,.045);transition:transform .16s,box-shadow .16s}
.dashboard-metrics>.metric-card:hover{transform:translateY(-2px);box-shadow:0 10px 22px rgba(20,45,75,.09)}
.dashboard-metrics>.metric-card:nth-child(4n+2){border-left-color:#15949a}
.dashboard-metrics>.metric-card:nth-child(4n+3){border-left-color:#7a68c4}
.dashboard-metrics>.metric-card:nth-child(4n+4){border-left-color:#d69a36}
.metric-card>strong{font-variant-numeric:tabular-nums;letter-spacing:-1px}
.dashboard-actions .section-heading>span{font-size:12px;color:#7a899c}
.quick-action{border-color:#e0e8f1;box-shadow:0 3px 12px rgba(20,45,75,.025)}
.quick-action:nth-child(4n+2) .quick-action-icon{background:#e5f6f3;color:#137c78}
.quick-action:nth-child(4n+3) .quick-action-icon{background:#f0edfc;color:#6854b1}
.quick-action:nth-child(4n+4) .quick-action-icon{background:#fff3df;color:#a96c16}
#ultimos-movimientos table th:first-child{border-top-left-radius:8px}
#ultimos-movimientos table th:last-child{border-top-right-radius:8px}
.status-pill{white-space:nowrap}
@media(max-width:520px){.dashboard-overview{padding:16px}.dashboard-heading{align-items:flex-start}.dashboard-heading>div:first-child{min-width:0}.dashboard-heading p{font-size:13px}.dashboard-metrics>.metric-card{min-width:0}.metric-card>span{font-size:11px}.quick-action{padding:12px}}


/* Nueva composición de panel y navegación operativa */
.fr-welcome{display:flex;justify-content:space-between;align-items:center;gap:25px;min-height:190px;padding:30px 34px;margin:0 0 24px;border-radius:18px;background:linear-gradient(115deg,#132b46 0%,#1d4567 65%,#176d73 100%);color:#fff;position:relative;overflow:hidden;box-shadow:0 12px 30px rgba(18,43,70,.12)}
.fr-welcome-copy{position:relative;z-index:2}.fr-kicker{display:block;font-size:10px;font-weight:850;letter-spacing:1.5px;color:#7890a9;margin-bottom:9px}.fr-welcome .fr-kicker{color:#a9d6d9}.fr-welcome h1{color:#fff;font-size:clamp(25px,3vw,35px);letter-spacing:-1px;line-height:1.12;margin:0 0 10px}.fr-welcome p{color:#d3e0eb;font-size:13px;max-width:520px;margin:0 0 17px}.fr-welcome-meta{display:flex;align-items:center;gap:8px;font-size:11px;color:#d4e3ee}.fr-live-dot,.fr-state-ok i{display:inline-block;width:7px;height:7px;border-radius:50%;background:#52d6b1}.fr-meta-separator{opacity:.55}.fr-welcome-symbol{width:155px;height:155px;flex:0 0 155px;border:1px solid rgba(255,255,255,.17);border-radius:50%;display:grid;place-items:center;position:relative;background:rgba(255,255,255,.055)}.fr-welcome-symbol span{font-size:43px;font-weight:850;letter-spacing:-3px;color:rgba(255,255,255,.92)}.fr-welcome-symbol i,.fr-welcome-symbol b{position:absolute;display:block;border:1px solid rgba(133,225,220,.38);border-radius:50%;width:190px;height:190px}.fr-welcome-symbol b{width:225px;height:225px;border-color:rgba(255,255,255,.11)}
.fr-dashboard-layout{display:grid;grid-template-columns:minmax(0,1fr) 265px;gap:22px;align-items:start}.fr-dashboard-primary{min-width:0}.fr-section-block{margin:0 0 26px}.fr-section-title{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;margin:0 0 15px;flex-wrap:wrap}.fr-section-title .fr-kicker{margin:0 0 5px;color:#68809a}.fr-section-title h2{font-size:21px;letter-spacing:-.5px;margin:0;color:#182e48}.fr-section-note{font-size:11px;color:#8290a2}.fr-date-chip{font-size:11px;color:#5b7188;padding:7px 10px;background:#fff;border:1px solid #e0e8f0;border-radius:8px}
.fr-stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:12px}.fr-stat{background:#fff;border:1px solid #e1e8f0;border-radius:13px;padding:16px;min-width:0;box-shadow:0 3px 12px rgba(20,44,70,.025)}.fr-stat-icon{width:34px;height:34px;display:grid;place-items:center;border-radius:10px;font-size:17px;font-weight:800;margin-bottom:15px}.fr-icon-blue{background:#e8f0fc;color:#2867b0}.fr-icon-teal{background:#e4f5f1;color:#168579}.fr-icon-amber{background:#fff2dd;color:#a76c14}.fr-icon-violet{background:#f0ecfb;color:#6c59b2}.fr-stat-label{font-size:11px;font-weight:700;color:#6c7e92;line-height:1.4}.fr-stat>strong{display:block;font-size:30px;line-height:1.15;color:#183753;letter-spacing:-.9px;margin:7px 0}.fr-stat small{display:block;color:#8a98a8;font-size:10px;line-height:1.4}.fr-stat>a{display:inline-block;margin-top:5px;font-size:10px;font-weight:800;color:#2b69a9}.fr-stat>a b{margin-left:3px}
.fr-area-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px}.fr-area-card{display:flex;align-items:center;gap:12px;min-width:0;background:#fff;border:1px solid #e1e8f0;border-radius:13px;padding:14px 13px;transition:transform .16s,border-color .16s,box-shadow .16s}.fr-area-card:hover{transform:translateY(-2px);border-color:#b7ccdf;box-shadow:0 8px 18px rgba(20,44,70,.06);text-decoration:none}.fr-area-symbol{display:grid;place-items:center;width:39px;height:39px;flex:0 0 39px;border-radius:11px;font-size:17px}.fr-area-copy{display:flex;flex-direction:column;gap:4px;min-width:0}.fr-area-copy strong{font-size:12px;color:#243c55}.fr-area-copy small{font-size:10px;line-height:1.4;color:#7c8da0}.fr-area-arrow{margin-left:auto;color:#8ba0b4;font-size:17px}
.fr-action-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.fr-action-card{position:relative;display:flex;flex-direction:column;gap:6px;min-height:90px;padding:15px;background:#fff;border:1px solid #e1e8f0;border-radius:12px;transition:transform .16s,border-color .16s}.fr-action-card:hover{transform:translateY(-2px);border-color:#b8cfe4;text-decoration:none}.fr-action-card strong{font-size:12px;color:#263f58;padding-right:22px}.fr-action-card small{font-size:10px;line-height:1.4;color:#8090a2}.fr-action-arrow{position:absolute;right:13px;top:13px;color:#3373b3;font-size:16px}
.fr-dashboard-rail{display:flex;flex-direction:column;gap:14px}.fr-rail-card{background:#fff;border:1px solid #e1e8f0;border-radius:14px;padding:19px;box-shadow:0 3px 12px rgba(20,44,70,.025)}.fr-rail-profile{text-align:center;padding-top:22px}.fr-profile-avatar{display:grid;place-items:center;width:52px;height:52px;margin:0 auto 14px;border-radius:16px;background:linear-gradient(140deg,#1c9a9a,#2e68ad);color:#fff;font-size:21px;font-weight:850}.fr-rail-card .fr-kicker{font-size:9px;margin-bottom:7px}.fr-rail-card h3{font-size:15px;margin:0 0 5px;color:#1c354e}.fr-rail-card p{font-size:11px;line-height:1.6;color:#7b8b9e;margin:0 0 12px}.fr-profile-divider,.fr-rail-divider{height:1px;background:#edf1f5;margin:16px 0}.fr-profile-row{display:flex;justify-content:space-between;gap:8px;margin-top:11px;text-align:left;font-size:10px}.fr-profile-row span{color:#7d8da0}.fr-profile-row strong{color:#3a5067}.fr-state-ok{display:flex;align-items:center;gap:6px}.fr-state-ok i{width:6px;height:6px}.fr-rail-link{display:flex;justify-content:space-between;gap:8px;align-items:center;font-size:11px;font-weight:800;color:#2867a9}.fr-view-all{font-size:11px;font-weight:800;color:#2867a9}.fr-activity-block{padding:22px;background:#fff;border:1px solid #e1e8f0;border-radius:15px}.fr-empty-state{display:flex;flex-direction:column;align-items:center;text-align:center;padding:30px 12px;color:#8191a3}.fr-empty-state>span{display:grid;place-items:center;width:43px;height:43px;border-radius:13px;background:#f0f4f8;color:#7289a0;font-size:22px;margin-bottom:12px}.fr-empty-state strong{font-size:13px;color:#435970}.fr-empty-state p{font-size:11px;margin:5px 0 0}
@media(max-width:1100px){.fr-dashboard-layout{grid-template-columns:minmax(0,1fr) 230px;gap:15px}.fr-stat-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.fr-area-grid{grid-template-columns:1fr}}
@media(max-width:820px){.fr-dashboard-layout{grid-template-columns:1fr}.fr-dashboard-rail{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.fr-area-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.fr-welcome{min-height:160px}}
@media(max-width:560px){.fr-welcome{padding:22px 18px;min-height:0;margin-bottom:20px}.fr-welcome-symbol{width:68px;height:68px;flex-basis:68px;border-radius:20px}.fr-welcome-symbol span{font-size:23px;letter-spacing:-1px}.fr-welcome-symbol i,.fr-welcome-symbol b{display:none}.fr-welcome h1{font-size:25px}.fr-welcome p{font-size:12px}.fr-welcome-meta{font-size:10px;flex-wrap:wrap}.fr-dashboard-layout{gap:5px}.fr-stat-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.fr-stat{padding:12px}.fr-stat-icon{margin-bottom:10px}.fr-stat>strong{font-size:27px}.fr-area-grid,.fr-action-grid{grid-template-columns:1fr}.fr-dashboard-rail{grid-template-columns:1fr}.fr-section-title h2{font-size:19px}.fr-activity-block{padding:14px}}

/* Rediseño integral: estilo de panel empresarial de Freddy Rojas */
:root{--fr-ink:#172b45;--fr-muted:#6c7c91;--fr-blue:#2865ad;--fr-teal:#15969a;--fr-border:#e2eaf3;--fr-bg:#f3f6fa;--fr-white:#fff}
html,body{background:var(--fr-bg);color:var(--fr-ink)}
header{left:252px;height:76px;padding:0 30px;background:rgba(255,255,255,.97);border-bottom:1px solid var(--fr-border);box-shadow:0 2px 12px rgba(23,43,69,.035)}
header>div:first-child{gap:14px}
header strong{font-size:19px;font-weight:800;letter-spacing:-.55px;color:var(--fr-ink)}
header>div:last-child{background:#f5f8fc;border:1px solid var(--fr-border);border-radius:10px;padding:8px 12px;color:#51647c;font-size:12px}
header .print-page{min-height:31px;padding:5px 10px;font-size:11px}
.sidebar{width:252px;padding:24px 14px;background:linear-gradient(180deg,#112840 0%,#193b5d 100%);border-right:1px solid rgba(255,255,255,.08);box-shadow:3px 0 18px rgba(15,36,59,.05)}
.sidebar-brand{padding:4px 9px 23px;margin-bottom:18px;gap:12px;border-bottom:1px solid rgba(255,255,255,.13)}
.brand-mark{width:42px;height:42px;border-radius:12px;background:linear-gradient(145deg,#23a4a6,#2e6bb6);box-shadow:0 5px 14px rgba(0,0,0,.17)}
.brand-copy strong{font-size:14px;letter-spacing:.7px}
.brand-copy span{display:block!important;font-size:10px;letter-spacing:1.15px;color:#a8bed4}
nav{gap:5px}
.nav-caption{display:block;margin:21px 11px 7px;color:#83a6ca;font-size:10px;letter-spacing:1.35px}
nav a,nav a:first-child{min-height:43px;padding:11px 13px;border:1px solid transparent;border-radius:9px;background:transparent;color:#d0dceb;font-size:13px;font-weight:600;transition:background .15s,border-color .15s}
nav a:first-child{margin-bottom:2px}
nav a:hover{background:rgba(255,255,255,.085);border-color:rgba(255,255,255,.07);color:#fff;transform:none}
main{margin-left:252px;padding:108px 30px 36px;min-height:100vh;max-width:none}
.card{background:var(--fr-white);border:1px solid var(--fr-border);border-radius:15px;padding:24px;margin-bottom:20px;box-shadow:0 5px 18px rgba(22,46,75,.035)}
h1,h2,h3,h4{color:var(--fr-ink)}
h2{font-size:21px;font-weight:780;letter-spacing:-.55px;margin:0 0 20px}
section.card>h2{display:flex;align-items:center;gap:11px}
section.card>h2:before{content:"";width:4px;height:23px;flex:0 0 4px;border-radius:5px;background:linear-gradient(180deg,var(--fr-teal),#3476c0)}
h3{font-size:15px;font-weight:750}
.grid{gap:16px}
label{margin:13px 0 7px;font-size:12px;font-weight:750;color:#3c5068}
input,select,textarea{min-height:43px;padding:10px 12px;background:#fff;border:1px solid #d7e1ec!important;border-radius:9px!important;color:#233952;font-size:13px;box-shadow:none;transition:border-color .15s,box-shadow .15s}
input:focus,select:focus,textarea:focus{outline:0;border-color:#4392ad!important;box-shadow:0 0 0 3px rgba(21,150,154,.12)}
input::placeholder,textarea::placeholder{color:#9aa8b8}
button,.btn{min-height:40px;padding:10px 15px;border:1px solid var(--fr-blue);border-radius:9px;background:var(--fr-blue);color:#fff;font-size:12px;font-weight:750;box-shadow:none;transition:background .15s,transform .15s,box-shadow .15s}
button:hover,.btn:hover{background:#1d4e87;border-color:#1d4e87;box-shadow:0 4px 11px rgba(40,101,173,.15);transform:translateY(-1px);text-decoration:none}
.actions{gap:9px}
table{border:1px solid var(--fr-border);border-radius:11px;border-spacing:0;overflow:hidden;font-size:12px}
th{padding:14px 13px;background:#f1f5fa;color:#5a6d83;border-bottom:1px solid #dfe7f0;font-size:10px;letter-spacing:.65px;font-weight:850}
td{padding:13px;color:#344960;border-bottom:1px solid #eaf0f5}
tbody tr:hover td{background:#f5f9fd}
tr:last-child td{border-bottom:0}
.card:has(table){overflow-x:auto}
.flash{border-radius:10px;background:#eaf7f3;border:1px solid #cbeae0;color:#176e5d;font-weight:650;margin-bottom:18px}
.warn{border-radius:10px}
.dashboard-overview{padding:29px 30px;background:linear-gradient(125deg,#fff 0%,#f1f6fc 68%,#e9f6f5 100%);border:1px solid #dce7f2;position:relative;overflow:hidden}
.dashboard-overview:after{content:"";position:absolute;right:-50px;top:-95px;width:245px;height:245px;border-radius:50%;background:radial-gradient(circle,rgba(21,150,154,.12),rgba(21,150,154,0));pointer-events:none}
.dashboard-heading,.dashboard-metrics{position:relative;z-index:1}
.dashboard-heading{align-items:flex-start}
.dashboard-heading .eyebrow{display:inline-flex;background:#e6f3f5;border-radius:6px;padding:6px 9px;color:#187f88;font-size:10px;font-weight:850;letter-spacing:1.5px}
.dashboard-heading h2{font-size:clamp(26px,3vw,34px);margin:9px 0 7px;letter-spacing:-1px}
.dashboard-heading p{color:#6b7c91}
.dashboard-date{background:#fff;border:1px solid #dfe8f1;border-radius:9px;padding:9px 13px;color:#405975;font-size:12px}
.dashboard-metrics{grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-top:22px}
.dashboard-metrics>.metric-card{margin:0;padding:19px;border:1px solid #e0e8f1;border-left:4px solid #3478c6;border-radius:12px;background:#fff;box-shadow:0 5px 15px rgba(23,49,79,.04);transition:transform .16s,box-shadow .16s}
.dashboard-metrics>.metric-card:nth-child(4n+2){border-left-color:#15969a}
.dashboard-metrics>.metric-card:nth-child(4n+3){border-left-color:#7968c1}
.dashboard-metrics>.metric-card:nth-child(4n+4){border-left-color:#d69a36}
.dashboard-metrics>.metric-card:hover{transform:translateY(-2px);box-shadow:0 9px 22px rgba(23,49,79,.08)}
.metric-card>span{font-size:11px;letter-spacing:.2px;color:#64778d}
.metric-card>strong{font-size:34px;color:#173d67;letter-spacing:-1.1px;margin:10px 0}
.metric-card>a{font-size:11px;color:#2865ad;font-weight:800}
.dashboard-actions{padding:24px}
.section-heading{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-bottom:17px}
.section-heading h2{margin:0}
.section-heading>span{color:#7b8ba0;font-size:11px}
.quick-action-grid{grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.quick-action{min-height:78px;padding:14px;border:1px solid #e1e9f2;border-radius:12px;background:#fff;box-shadow:0 3px 11px rgba(22,46,75,.025);transition:transform .15s,border-color .15s,box-shadow .15s}
.quick-action:hover{transform:translateY(-2px);border-color:#b4cbe5;box-shadow:0 8px 18px rgba(22,46,75,.07)}
.quick-action-icon{width:39px;height:39px;flex-basis:39px;border-radius:11px;background:#e9f1ff;color:#2d66b2}
.quick-action:nth-child(4n+2) .quick-action-icon{background:#e3f5f1;color:#147d76}
.quick-action:nth-child(4n+3) .quick-action-icon{background:#f0edfc;color:#6c58b5}
.quick-action:nth-child(4n+4) .quick-action-icon{background:#fff3df;color:#a86d18}
.quick-action strong{font-size:12px}.quick-action small{color:#77889d;font-size:10px}
.status-pill{padding:5px 9px;background:#edf4fb;color:#3d618a;border-radius:999px;font-size:10px;font-weight:800}
.table-wrap{overflow-x:auto}
footer{display:block!important;color:#8b99aa}
@media(max-width:900px){header{left:0;height:66px;padding:0 17px}.sidebar{position:fixed;top:66px;bottom:auto;width:100%;height:auto;max-height:112px;padding:8px 11px;overflow-x:auto;overflow-y:hidden;box-shadow:0 4px 12px rgba(15,36,59,.06)}.sidebar-brand,.nav-caption{display:none!important}nav{flex-direction:row;overflow-x:auto;gap:6px;padding-bottom:2px}nav a,nav a:first-child{white-space:nowrap;min-height:36px;padding:8px 11px;margin:0}main{margin-left:0;padding:130px 17px 28px}body:not(:has(.sidebar)) main{padding:90px 17px 28px}.card{padding:19px}.dashboard-overview{padding:24px}}
@media(max-width:520px){header{height:62px;padding:0 11px}header strong{font-size:16px}header>div:last-child{padding:5px 7px;font-size:10px;max-width:63%;white-space:nowrap;overflow:hidden}header .print-page{display:none}.sidebar{top:62px;max-height:98px;padding:7px 8px}nav a,nav a:first-child{font-size:11px;min-height:34px;padding:7px 9px}main{padding:116px 10px 20px}body:not(:has(.sidebar)) main{padding:82px 10px 20px}.card{padding:15px;border-radius:12px;margin-bottom:13px}h2{font-size:18px}.dashboard-overview{padding:16px}.dashboard-heading h2{font-size:23px}.dashboard-heading p{font-size:12px}.dashboard-metrics{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.dashboard-metrics>.metric-card{padding:12px}.metric-card>span{font-size:10px}.metric-card>strong{font-size:27px}.quick-action-grid{grid-template-columns:1fr}.quick-action{min-height:70px;padding:11px}table{min-width:650px}th,td{padding:10px}.grid{gap:10px}}
@media print{.sidebar,header,button,.btn,form,nav{display:none!important}footer{display:none!important}}
</style></head><body><header><div><strong>Freddy Rojas</strong><div class="small">Plataforma de gestión empresarial</div></div>
<div>{% if user %}<span>{{ user.username }} · {{ AREAS.get(user.role,user.role) }}</span> · <button class="print-page" type="button" onclick="window.print()">Imprimir</button> · <a href="{{ url_for('logout') }}">Cerrar sesión</a>{% endif %}</div></header>
{% if user %}<aside class="sidebar"><div class="sidebar-brand"><div class="brand-mark">FR</div><div class="brand-copy"><strong>FREDDY ROJAS</strong><span>GESTIÓN EMPRESARIAL</span></div></div>
<nav><a href="{{url_for('index')}}">⌂ &nbsp; Panel principal</a>
{% if user.role=='admin' or allowed('caja') or allowed('tesoreria') or allowed('estacion') or allowed('gomeria') or allowed('inventario') or allowed('auditoria') %}<a href="{{url_for('reports')}}">Informes</a><a href="{{url_for('general_history')}}">Historial</a>{% endif %}
{% if user.role=='admin' %}
<div class="nav-caption">ÁREAS DE TRABAJO</div>
<a href="{{url_for('admin_section',section='caja')}}">▣ &nbsp; Caja</a><a href="{{url_for('admin_section',section='estacion')}}">⛽ &nbsp; Estación de servicio</a><a href="{{url_for('admin_section',section='gomeria')}}">⚙ &nbsp; Gomería</a><a href="{{url_for('admin_section',section='inventario')}}">▤ &nbsp; Inventario</a><a href="{{url_for('admin_section',section='tesoreria')}}">◇ &nbsp; Tesorería</a><a href="{{url_for('admin_section',section='auditoria')}}">✓ &nbsp; Auditoría</a><a href="{{url_for('admin_section',section='administracion')}}">⚙ &nbsp; Administración</a>
<a href="{{url_for('proveedores')}}">＋ &nbsp; Agregar proveedor</a><a href="{{url_for('module_page',module='materiales')}}">＋ &nbsp; Agregar material</a>
{% else %}
{% if allowed('caja') %}<a href="{{url_for('pagos_diarios')}}">Pagos diarios</a><a href="{{url_for('prestamos')}}">Préstamos</a><a href="{{url_for('proveedores')}}">Proveedores y precios</a><a href="{{url_for('listado_proveedores')}}">Proveedores</a><a href="{{url_for('planillas')}}">Cuenta de proveedores</a><a href="{{url_for('fletes')}}">Fletes</a><a href="{{url_for('caja_chica')}}">Caja chica</a>{% endif %}
{% if allowed('estacion') %}<a href="{{url_for('flota')}}">Camiones y retiros</a><a href="{{url_for('combustible_stock')}}">Stock y cargas de combustible</a><a href="{{url_for('mantenimiento')}}">Mantenimiento de flota</a>{% endif %}
{% if allowed('tesoreria') %}<a href="{{url_for('module_page',module='pagos_cuentas')}}">Movimientos de pagos</a><a href="{{url_for('module_page',module='cobros_cuentas')}}">Cobros de cuentas</a>{% endif %}
{% if allowed('gomeria') %}<a href="{{url_for('gomeria_camiones')}}">Gomería por camión</a><a href="{{url_for('module_page',module='gomeria')}}">Servicios de gomería</a>{% endif %}
{% if allowed('auditoria') %}<a href="{{url_for('auditoria_pagos')}}">Auditoría de pagos</a>{% endif %}
{% for key,meta in MODULES.items() %}{% if key not in ['pagos_diarios','prestamos','prestamos_pagos','pagos_cuentas','cobros_cuentas','proveedores','planillas','flota','combustible_stock','combustible_camion','mantenimiento','gomeria_camiones','fletes','caja_chica'] and allowed(key) %}<a href="{{url_for('module_page',module=key)}}">{{meta[0]}}</a>{% endif %}{% endfor %}
{% if user.role=='admin' %}<a href="{{url_for('users')}}">Usuarios y permisos</a><a href="{{url_for('access_report')}}">Informe de accesos</a><a href="{{url_for('backup_export')}}">Exportar respaldo</a><a href="{{url_for('change_password')}}">Mi contraseña</a>{% endif %}
{% endif %}
{% if user.role!='admin' and allowed('tesoreria') %}<a href="{{url_for('approvals')}}">Autorizaciones y pagos autorizados</a>{% endif %}
</nav></aside>{% endif %}
<main>{% with messages=get_flashed_messages() %}{% for m in messages %}<div class="flash">{{m}}</div>{% endfor %}{% endwith %}
"""

@app.context_processor
def inject_globals():
    return {"user": current_user(), "AREAS": AREAS, "MODULES": MODULES, "now": datetime.now(), "allowed": allowed}

@app.get("/health")
def health():
    return {"status":"ok","app":"freddy-rojas","database":"configured" if os.environ.get("DATABASE_URL") else "demo-sqlite"}

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = User.query.filter_by(username=request.form.get("username","").strip(), active=True).first()
        if u and check_password_hash(u.password_hash, request.form.get("password","")):
            session.clear(); session["uid"] = u.id
            log_action("inicio de sesión","usuarios",u.id)
            db.session.commit()
            return redirect(request.args.get("next") or url_for("index"))
        flash("Usuario o contraseña incorrectos.")
    return render_template_string(BASE + """
    <section class="card" style="max-width:430px;margin:35px auto"><h2>Iniciar sesión</h2>
    {% if not config.get('ADMIN_CONFIGURED') and not user %}<p class="warn">El administrador inicial se configura en Render mediante ADMIN_USERNAME y ADMIN_PASSWORD. No existe una contraseña pública predeterminada.</p>{% endif %}
    <form method="post"><label>Usuario</label><input name="username" autocomplete="username" required>
    <label>Contraseña</label><input name="password" type="password" autocomplete="current-password" required>
    <p><button class="btn" type="submit">Entrar</button></p></form></section></main><footer>Freddy Rojas · Cada registro conserva usuario y fecha/hora</footer></body></html>""", title="Acceso")

@app.get("/logout")
def logout():
    if current_user():
        log_action("cerrar sesión","usuarios",current_user().id); db.session.commit()
    session.clear()
    return redirect(url_for("login"))

@app.get("/")
@login_required
def index():
    u = current_user()
    visible_modules = [key for key in MODULES if allowed(key)]
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = Record.query.filter(Record.module.in_(visible_modules), Record.created_at >= today_start).count() if visible_modules else 0
    records = Record.query.filter(Record.module.in_(visible_modules)).order_by(Record.created_at.desc()).limit(8).all() if u.role == "admin" and visible_modules else []
    pending = Record.query.filter_by(module="solicitudes",status="Pendiente de autorización").count() if (u.role == "admin" or allowed("tesoreria")) else 0
    accounts = CompanyAccount.query.filter_by(active=True).all() if u.role == "admin" else []
    material_count = Material.query.count() if u.role == "admin" or allowed("inventario") else None
    active_users = User.query.filter_by(active=True).count() if u.role == "admin" else None
    quick_actions = []
    if u.role == "admin" or allowed("caja"):
        quick_actions += [
            ("Registrar pago", url_for("pagos_diarios"), "Cargar un pago o movimiento"),
            ("Proveedores y precios", url_for("proveedores"), "Consultar y actualizar precios"),
            ("Caja chica", url_for("caja_chica"), "Revisar saldo y registrar gastos")]
    if u.role == "admin" or allowed("estacion"):
        quick_actions += [
            ("Camiones y retiros", url_for("flota"), "Consultar flota y retiros"),
            ("Combustible", url_for("combustible_stock"), "Ver existencias y cargas"),
            ("Mantenimiento", url_for("mantenimiento"), "Registrar servicios de flota")]
    if u.role == "admin":
        quick_actions += [
            ("Informes", url_for("reports"), "Consultar e imprimir informes"),
            ("Usuarios", url_for("users"), "Administrar accesos y permisos")]
    elif allowed("auditoria"):
        quick_actions.append(("Auditoría de pagos", url_for("auditoria_pagos"), "Revisar operaciones"))
    return render_template_string(BASE + """
    <section class="fr-welcome">
      <div class="fr-welcome-copy">
        <span class="fr-kicker">FREDDY ROJAS / CENTRO DE OPERACIONES</span>
        <h1>Buen día, {{user.username}}.</h1>
        <p>Este es el resumen de tu operación. Elegí un área para continuar trabajando.</p>
        <div class="fr-welcome-meta"><span class="fr-live-dot"></span> Sistema de gestión <span class="fr-meta-separator">•</span> {{now.strftime('%A %d de %B de %Y')}}</div>
      </div>
      <div class="fr-welcome-symbol" aria-hidden="true"><span>FR</span><i></i><b></b></div>
    </section>
    {% if not config.get('DATABASE_URL') %}<div class="warn">Modo de demostración: esta instancia usa almacenamiento local temporal. No cargar operaciones reales hasta conectar una base de datos persistente y configurar copias de seguridad.</div>{% endif %}
    <div class="fr-dashboard-layout">
      <div class="fr-dashboard-primary">
        <section class="fr-section-block">
          <div class="fr-section-title"><div><span class="fr-kicker">RESUMEN</span><h2>Indicadores de hoy</h2></div><span class="fr-date-chip">{{now.strftime('%d · %m · %Y')}}</span></div>
          <div class="fr-stat-grid">
            <article class="fr-stat"><span class="fr-stat-icon fr-icon-blue">↗</span><div class="fr-stat-label">Operaciones de hoy</div><strong>{{today_count}}</strong><small>En tus áreas habilitadas</small></article>
            {% if user.role=='admin' or allowed('tesoreria') %}<article class="fr-stat"><span class="fr-stat-icon fr-icon-amber">◷</span><div class="fr-stat-label">Pendientes de autorización</div><strong>{{pending}}</strong><a href="{{url_for('approvals')}}">Ver solicitudes <b>→</b></a></article>{% endif %}
            {% if material_count is not none %}<article class="fr-stat"><span class="fr-stat-icon fr-icon-teal">▤</span><div class="fr-stat-label">Materiales registrados</div><strong>{{material_count}}</strong><a href="{{url_for('module_page',module='materiales')}}">Abrir materiales <b>→</b></a></article>{% endif %}
            {% if user.role=='admin' %}<article class="fr-stat"><span class="fr-stat-icon fr-icon-violet">◎</span><div class="fr-stat-label">Cuentas empresariales</div><strong>{{accounts|length}}</strong><a href="{{url_for('module_page',module='cuentas_empresa')}}">Consultar cuentas <b>→</b></a></article><article class="fr-stat"><span class="fr-stat-icon fr-icon-teal">♙</span><div class="fr-stat-label">Usuarios activos</div><strong>{{active_users}}</strong><a href="{{url_for('users')}}">Gestionar usuarios <b>→</b></a></article>{% endif %}
          </div>
        </section>
        {% if user.role=='admin' %}
        <section class="fr-section-block">
          <div class="fr-section-title"><div><span class="fr-kicker">ORGANIZACIÓN</span><h2>Áreas de trabajo</h2></div><span class="fr-section-note">Seleccioná un área para ver sus herramientas</span></div>
          <div class="fr-area-grid">
            <a class="fr-area-card" href="{{url_for('admin_section',section='caja')}}"><span class="fr-area-symbol fr-icon-blue">▣</span><span class="fr-area-copy"><strong>Caja</strong><small>Pagos, proveedores y gastos</small></span><span class="fr-area-arrow">↗</span></a>
            <a class="fr-area-card" href="{{url_for('admin_section',section='estacion')}}"><span class="fr-area-symbol fr-icon-amber">▤</span><span class="fr-area-copy"><strong>Estación y flota</strong><small>Camiones, combustible y retiros</small></span><span class="fr-area-arrow">↗</span></a>
            <a class="fr-area-card" href="{{url_for('admin_section',section='inventario')}}"><span class="fr-area-symbol fr-icon-teal">▦</span><span class="fr-area-copy"><strong>Inventario</strong><small>Materiales, stock y movimientos</small></span><span class="fr-area-arrow">↗</span></a>
            <a class="fr-area-card" href="{{url_for('admin_section',section='tesoreria')}}"><span class="fr-area-symbol fr-icon-violet">◇</span><span class="fr-area-copy"><strong>Tesorería</strong><small>Cuentas, pagos y cobros</small></span><span class="fr-area-arrow">↗</span></a>
            <a class="fr-area-card" href="{{url_for('admin_section',section='gomeria')}}"><span class="fr-area-symbol fr-icon-amber">⚙</span><span class="fr-area-copy"><strong>Gomería</strong><small>Servicios y control por camión</small></span><span class="fr-area-arrow">↗</span></a>
            <a class="fr-area-card" href="{{url_for('admin_section',section='auditoria')}}"><span class="fr-area-symbol fr-icon-blue">✓</span><span class="fr-area-copy"><strong>Auditoría</strong><small>Controles, accesos e historial</small></span><span class="fr-area-arrow">↗</span></a>
          </div>
        </section>
        {% endif %}
        <section class="fr-section-block">
          <div class="fr-section-title"><div><span class="fr-kicker">ATAJOS</span><h2>Acciones frecuentes</h2></div></div>
          <div class="fr-action-grid">{% for label,href,description in quick_actions %}<a class="fr-action-card" href="{{href}}"><span class="fr-action-arrow">↗</span><strong>{{label}}</strong><small>{{description}}</small></a>{% endfor %}</div>
        </section>
      </div>
      <aside class="fr-dashboard-rail">
        <section class="fr-rail-card fr-rail-profile"><span class="fr-profile-avatar">{{user.username[:1]|upper}}</span><span class="fr-kicker">SESIÓN ACTIVA</span><h3>{{user.username}}</h3><p>{{AREAS.get(user.role,user.role)}}</p><div class="fr-profile-divider"></div><div class="fr-profile-row"><span>Fecha de acceso</span><strong>{{now.strftime('%d/%m/%Y')}}</strong></div><div class="fr-profile-row"><span>Estado</span><strong class="fr-state-ok"><i></i> Activo</strong></div></section>
        <section class="fr-rail-card"><span class="fr-kicker">ACCESO DIRECTO</span><h3>¿Necesitás consultar algo?</h3><p>Ingresá al historial general para revisar los registros guardados.</p><a class="fr-rail-link" href="{{url_for('general_history')}}">Abrir historial <b>→</b></a><div class="fr-rail-divider"></div><p>También podés consultar e imprimir los informes disponibles.</p><a class="fr-rail-link" href="{{url_for('reports')}}">Ver informes <b>→</b></a></section>
      </aside>
    </div>
    {% if user.role=='admin' %}<section class="fr-section-block fr-activity-block" id="ultimos-movimientos"><div class="fr-section-title"><div><span class="fr-kicker">TRAZABILIDAD</span><h2>Actividad reciente</h2></div><a class="fr-view-all" href="{{url_for('general_history')}}">Ver historial completo →</a></div>{% if records %}<div class="table-wrap"><table><thead><tr><th>Fecha y hora</th><th>Área</th><th>Registro</th><th>Estado</th><th>Importe</th></tr></thead><tbody>{% for r in records %}<tr><td>{{r.created_at.strftime('%d/%m/%Y %H:%M')}}</td><td>{{MODULES.get(r.module,(r.module,))[0]}}</td><td>{{r.title}}</td><td><span class="status-pill">{{r.status}}</span></td><td>{{r.amount}}</td></tr>{% endfor %}</tbody></table></div>{% else %}<div class="fr-empty-state"><span>▤</span><strong>Sin movimientos recientes</strong><p>Cuando se registren operaciones, aparecerán en esta sección.</p></div>{% endif %}</section>{% endif %}
    </main><footer>Freddy Rojas · Gestión empresarial</footer></body></html>""" , title="Panel principal", pending=pending, accounts=accounts, records=records, today_count=today_count, material_count=material_count, active_users=active_users, quick_actions=quick_actions)

@app.get("/area/<section>")
@login_required
def admin_section(section):
    if current_user().role != "admin":
        abort(403)
    groups = {
      "caja": ("Caja", "OPERACIONES FINANCIERAS", "Pagos, proveedores y movimientos diarios.", [
        ("Pagos diarios", url_for("pagos_diarios"), "Pagos y comprobantes"),
        ("Préstamos", url_for("prestamos"), "Registro y seguimiento"),
        ("Proveedores y precios", url_for("proveedores"), "Registrar proveedor y precios por material"),
        ("Listado de proveedores", url_for("listado_proveedores"), "Consultar proveedores registrados"),
        ("Cuenta de proveedores", url_for("planillas"), "Planillas y movimientos"),
        ("Fletes", url_for("fletes"), "Control de fletes"),
        ("Tickets de entrada", url_for("module_page",module="tickets"), "Registrar y consultar tickets"),
        ("Solicitudes de pago", url_for("module_page",module="solicitudes"), "Solicitudes para autorización"),
        ("Gastos", url_for("module_page",module="gastos"), "Gastos de la empresa"),
        ("Caja chica", url_for("caja_chica"), "Saldo disponible y movimientos de caja chica")]),
      "estacion": ("Estación de servicio", "FLOTA Y COMBUSTIBLE", "Camiones, combustible, retiros y mantenimiento.", [
        ("Camiones y retiros", url_for("flota"), "Vehículos y retiros"),
        ("Stock de combustible", url_for("combustible_stock"), "Existencias y cargas"),
        ("Combustible por camión", url_for("module_page",module="combustible"), "Historial por vehículo"),
        ("Mantenimiento", url_for("mantenimiento"), "Servicios de flota")]),
      "gomeria": ("Gomería", "MANTENIMIENTO DE NEUMÁTICOS", "Todas las funciones de gomería en una sola sección.", [
        ("Gomería por camión", url_for("gomeria_camiones"), "Trabajos por vehículo"),
        ("Servicios de gomería", url_for("module_page",module="gomeria"), "Registrar servicio, costo y responsable"),
        ("Historial de gomería", url_for("report_module",module="gomeria"), "Consultar registros del área")]),
      "inventario": ("Inventario", "STOCK Y MATERIALES", "Materiales, repuestos, ventas y movimientos.", [
        ("Materiales y precios", url_for("module_page",module="materiales"), "Catálogo de materiales"),
        ("Inventario de materiales", url_for("module_page",module="inventario"), "Entradas y existencias"),
        ("Ventas", url_for("module_page",module="ventas"), "Ventas y salidas"),
        ("Repuestos hidráulicos", url_for("module_page",module="repuestos"), "Stock de repuestos"),
        ("Movimientos de stock", url_for("module_page",module="movimientos_stock"), "Entradas, usos y salidas")]),
      "tesoreria": ("Tesorería", "CUENTAS Y PAGOS", "Cuentas por pagar y cobrar, cheques y autorizaciones.", [
        ("Cuentas por pagar", url_for("module_page",module="cuentas_pagar"), "Obligaciones y vencimientos"),
        ("Cuentas por cobrar", url_for("module_page",module="cuentas_cobrar"), "Cobros y seguimiento"),
        ("Cheques adelantados", url_for("module_page",module="cheques"), "Cheques y vencimientos"),
        ("Movimientos de pagos", url_for("module_page",module="pagos_cuentas"), "Movimientos de cuentas"),
        ("Cobros de cuentas", url_for("module_page",module="cobros_cuentas"), "Registrar cobros"),
        ("Autorizaciones y pagos", url_for("approvals"), "Revisar solicitudes"),
        ("Cuentas bancarias de la empresa", url_for("module_page",module="cuentas_empresa"), "Cuentas y saldos")]),
      "auditoria": ("Auditoría", "CONTROL Y TRAZABILIDAD", "Revisión de operaciones y actividad de usuarios.", [
        ("Auditoría de pagos", url_for("auditoria_pagos"), "Revisar pagos y comprobantes"),
        ("Revisión y auditoría", url_for("module_page",module="auditoria"), "Registrar controles y diferencias"),
        ("Informe de accesos", url_for("access_report"), "Quién ingresó y cuándo"),
        ("Informes", url_for("reports"), "Informes del sistema"),
        ("Historial", url_for("general_history"), "Historial general")]),
      "administracion": ("Administración", "CONFIGURACIÓN DEL SISTEMA", "Usuarios, permisos y herramientas administrativas.", [
        ("Usuarios y permisos", url_for("users"), "Crear usuarios y asignar áreas"),
        ("Materiales y precios", url_for("module_page",module="materiales"), "Administrar catálogo"),
        ("Cuentas de la empresa", url_for("module_page",module="cuentas_empresa"), "Cuentas bancarias y saldos"),
        ("Informe de accesos", url_for("access_report"), "Registro de ingresos"),
        ("Exportar respaldo", url_for("backup_export"), "Descargar respaldo de datos"),
        ("Mi contraseña", url_for("change_password"), "Cambiar contraseña del administrador")])
    }
    data=groups.get(section)
    if not data:
        abort(404)
    return render_template_string(BASE + """
    <section class="card area-hero">
      <div class="area-eyebrow">{{data[1]}}</div><h1>{{data[0]}}</h1>
      <p>{{data[2]}}</p><a class="btn btn-secondary" href="{{url_for('index')}}">← Volver al panel</a>
    </section>
    <section class="area-grid">
      {% for label,href,description in data[3] %}
      <a class="area-link" href="{{href}}"><span class="area-link-icon">{{loop.index}}</span>
      <span class="area-link-copy"><strong>{{label}}</strong><small>{{description}}</small></span><span class="area-arrow">→</span></a>
      {% endfor %}
    </section></main><footer>Freddy Rojas · Plataforma de gestión empresarial</footer></body></html>
    """, title=data[0], data=data)


@app.route("/modulo/<module>", methods=["GET","POST"])
@login_required
def module_page(module):
    if module not in MODULES: abort(404)
    if not allowed(module):
        flash("Tu usuario no tiene permiso para acceder a este módulo.")
        abort(403)
    title, area, fields = MODULES[module]
    if module == "combustible":
        return redirect(url_for("combustible_stock"))
    if module == "gomeria":
        return redirect(url_for("gomeria_camiones"))
    if module == "clientes":
        return redirect(url_for("listado_proveedores"))
    if module == "materiales":
        if request.method == "POST":
            name=request.form.get("nombre","").strip()
            if not name:
                flash("Ingresá el nombre del material.")
            elif Material.query.filter(db.func.lower(Material.name)==name.lower()).first():
                flash("Ese material ya existe.")
            else:
                m=Material(name=name,price=0,wholesale_price=None,unit="kg",stock=0)
                db.session.add(m); db.session.flush()
                log_action("crear material","materiales",m.id,name)
                db.session.commit(); flash("Material guardado.")
            return redirect(url_for("module_page",module=module))
        items=Material.query.order_by(Material.name).all()
        return render_template_string(BASE+"""
        <section class="card"><h2>Agregar material</h2><form method="post" class="grid">
        <div><label>Nombre del material</label><input name="nombre" required></div>
        <div style="align-self:end"><button class="btn">Guardar material</button></div></form></section>
        <section class="card"><h2>Listado de materiales</h2><button class="btn" type="button" onclick="window.print()">Imprimir listado</button>
        <table><tr><th>Material</th><th>Precio minorista</th><th>Precio mayorista</th><th>Actualizar precios</th></tr>{% for m in items %}<tr><td>{{m.name}}</td><td>{{m.price if m.price and m.price != 0 else '—'}}</td><td>{{m.wholesale_price if m.wholesale_price is not none else '—'}}</td>
        <td><form method="post" action="{{url_for('update_material_price',mid=m.id)}}" class="actions"><input aria-label="Precio minorista" name="precio_minorista" type="number" step="0.01" min="0" placeholder="Minorista"><input aria-label="Precio mayorista" name="precio_mayorista" type="number" step="0.01" min="0" placeholder="Mayorista"><button class="btn">Guardar</button></form></td></tr>{% endfor %}</table></section></main><footer>El Toro S.A.</footer></body></html>""",title=title,items=items)
    if module == "cuentas_empresa":
        if request.method == "POST":
            try:
                bal = Decimal(request.form.get("saldo_inicial","0") or "0")
                if bal < 0: raise InvalidOperation()
                a = CompanyAccount(name=request.form["nombre"].strip(),bank=request.form["banco"].strip(),
                    number=request.form["numero"].strip(),currency=request.form["moneda"].strip().upper(),
                    opening_balance=bal,balance=bal)
                db.session.add(a); db.session.flush(); log_action("crear cuenta empresa","cuentas_empresa",a.id,a.name); db.session.commit()
                flash("Cuenta de empresa creada."); return redirect(url_for("module_page",module=module))
            except (InvalidOperation,ValueError,KeyError):
                db.session.rollback(); flash("Datos de cuenta o saldo inválidos.")
        items=CompanyAccount.query.order_by(CompanyAccount.id.desc()).all()
        return render_template_string(BASE+"""
        <section class="card"><h2>{{title}}</h2><p class="warn">Solo el administrador administra las cuentas y los saldos de El Toro S.A. La cuenta del cliente se guarda por separado en su ticket/solicitud.</p>
        <form method="post" class="grid">{% for key,label,kind,req in fields %}<div><label>{{label}}</label><input name="{{key}}" type="{{kind}}" {% if req %}required{% endif %} {% if kind=='number' %}step="0.01" min="0"{% endif %}></div>{% endfor %}<div style="align-self:end"><button class="btn">Crear cuenta</button></div></form></section>
        <section class="card"><h2>Cuentas y saldos actuales</h2><table><tr><th>Cuenta</th><th>Banco</th><th>Número/alias</th><th>Moneda</th><th>Saldo inicial</th><th>Saldo actual</th></tr>{% for a in items %}<tr><td>{{a.name}}</td><td>{{a.bank}}</td><td>{{a.number}}</td><td>{{a.currency}}</td><td>{{a.opening_balance}}</td><td>{{a.balance}}</td></tr>{% endfor %}</table></section></main><footer>Freddy Rojas · Cada registro conserva usuario y fecha/hora</footer></body></html>""",title=title,fields=fields,items=items)
    if module == "inventario":
        if request.method == "POST":
            name=request.form.get("nombre","").strip(); raw=request.form.get("cantidad","").strip().replace(",",".")
            try:
                qty=Decimal(raw)
                if not name or qty<=0: raise InvalidOperation()
                mat=Material.query.filter(db.func.lower(Material.name)==name.lower()).first()
                if not mat:
                    mat=Material(name=name,price=0,wholesale_price=None,unit="kg",stock=qty); db.session.add(mat); db.session.flush()
                else: mat.stock += qty
                data={"material":mat.name,"cantidad_ingresada":str(qty),"cantidad_disponible":str(mat.stock)}
                rec=Record(module="inventario",title=mat.name,data=json.dumps(data,ensure_ascii=False),status="Stock actualizado",created_by=current_user().id)
                db.session.add(rec); db.session.flush(); log_action("entrada de inventario","inventario",rec.id,f"{mat.name}: +{qty}; disponible {mat.stock}")
                db.session.commit(); flash("Material y cantidad guardados.")
            except (InvalidOperation,ValueError): db.session.rollback(); flash("Ingresá una cantidad mayor que cero.")
            return redirect(url_for("module_page",module=module))
        items=Material.query.order_by(Material.name).all()
        hist=Record.query.filter_by(module="inventario").order_by(Record.created_at.desc()).all()
        hist_parsed=[(r,json.loads(r.data or "{}")) for r in hist]
        return render_template_string(BASE+"""
        <section class="card"><h2>Inventario de materiales</h2><form method="post" class="grid">
        <div><label>Nombre del material</label><input name="nombre" list="materiales-disponibles" required><datalist id="materiales-disponibles">{% for m in items %}<option value="{{m.name}}">{% endfor %}</datalist></div>
        <div><label>Cantidad que se agrega</label><input name="cantidad" type="number" min="0.001" step="0.001" required></div><div style="align-self:end"><button class="btn">Guardar y agregar otro</button></div></form></section>
        <section class="card inventory-list"><h2>Materiales disponibles</h2><button class="btn" type="button" onclick="window.print()">Imprimir inventario</button>
        <table><tr><th>Material</th><th>Cantidad disponible</th><th>Unidad</th></tr>{% for m in items %}<tr><td>{{m.name}}</td><td class="inventory-qty">{{m.stock}}</td><td>{{m.unit}}</td></tr>{% endfor %}</table></section>
        <section class="card"><h2>Historial de inventario</h2><button class="btn" type="button" onclick="window.print()">Imprimir historial</button>
        <table><tr><th>Fecha/hora</th><th>Material</th><th>Cantidad agregada</th><th>Disponible</th><th>Imprimir</th></tr>{% for r,d in hist_parsed %}<tr><td>{{r.created_at.strftime('%d/%m/%Y %H:%M')}}</td><td>{{d.get('material',r.title)}}</td><td>{{d.get('cantidad_ingresada','')}}</td><td>{{d.get('cantidad_disponible','')}}</td><td><a class="btn" href="{{url_for('print_record',rid=r.id)}}">Imprimir</a></td></tr>{% endfor %}</table></section></main><footer>El Toro S.A.</footer></body></html>""",title=title,items=items,hist_parsed=hist_parsed)
    if module == "tickets":
        materials=Material.query.order_by(Material.name).all()
        if request.method=="POST":
            client=request.form.get("cliente","").strip(); names=request.form.getlist("material"); quantities=request.form.getlist("cantidad"); price_type=request.form.get("tipo_precio","minorista")
            lines=[]; total=Decimal("0")
            if not client: flash("Ingresá el cliente o proveedor."); return redirect(url_for("module_page",module=module))
            for name,raw in zip(names,quantities):
                name=name.strip(); raw=raw.strip().replace(",",".")
                if not name and not raw: continue
                try:
                    qty=Decimal(raw); mat=Material.query.filter(db.func.lower(Material.name)==name.lower()).first()
                    if not mat or qty<=0: raise InvalidOperation()
                    price=mat.price if price_type=="minorista" else mat.wholesale_price
                    if price is None or (price_type=="minorista" and price<=0):
                        flash("El material "+mat.name+" no tiene ese precio configurado."); return redirect(url_for("module_page",module=module))
                    line_total=(qty*price).quantize(Decimal("0.01")); total+=line_total
                    lines.append({"material":mat.name,"cantidad":str(qty),"tipo_precio":price_type,"precio":str(price),"total":str(line_total)})
                except (InvalidOperation,ValueError): flash("Cada material debe tener una cantidad mayor que cero."); return redirect(url_for("module_page",module=module))
            if not lines: flash("Agregá al menos un material."); return redirect(url_for("module_page",module=module))
            data={"cliente":client,"materiales":lines,"tipo_precio":price_type,"cuenta_cliente":request.form.get("cuenta_cliente","").strip(),"observaciones":request.form.get("observaciones","").strip(),"destino_pago":request.form.get("destino_pago","materiales").strip(),"total":str(total)}
            rec=Record(module="tickets",title=client,data=json.dumps(data,ensure_ascii=False),amount=total,status="Pendiente de pago",created_by=current_user().id)
            db.session.add(rec); db.session.flush(); log_action("crear ticket de entrada","tickets",rec.id,f"{client}; total {total}"); db.session.commit()
            flash("Ticket guardado."); return redirect(url_for("module_page",module=module))
        q=request.args.get("q","").strip().casefold(); hist=Record.query.filter_by(module="tickets").order_by(Record.created_at.desc()).all()
        parsed=[(r,json.loads(r.data or "{}")) for r in hist if not q or q in (r.title+" "+r.data+" "+str(r.amount)).casefold()]
        return render_template_string(BASE+"""
        <section class="card"><h2>{{title}}</h2><form method="post" id="ticket-form"><div class="grid">
        <div><label>Cliente / proveedor</label><input name="cliente" required></div><div><label>Tipo de precio</label><select name="tipo_precio"><option value="minorista">Minorista</option><option value="mayorista">Mayorista</option></select></div>
        <div><label>Cuenta bancaria del cliente (opcional)</label><input name="cuenta_cliente"></div><div><label>Observaciones</label><input name="observaciones"></div><div><label>Destino del registro</label><select name="destino_pago" required><option value="materiales">Pago de materiales</option><option value="gastos">Gastos</option></select></div></div>
        <h3>Materiales del ticket</h3><div id="ticket-lines"><div class="grid ticket-line"><div><label>Material</label><select name="material" required><option value="">Seleccionar material</option>{% for m in materials %}<option value="{{m.name}}">{{m.name}}</option>{% endfor %}</select></div><div><label>Cantidad / kg</label><input name="cantidad" type="number" min="0.001" step="0.001" required></div></div></div>
        <p><button type="button" class="btn" onclick="addTicketLine()">+ Agregar material</button></p><button class="btn">Guardar ticket</button></form></section>
        <section class="card"><h2>Historial de tickets</h2><form method="get" class="actions"><input name="q" placeholder="Buscar cliente, material, monto..." value="{{q}}"><button class="btn">Buscar</button><a class="btn" href="{{url_for('module_page',module='tickets')}}">Limpiar</a></form><p><button class="btn" type="button" onclick="window.print()">Imprimir listado</button></p>
        <table><tr><th>Fecha/hora</th><th>Cliente</th><th>Materiales</th><th>Destino</th><th>Estado</th><th>Total</th><th>Acciones</th></tr>{% for r,d in parsed %}<tr><td>{{r.created_at.strftime('%d/%m/%Y %H:%M')}}</td><td>{{r.title}}</td><td>{% for line in d.get('materiales',[]) %}{{line.material}} · {{line.cantidad}} · {{line.total}}<br>{% endfor %}</td><td>{{'Gastos' if d.get('destino_pago')=='gastos' else 'Pago de materiales'}}</td><td>{{r.status}}</td><td>{{r.amount}}</td><td><a class="btn" href="{{url_for('print_record',rid=r.id)}}">Imprimir ticket</a></td></tr>{% endfor %}</table></section>
        <script>function addTicketLine(){const root=document.getElementById('ticket-lines');const first=root.querySelector('.ticket-line');const copy=first.cloneNode(true);copy.querySelector('select').value='';copy.querySelector('input').value='';copy.querySelector('select').required=false;copy.querySelector('input').required=false;root.appendChild(copy)}</script>
        </main><footer>El Toro S.A.</footer></body></html>""",title=title,materials=materials,parsed=parsed,q=q)
    if module == "auditoria" and request.method == "GET":
        q=request.args.get("q","").strip().casefold(); since=request.args.get("desde",""); until=request.args.get("hasta",""); amount_filter=request.args.get("monto","").strip()
        modules_allowed=set(MODULES.keys())
        all_records=Record.query.order_by(Record.created_at.desc()).all(); results=[]
        for rec in all_records:
            if rec.module not in modules_allowed and rec.module not in {"pagos_diarios","prestamos_pagos","pagos_cuentas","combustible_camion","gomeria_camiones","fletes","planillas","flota","mantenimiento","gastos"}: continue
            d=json.loads(rec.data or "{}"); hay=(rec.title+" "+rec.module+" "+rec.status+" "+str(rec.amount)+" "+rec.data).casefold()
            if q and q not in hay: continue
            if since and rec.created_at.strftime("%Y-%m-%d")<since: continue
            if until and rec.created_at.strftime("%Y-%m-%d")>until: continue
            if amount_filter and amount_filter not in str(rec.amount): continue
            results.append((rec,d))
        logs=AuditLog.query.order_by(AuditLog.created_at.desc()).all()
        if q: logs=[x for x in logs if q in (x.action+" "+x.module+" "+x.detail).casefold()]
        return render_template_string(BASE+"""
        <section class="card"><h2>Auditoría centralizada</h2><form method="get" class="grid">
        <div><label>Buscar cualquier dato</label><input name="q" value="{{q}}" placeholder="Pago a cliente, proveedor, concepto..."></div>
        <div><label>Desde</label><input type="date" name="desde" value="{{since}}"></div><div><label>Hasta</label><input type="date" name="hasta" value="{{until}}"></div><div><label>Monto</label><input name="monto" value="{{amount_filter}}"></div>
        <div style="align-self:end"><button class="btn">Buscar</button> <a class="btn" href="{{url_for('module_page',module='auditoria')}}">Limpiar</a></div></form>
        <p><button class="btn" type="button" onclick="window.print()">Imprimir resultados</button></p><h3>Operaciones registradas ({{results|length}})</h3>
        <table><tr><th>Fecha/hora</th><th>Sector</th><th>Operación</th><th>Estado</th><th>Monto</th><th>Imprimir</th></tr>{% for r,d in results %}<tr><td>{{r.created_at.strftime('%d/%m/%Y %H:%M')}}</td><td>{{MODULES.get(r.module,(r.module,))[0]}}</td><td>{{r.title}}<br>{% for k,v in d.items() %}{% if v is string %}<b>{{k}}:</b> {{v}}<br>{% endif %}{% endfor %}</td><td>{{r.status}}</td><td>{{r.amount}}</td><td><a class="btn" href="{{url_for('print_record',rid=r.id)}}">Imprimir</a></td></tr>{% endfor %}</table></section>
        <section class="card"><h2>Registro de acciones y cambios</h2><table><tr><th>Fecha/hora</th><th>Usuario ID</th><th>Acción</th><th>Sector</th><th>Detalle</th></tr>{% for x in logs %}<tr><td>{{x.created_at.strftime('%d/%m/%Y %H:%M')}}</td><td>{{x.user_id or 'Sistema'}}</td><td>{{x.action}}</td><td>{{MODULES.get(x.module,(x.module,))[0]}}</td><td>{{x.detail}}</td></tr>{% endfor %}</table></section></main><footer>El Toro S.A.</footer></body></html>""",title=title,q=q,since=since,until=until,amount_filter=amount_filter,results=results,logs=logs)
    if module == "repuestos":
        if request.method=="POST":
            name=request.form.get("nombre","").strip()
            code=request.form.get("codigo","").strip()
            location=request.form.get("ubicacion","").strip()
            try:
                qty=Decimal(request.form.get("stock","").replace(",","."))
                minimum=Decimal(request.form.get("stock_minimo","0").replace(",",".") or "0")
                if not name or qty<0 or minimum<0: raise InvalidOperation()
                latest=None; current=Decimal("0")
                for candidate in Record.query.filter_by(module="repuestos").order_by(Record.created_at.desc()).all():
                    d=json.loads(candidate.data or "{}")
                    if d.get("nombre","").strip().casefold()==name.casefold():
                        latest=candidate
                        current=Decimal(str(d.get("stock","0")))
                        break
                newstock=current+qty
                data={"nombre":name,"codigo":code,"stock":str(newstock),"stock_minimo":str(minimum),"ubicacion":location,"cantidad_ingresada":str(qty)}
                rec=Record(module="repuestos",title=name,data=json.dumps(data,ensure_ascii=False),amount=0,status="Stock actualizado",created_by=current_user().id)
                db.session.add(rec); db.session.flush()
                log_action("entrada de inventario hidráulico","repuestos",rec.id,f"{name}: +{qty}; disponible {newstock}")
                db.session.commit(); flash("Repuesto guardado. Stock disponible: "+str(newstock))
            except (InvalidOperation,ValueError):
                db.session.rollback(); flash("Ingresá una cantidad y stock mínimo válidos.")
            return redirect(url_for("module_page",module="repuestos"))
        allrows=Record.query.filter_by(module="repuestos").order_by(Record.created_at.desc()).all()
        seen=set(); current_items=[]; history=[]
        for rec in allrows:
            d=json.loads(rec.data or "{}"); history.append((rec,d)); key=d.get("nombre","").strip().casefold()
            if key and key not in seen:
                seen.add(key); current_items.append((rec,d))
        q=request.args.get("q","").strip().casefold()
        current_items=[(r,d) for r,d in current_items if not q or q in (r.title+" "+r.data).casefold()]
        return render_template_string(BASE+"""
        <section class="card"><h2>Inventario de puesto hidráulico</h2><form method="post" class="grid">
        <div><label>Artículo / repuesto</label><input name="nombre" required></div><div><label>Código / referencia</label><input name="codigo"></div>
        <div><label>Cantidad inicial o que se agrega</label><input name="stock" type="number" min="0" step="0.001" required></div>
        <div><label>Stock mínimo</label><input name="stock_minimo" type="number" min="0" step="0.001" value="0"></div><div><label>Ubicación</label><input name="ubicacion"></div>
        <div style="align-self:end"><button>Guardar / agregar stock</button></div></form></section>
        <section class="card inventory-list"><h2>Artículos y stock disponible</h2><form class="actions"><input name="q" value="{{q}}" placeholder="Buscar artículo o código"><button>Buscar</button><button type="button" onclick="window.print()">Imprimir inventario</button></form>
        <table><tr><th>Artículo</th><th>Código</th><th>Disponible</th><th>Stock mínimo</th><th>Ubicación</th></tr>{% for r,d in current_items %}<tr><td>{{d.get('nombre')}}</td><td>{{d.get('codigo')}}</td><td class="inventory-qty">{{d.get('stock')}}</td><td>{{d.get('stock_minimo')}}</td><td>{{d.get('ubicacion')}}</td></tr>{% endfor %}</table></section>
        <section class="card"><h2>Historial de entradas</h2><table><tr><th>Fecha/hora</th><th>Artículo</th><th>Cantidad agregada</th><th>Stock tras registro</th><th>Imprimir</th></tr>{% for r,d in history %}<tr><td>{{r.created_at.strftime('%d/%m/%Y %H:%M')}}</td><td>{{d.get('nombre')}}</td><td>{{d.get('cantidad_ingresada',d.get('stock'))}}</td><td>{{d.get('stock')}}</td><td><a class="btn" href="{{url_for('print_record',rid=r.id)}}">Imprimir</a></td></tr>{% endfor %}</table></section></main><footer>El Toro S.A.</footer></body></html>
        """,title=title,current_items=current_items,history=history,q=q)
    if module == "gastos":
        if request.method == "POST":
            try:
                names=request.form.getlist("item[]"); quantities=request.form.getlist("cantidad_item[]"); prices=request.form.getlist("precio_item[]")
                items=[]; total=Decimal("0")
                for name,raw_qty,raw_price in zip(names,quantities,prices):
                    name=name.strip(); raw_qty=raw_qty.strip().replace(",","."); raw_price=raw_price.strip().replace(",",".")
                    if not name and not raw_qty and not raw_price: continue
                    qty=Decimal(raw_qty); price=Decimal(raw_price)
                    if not name or qty<=0 or price<0: raise InvalidOperation()
                    subtotal=(qty*price).quantize(Decimal("0.01"))
                    items.append({"articulo":name,"cantidad":str(qty),"precio_unitario":str(price),"subtotal":str(subtotal)})
                    total+=subtotal
                if not items or total<=0: raise InvalidOperation()
                data={"fecha":request.form.get("fecha",""),"categoria":request.form.get("categoria","").strip(),
                      "items":items,"detalle":"; ".join(x["articulo"] for x in items),
                      "medio":request.form.get("medio","").strip(),"comprobante":request.form.get("comprobante","").strip()}
                if not data["fecha"] or not data["categoria"]: raise InvalidOperation()
                rec=Record(module="gastos",title=data["categoria"]+" · "+data["detalle"][:150],
                    data=json.dumps(data,ensure_ascii=False),amount=total,status="Pagado" if data["medio"] else "Registrado",
                    created_by=current_user().id)
                db.session.add(rec); db.session.flush()
                log_action("registrar gasto y salida de dinero","gastos",rec.id,f"{data['categoria']}; total {total}; medio {data['medio']}")
                db.session.commit(); flash("Gasto guardado. Total: Gs. "+str(total))
            except (InvalidOperation,ValueError):
                db.session.rollback(); flash("Revisá los artículos, cantidades, precios y fecha del gasto.")
            return redirect(url_for("module_page",module="gastos"))
        items=Record.query.filter_by(module="gastos").order_by(Record.created_at.desc()).all()
        tickets_gasto=[r for r in Record.query.filter_by(module="tickets").order_by(Record.created_at.desc()).all() if json.loads(r.data or "{}").get("destino_pago")=="gastos"]
        caja_chica_gastos=[r for r in Record.query.filter_by(module="caja_chica").order_by(Record.created_at.desc()).all() if json.loads(r.data or "{}").get("tipo")=="gasto" and json.loads(r.data or "{}").get("clasificacion")=="gastos"]
        total_gastos=sum((Decimal(str(r.amount or 0)) for r in items+tickets_gasto+caja_chica_gastos),Decimal("0"))
        q=request.args.get("q","").strip().casefold()
        items=[r for r in items if not q or q in (r.title+" "+r.data+" "+str(r.amount)).casefold()]
        tickets_gasto=[r for r in tickets_gasto if not q or q in (r.title+" "+r.data+" "+str(r.amount)).casefold()]
        caja_chica_gastos=[r for r in caja_chica_gastos if not q or q in (r.title+" "+r.data+" "+str(r.amount)).casefold()]
        return render_template_string(BASE+"""
        <section class="card"><h2>Registrar gasto</h2><form method="post" id="gasto-form" class="grid">
        <div><label>Fecha</label><input name="fecha" type="date" value="{{today}}" required></div>
        <div><label>Categoría</label><input name="categoria" required></div><div><label>Medio de pago</label><select name="medio"><option value="">Pendiente / no pagado</option><option>Efectivo</option><option>Transferencia</option><option>Cheque</option><option>Tarjeta</option><option>Otro</option></select></div>
        <div><label>Comprobante</label><input name="comprobante"></div>
        <div style="grid-column:1/-1"><h3>Artículos del gasto</h3><div id="gasto-items"><div class="grid gasto-item">
        <div><label>Artículo / descripción</label><input name="item[]" required></div><div><label>Cantidad</label><input name="cantidad_item[]" type="number" min="0.001" step="0.001" required></div><div><label>Precio unitario (Gs.)</label><input name="precio_item[]" type="number" min="0" step="0.01" required></div>
        </div></div><p><button type="button" onclick="addGastoItem()">+ Agregar artículo</button></p></div>
        <div style="align-self:end"><button>Guardar gasto</button></div></form>
        <script>function addGastoItem(){const root=document.getElementById('gasto-items');const row=root.querySelector('.gasto-item').cloneNode(true);row.querySelectorAll('input').forEach(i=>i.value='');root.appendChild(row)}</script></section>
        <section class="card"><h2>Resumen de gastos · Total: Gs. {{total_gastos}}</h2><p>Incluye los gastos registrados aquí y los tickets clasificados como Gastos. Los tickets clasificados como Pago de materiales y los movimientos de caja chica marcados solo como Caja chica no se suman.</p></section>
        <section class="card"><h2>Historial de gastos</h2><form class="actions"><input name="q" value="{{q}}" placeholder="Buscar artículo, concepto, comprobante"><button>Buscar</button><button type="button" onclick="window.print()">Imprimir</button></form>
        <table><tr><th>Fecha</th><th>Origen</th><th>Categoría / proveedor</th><th>Detalle</th><th>Medio</th><th>Total</th><th>Estado</th><th>Imprimir</th></tr>
        {% for r in items %}{% set d=decode(r) %}<tr><td>{{d.get('fecha')}}</td><td>Gasto</td><td>{{d.get('categoria')}}</td><td>{% for x in d.get('items',[]) %}{{x.get('articulo')}} · {{x.get('cantidad')}} × {{x.get('precio_unitario')}} = {{x.get('subtotal')}}<br>{% endfor %}</td><td>{{d.get('medio')}}</td><td>{{r.amount}}</td><td>{{r.status}}</td><td><a class="btn" href="{{url_for('print_record',rid=r.id)}}">Imprimir</a></td></tr>{% endfor %}
        {% for r in tickets_gasto %}{% set d=decode(r) %}<tr><td>{{r.created_at.strftime('%Y-%m-%d')}}</td><td>Ticket</td><td>{{d.get('cliente',r.title)}}</td><td>{% for x in d.get('materiales',[]) %}{{x.get('material')}} · {{x.get('cantidad')}} kg · Gs. {{x.get('total')}}<br>{% endfor %}</td><td>{{d.get('medio_pago','No indicado')}}</td><td>{{r.amount}}</td><td>{{r.status}}</td><td><a class="btn" href="{{url_for('print_record',rid=r.id)}}">Imprimir</a></td></tr>{% endfor %}
        {% for r in caja_chica_gastos %}{% set d=decode(r) %}<tr><td>{{d.get('fecha')}}</td><td>Caja chica</td><td>Gasto de caja chica</td><td>{{d.get('detalle')}}</td><td>{{d.get('medio')}}</td><td>{{r.amount}}</td><td>{{r.status}}</td><td><a class="btn" href="{{url_for('print_record',rid=r.id)}}">Imprimir</a></td></tr>{% endfor %}</table></section></main><footer>El Toro S.A.</footer></body></html>
        """,title=title,items=items,tickets_gasto=tickets_gasto,caja_chica_gastos=caja_chica_gastos,total_gastos=total_gastos,q=q,today=datetime.now().strftime("%Y-%m-%d"),decode=lambda r:json.loads(r.data or "{}"))
    if module in ("cuentas_pagar","cuentas_cobrar","cheques"):
        payment_module="cobros_cuentas" if module=="cuentas_cobrar" else "pagos_cuentas"
        payment_rows=Record.query.filter(Record.module.in_(["pagos_cuentas","cobros_cuentas"])).order_by(Record.created_at.desc()).all()
        originals=Record.query.filter_by(module=module).order_by(Record.created_at.desc()).all()
        if request.method=="POST":
            action=request.form.get("accion","crear")
            if action=="pago":
                try:
                    rid=int(request.form.get("registro_id","")); original=db.get_or_404(Record,rid)
                    if original.module!=module: abort(400)
                    amount=Decimal(request.form.get("importe","").replace(",","."))
                    original_data=json.loads(original.data or "{}")
                    paid=sum((Decimal(str(json.loads(p.data or "{}").get("importe",0))) for p in payment_rows
                              if p.module==payment_module and json.loads(p.data or "{}").get("modulo_origen")==module and str(json.loads(p.data or "{}").get("registro_id"))==str(rid)),Decimal("0"))
                    balance=original.amount-paid
                    if amount<=0 or amount>balance: raise InvalidOperation()
                    paydata={"modulo_origen":module,"registro_id":rid,"fecha":request.form.get("fecha",""),
                        "beneficiario":original_data.get("beneficiario",original_data.get("cliente","")),
                        "concepto":original_data.get("concepto",""),"numero_cheque":original_data.get("numero",""),
                        "importe":str(amount),"medio":request.form.get("medio","Efectivo"),"detalle":request.form.get("detalle","")}
                    is_collection=(module=="cuentas_cobrar")
                    pay_title=("Cobro · " if is_collection else "Pago · ")+original.title
                    pay=Record(module=payment_module,title=pay_title,data=json.dumps(paydata,ensure_ascii=False),
                        amount=amount,status="Cobrado" if is_collection else "Pagado",created_by=current_user().id)
                    db.session.add(pay); db.session.flush()
                    new_balance=balance-amount
                    original.status="Pagado" if new_balance==0 else ("Pago parcial" if not is_collection else "En proceso")
                    log_action("registrar cobro" if is_collection else "registrar pago parcial/final",module,original.id,f"Importe {amount}; saldo {new_balance}; medio {paydata['medio']}")
                    if not is_collection:
                        log_action("salida de dinero registrada","pagos_cuentas",pay.id,pay.title+"; importe "+str(amount))
                    db.session.commit(); flash("Pago registrado. Saldo restante: Gs. "+str(new_balance))
                except (InvalidOperation,ValueError):
                    db.session.rollback(); flash("No se pudo registrar: verificá el importe y el saldo pendiente.")
                return redirect(url_for("module_page",module=module))
            if action=="desembolsar" and module=="cheques":
                try:
                    rid=int(request.form.get("registro_id","")); original=db.get_or_404(Record,rid)
                    if original.module!="cheques" or original.status=="Desembolsado": abort(400)
                    d=json.loads(original.data or "{}")
                    paid=sum((Decimal(str(json.loads(p.data or "{}").get("importe",0))) for p in payment_rows
                              if p.module==payment_module and json.loads(p.data or "{}").get("modulo_origen")==module and str(json.loads(p.data or "{}").get("registro_id"))==str(rid)),Decimal("0"))
                    balance=original.amount-paid
                    paydata={"modulo_origen":module,"registro_id":rid,"fecha":datetime.now().strftime("%Y-%m-%d"),
                        "beneficiario":d.get("beneficiario",""),"concepto":"Desembolso de cheque "+d.get("numero",""),
                        "numero_cheque":d.get("numero",""),"importe":str(balance),"medio":"Cheque","detalle":"Cheque desembolsado"}
                    pay=Record(module="pagos_cuentas",title="Desembolso · "+original.title,data=json.dumps(paydata,ensure_ascii=False),
                        amount=balance,status="Desembolsado",created_by=current_user().id)
                    db.session.add(pay); original.status="Desembolsado"
                    db.session.flush(); log_action("desembolsar cheque","cheques",original.id,"Importe "+str(balance))
                    log_action("salida de dinero registrada","pagos_cuentas",pay.id,pay.title)
                    db.session.commit(); flash("Cheque marcado como desembolsado y registrado en Auditoría.")
                except (ValueError,InvalidOperation):
                    db.session.rollback(); flash("No se pudo desembolsar el cheque.")
                return redirect(url_for("module_page",module=module))
            data={key:("Sí" if request.form.get(key) else "No") if kind=="checkbox" else request.form.get(key,"").strip()
                  for key,label,kind,req in fields}
            if module=="cuentas_cobrar" and not data.get("estado"): data["estado"]="Pendiente"
            if module=="cheques" and not data.get("estado"): data["estado"]="Pendiente"
            for key,label,kind,req in fields:
                if req and not data.get(key): flash("Falta completar: "+label); return redirect(url_for("module_page",module=module))
            try:
                amount=Decimal(data.get("importe","0").replace(",","."))
                if amount<=0: raise InvalidOperation()
                status=data.get("estado","Pendiente") if module in ("cuentas_cobrar","cheques") else "Pendiente"
                rec=Record(module=module,title=(data.get("beneficiario") or data.get("cliente") or data.get("concepto") or data.get("numero") or title)[:220],
                    data=json.dumps(data,ensure_ascii=False),amount=amount,status=status,created_by=current_user().id)
                db.session.add(rec); db.session.flush(); log_action("crear cuenta / cheque",module,rec.id,rec.title)
                if module=="cheques" and status=="Desembolsado":
                    paydata={"modulo_origen":"cheques","registro_id":rec.id,"fecha":data.get("fecha",""),
                        "beneficiario":data.get("beneficiario",""),"concepto":"Desembolso de cheque "+data.get("numero",""),
                        "numero_cheque":data.get("numero",""),"importe":str(amount),"medio":"Cheque","detalle":"Desembolsado al registrar"}
                    pay=Record(module="pagos_cuentas",title="Desembolso · "+rec.title,data=json.dumps(paydata,ensure_ascii=False),
                        amount=amount,status="Desembolsado",created_by=current_user().id)
                    db.session.add(pay); db.session.flush()
                    log_action("salida de dinero registrada","pagos_cuentas",pay.id,pay.title)
                db.session.commit(); flash("Registro guardado.")
            except (InvalidOperation,ValueError):
                db.session.rollback(); flash("Ingresá un importe válido mayor que cero.")
            return redirect(url_for("module_page",module=module))
        summaries=[]
        for rec in originals:
            d=json.loads(rec.data or "{}")
            paid=sum((Decimal(str(json.loads(p.data or "{}").get("importe",0))) for p in payment_rows
                      if p.module==payment_module and json.loads(p.data or "{}").get("modulo_origen")==module and str(json.loads(p.data or "{}").get("registro_id"))==str(rec.id)),Decimal("0"))
            summaries.append((rec,d,paid,max(Decimal("0"),rec.amount-paid)))
        return render_template_string(BASE+"""
        <section class="card"><h2>{{title}}</h2><form method="post" class="grid">
        {% for key,label,kind,req in fields %}<div><label>{{label}}</label>
        {% if kind=='checkbox' %}<label><input type="checkbox" name="{{key}}" value="Sí" style="width:auto"> Incluye cheque adelantado</label>
        {% elif kind=='select' and module=='cuentas_cobrar' %}<select name="{{key}}"><option>Pendiente</option><option>En proceso</option><option>Pagado</option><option>Vencido</option></select>
        {% elif kind=='select' and module=='cheques' %}<select name="{{key}}"><option>Pendiente</option><option>Desembolsado</option></select>
        {% else %}<input name="{{key}}" type="{{kind}}" {% if req %}required{% endif %} {% if kind=='number' %}step="0.01" min="0"{% endif %}>{% endif %}</div>{% endfor %}
        <div style="align-self:end"><button>Guardar registro</button></div></form></section>
        <section class="card"><h2>Historial y saldos</h2><button type="button" onclick="window.print()">Imprimir historial</button>
        <table><tr><th>Fecha</th><th>Registro</th><th>Importe original</th><th>Pagado</th><th>Saldo</th><th>Estado</th><th>Acción</th></tr>
        {% for r,d,paid,balance in summaries %}<tr><td>{{r.created_at.strftime('%d/%m/%Y')}}</td><td>{{r.title}}<br>{% for k,v in d.items() %}{% if v is string %}{{k}}: {{v}}<br>{% endif %}{% endfor %}</td><td>{{r.amount}}</td><td>{{paid}}</td><td><b>{{balance}}</b></td><td>{{r.status}}</td><td>{% if balance>0 and module!='cheques' %}<form method="post"><input type="hidden" name="accion" value="pago"><input type="hidden" name="registro_id" value="{{r.id}}"><input name="importe" type="number" min="0.01" max="{{balance}}" step="0.01" required placeholder="Importe"><input name="fecha" type="date" value="{{today}}" required><select name="medio"><option>Efectivo</option><option>Transferencia</option><option>Cheque</option><option>Otro</option></select><input name="detalle" placeholder="Detalle"><button>Registrar pago</button></form>{% elif module=='cheques' and r.status!='Desembolsado' %}<form method="post"><input type="hidden" name="accion" value="desembolsar"><input type="hidden" name="registro_id" value="{{r.id}}"><button>Marcar desembolsado</button></form>{% endif %}</td></tr>{% endfor %}</table></section>
        <section class="card"><h2>Movimientos de pago</h2><table><tr><th>Fecha</th><th>Registro</th><th>Beneficiario / cliente</th><th>Concepto</th><th>Importe</th><th>Medio</th><th>Imprimir</th></tr>
        {% for p in payment_rows %}{% set d=decode(p) %}{% if d.get('modulo_origen')==module %}<tr><td>{{d.get('fecha')}}</td><td>#{{d.get('registro_id')}}</td><td>{{d.get('beneficiario')}}</td><td>{{d.get('concepto') or d.get('numero_cheque')}}</td><td>{{p.amount}}</td><td>{{d.get('medio')}}</td><td><a class="btn" href="{{url_for('print_record',rid=p.id)}}">Imprimir</a></td></tr>{% endif %}{% endfor %}</table></section></main><footer>El Toro S.A.</footer></body></html>
        """,title=title,fields=fields,module=module,summaries=summaries,payment_rows=payment_rows,today=datetime.now().strftime("%Y-%m-%d"),decode=lambda r:json.loads(r.data or "{}"))
    if request.method == "POST":
        data = {key: ("Sí" if request.form.get(key) else "No") if kind=="checkbox" else request.form.get(key,"").strip() for key,label,kind,req in fields}
        if module == "cuentas_cobrar" and not data.get("estado"): data["estado"]="Pendiente"
        if module == "cheques" and not data.get("estado"): data["estado"]="Pendiente"

        for key,label,kind,req in fields:
            if req and not data.get(key):
                flash("Falta completar: "+label); return redirect(url_for("module_page",module=module))
        amount = Decimal("0")
        for k in ("importe","total","costo"):
            if data.get(k):
                try: amount=Decimal(data[k].replace(",","."))
                except InvalidOperation: amount=Decimal("0")
                break
        status = "Registrado"
        if module == "solicitudes": status = "Pendiente de autorización"
        if module == "tickets":
            mat = Material.query.filter(db.func.lower(Material.name)==data.get("material","").lower()).first()
            if mat:
                try:
                    qty=Decimal(data.get("cantidad","0").replace(",","."))
                    data["precio"]=str(mat.price); data["total"]=str((qty*mat.price).quantize(Decimal("0.01")))
                    amount=Decimal(data["total"])
                except InvalidOperation: pass
            status = "Pendiente de pago" if data.get("total") else "Registrado"
        r=Record(module=module,title=(data.get("nombre") or data.get("cliente") or data.get("proveedor") or data.get("concepto") or data.get("camion") or data.get("referencia") or title)[:220],
            data=json.dumps(data,ensure_ascii=False),amount=amount,status=status,created_by=current_user().id)
        db.session.add(r); db.session.flush()
        log_action("crear registro",module,r.id,r.title)
        if module == "ventas":
            mat=Material.query.filter(db.func.lower(Material.name)==data.get("material","").lower()).first()
            if mat:
                try:
                    qty=Decimal(data.get("cantidad","0").replace(",","."))
                    if qty <= 0 or mat.stock < qty:
                        db.session.rollback()
                        flash("La cantidad debe ser positiva y no puede superar el stock disponible.")
                        return redirect(url_for("module_page",module=module))
                    mat.stock -= qty
                except InvalidOperation:
                    db.session.rollback()
                    flash("La cantidad de venta no es válida.")
                    return redirect(url_for("module_page",module=module))
        if module == "movimientos_stock":
            try:
                qty=Decimal(data.get("cantidad","0").replace(",","."))
                if qty <= 0: raise InvalidOperation()
            except InvalidOperation:
                db.session.rollback()
                flash("La cantidad del movimiento debe ser un número mayor que cero.")
                return redirect(url_for("module_page",module=module))
            spare_records=Record.query.filter_by(module="repuestos").order_by(Record.created_at.desc()).all()
            spare_record=None
            spare_data={}
            for candidate in spare_records:
                candidate_data=json.loads(candidate.data or "{}")
                if candidate_data.get("nombre","").strip().casefold()==data.get("repuesto","").strip().casefold():
                    spare_record=candidate
                    spare_data=candidate_data
                    break
            movement=data.get("tipo","").strip().lower()
            if not spare_record:
                db.session.rollback()
                flash("Ese repuesto no está registrado. Cargalo primero en Inventario de puesto hidráulico.")
                return redirect(url_for("module_page",module=module))
            if movement not in ("entrada","uso","salida"):
                db.session.rollback()
                flash("Seleccioná Entrada, Uso o Salida.")
                return redirect(url_for("module_page",module=module))
            if spare_record and movement in ("uso","salida"):
                try: available=Decimal(str(spare_data.get("stock","0")).replace(",","."))
                except InvalidOperation: available=Decimal("0")
                if available < qty:
                    db.session.rollback()
                    flash("Stock hidráulico insuficiente para ese movimiento.")
                    return redirect(url_for("module_page",module=module))
                spare_data["stock"]=str(available-qty)
            elif spare_record and movement=="entrada":
                try: available=Decimal(str(spare_data.get("stock","0")).replace(",","."))
                except InvalidOperation: available=Decimal("0")
                spare_data["stock"]=str(available+qty)
            if spare_record and movement in ("uso","salida","entrada"):
                spare_record.data=json.dumps(spare_data,ensure_ascii=False)
                spare_record.updated_at=datetime.utcnow()
                log_action("actualizar stock de repuesto hidráulico","repuestos",spare_record.id,
                           f"{data.get('repuesto')}: movimiento {movement}, cantidad {qty}")
        db.session.commit(); flash("Registro guardado con usuario y fecha/hora."); return redirect(url_for("module_page",module=module))
    items=Record.query.filter_by(module=module).order_by(Record.created_at.desc()).all()
    q=request.args.get("q","").strip().casefold(); since=request.args.get("desde",""); until=request.args.get("hasta",""); amount_filter=request.args.get("monto","").strip()
    parsed=[]
    for r in items:
        d=json.loads(r.data or "{}"); hay=(r.title+" "+r.status+" "+str(r.amount)+" "+r.data).casefold()
        if q and q not in hay: continue
        if since and r.created_at.strftime("%Y-%m-%d")<since: continue
        if until and r.created_at.strftime("%Y-%m-%d")>until: continue
        if amount_filter and amount_filter not in str(r.amount): continue
        parsed.append((r,d))
    return render_template_string(BASE+"""
    <section class="card"><h2>{{title}}</h2><form method="post" class="grid">
    {% for key,label,kind,req in fields %}<div><label>{{label}}</label>
    {% if kind=='checkbox' %}<label class="check-field"><input type="checkbox" name="{{key}}" value="Sí" style="width:auto"> Sí, incluye cheque adelantado</label>
    {% elif kind=='select' and module=='cuentas_cobrar' %}<select name="{{key}}"><option>Pendiente</option><option>En proceso</option><option>Pagado</option><option>Vencido</option></select>
    {% elif kind=='select' and module=='cheques' %}<select name="{{key}}" required><option>Pendiente</option><option>Desembolsado</option></select>
     {% elif kind=='select' and module=='gomeria' %}<select name="{{key}}" required><option value="Reparación de cubierta">Reparación de cubierta</option><option value="Cambio de cubierta">Cambio de cubierta</option><option value="Reparación de cámara">Reparación de cámara</option><option value="Cambio de cámara">Cambio de cámara</option><option value="Otro">Otro</option></select>
     {% elif kind=='select' and module=='movimientos_stock' %}<select name="{{key}}" required><option value="entrada">Entrada</option><option value="uso">Uso</option><option value="salida">Salida</option></select>
    {% else %}<input name="{{key}}" type="{{kind}}" {% if req %}required{% endif %} {% if kind=='number' %}step="0.001"{% endif %}>{% endif %}</div>{% endfor %}
    <div style="align-self:end"><button class="btn">Guardar registro</button></div></form>
    {% if module=='tickets' %}<p class="muted small">El precio se toma del material vigente si coincide su nombre. Revisá el total antes de solicitar el pago.</p>{% endif %}
    </section><section class="card"><h2>Historial completo</h2><form method="get" class="grid"><div><label>Buscar en cualquier dato</label><input name="q" value="{{q}}"></div><div><label>Desde</label><input type="date" name="desde" value="{{since}}"></div><div><label>Hasta</label><input type="date" name="hasta" value="{{until}}"></div><div><label>Filtrar por monto</label><input name="monto" value="{{amount_filter}}"></div><div style="align-self:end"><button class="btn">Buscar</button> <a class="btn" href="{{url_for('module_page',module=module)}}">Limpiar</a></div></form><p><button class="btn" type="button" onclick="window.print()">Imprimir historial</button></p>
    {% if parsed %}<table><tr><th>Fecha/hora</th><th>Registro</th><th>Detalle</th><th>Estado</th><th>Importe</th><th>Imprimir</th></tr>
    {% for r,d in parsed %}<tr><td>{{r.created_at.strftime('%d/%m/%Y %H:%M')}}</td><td>{{r.title}}</td><td>{% for k,v in d.items() %}<div><b>{{k}}:</b> {{v}}</div>{% endfor %}</td><td>{{r.status}}</td><td>{{r.amount}}</td><td><a class="btn" href="{{url_for('print_record',rid=r.id)}}">Imprimir</a></td></tr>{% endfor %}</table>{% else %}<p>No hay registros para esa búsqueda.</p>{% endif %}</section></main><footer>Freddy Rojas · Cada registro conserva usuario y fecha/hora</footer></body></html>""",title=title,fields=fields,module=module,parsed=parsed,q=q,since=since,until=until,amount_filter=amount_filter)


@app.post("/materiales/<int:mid>/precio")
@admin_required
def update_material_price(mid):
    material=db.get_or_404(Material,mid)
    minor=request.form.get("precio_minorista","").strip().replace(",","."); major=request.form.get("precio_mayorista","").strip().replace(",",".")
    try:
        pminor=Decimal(minor) if minor else None; pmajor=Decimal(major) if major else None
        if (pminor is not None and pminor<0) or (pmajor is not None and pmajor<0) or (pminor is None and pmajor is None): raise InvalidOperation()
    except (InvalidOperation,ValueError):
        flash("Ingresá al menos un precio válido; dejá vacío el que no corresponda."); return redirect(url_for("module_page",module="materiales"))
    old_minor=material.price; old_major=material.wholesale_price
    if pminor is not None: material.price=pminor
    if request.form.get("precio_mayorista","").strip(): material.wholesale_price=pmajor
    log_action("actualizar precios de material","materiales",material.id,f"{material.name}: minorista {old_minor}->{material.price}; mayorista {old_major}->{material.wholesale_price}")
    db.session.commit(); flash("Precios actualizados. Los tickets anteriores conservan los importes históricos.")
    return redirect(url_for("module_page", module="materiales"))

@app.get("/autorizaciones")
@login_required
def approvals():
    u=current_user()
    if u.role!="admin" and not allowed("tesoreria"): abort(403)
    items=Record.query.filter_by(module="solicitudes").order_by(Record.created_at.asc()).all()
    parsed=[(r,json.loads(r.data or "{}")) for r in items]
    return render_template_string(BASE+"""
    <section class="card"><h2>Autorización requerida</h2><p class="muted">Ordenado por llegada. Autorizar no descuenta el saldo de la empresa; el saldo cambia únicamente al registrar el pago ejecutado.</p>
    {% if parsed %}<table><tr><th>Fecha/hora</th><th>Cliente / concepto</th><th>Importe</th><th>Cuenta del cliente</th><th>Estado</th><th>Acción</th></tr>{% for r,d in parsed %}<tr><td>{{r.created_at.strftime('%d/%m/%Y %H:%M')}}</td><td>{{d.get('cliente','')}}<br>{{d.get('concepto','')}}</td><td>{{r.amount}}</td><td>{{d.get('cuenta_cliente','')}}</td><td>{{r.status}}{% if d.get('motivo_rechazo') %}<br><span class="danger">{{d.get('motivo_rechazo')}}</span>{% endif %}</td><td>
    {% if user.role=='admin' and r.status=='Pendiente de autorización' %}<form method="post" action="{{url_for('decide_payment',rid=r.id)}}"><button class="btn" name="decision" value="aprobar">Autorizar</button> <button class="btn" name="decision" value="rechazar">Rechazar</button><input name="reason" placeholder="Motivo si rechaza"></form>{% elif r.status=='Autorizado' and (user.role=='admin' or allowed('tesoreria')) %}<form method="post" action="{{url_for('pay_payment',rid=r.id)}}"><label>Cuenta de empresa</label><select name="account_id" required>{% for a in accounts %}<option value="{{a.id}}">{{a.name}} · {{a.currency}} · saldo {{a.balance}}</option>{% endfor %}</select><button class="btn">Registrar pago ejecutado</button></form>{% endif %}</td></tr>{% endfor %}</table>{% else %}<p>No hay solicitudes.</p>{% endif %}</section></main><footer>Freddy Rojas · Cada registro conserva usuario y fecha/hora</footer></body></html>""",title="Autorizaciones",parsed=parsed,accounts=CompanyAccount.query.filter_by(active=True).all())

@app.post("/autorizaciones/<int:rid>/decidir")
@login_required
def decide_payment(rid):
    if current_user().role!="admin": abort(403)
    r=db.get_or_404(Record,rid)
    if r.module!="solicitudes" or r.status!="Pendiente de autorización": abort(400)
    d=json.loads(r.data or "{}")
    if request.form.get("decision")=="aprobar":
        r.status="Autorizado"; r.approved_by=current_user().id
        log_action("autorizar pago","solicitudes",r.id,r.title)
        flash("Solicitud autorizada; todavía no se descontó dinero.")
    else:
        reason=request.form.get("reason","").strip()
        d["motivo_rechazo"]=reason or "Sin motivo indicado"
        r.data=json.dumps(d,ensure_ascii=False); r.status="Rechazado"
        log_action("rechazar pago","solicitudes",r.id,d["motivo_rechazo"])
        flash("Solicitud rechazada y motivo guardado.")
    db.session.commit(); return redirect(url_for("approvals"))

@app.post("/autorizaciones/<int:rid>/pagar")
@login_required
def pay_payment(rid):
    if current_user().role!="admin" and not allowed("tesoreria"): abort(403)
    r=db.get_or_404(Record,rid)
    if r.module!="solicitudes" or r.status!="Autorizado": abort(400)
    try: aid=int(request.form.get("account_id",""))
    except ValueError: abort(400)
    a=db.get_or_404(CompanyAccount,aid)
    if not a.active: abort(400)
    if a.balance < r.amount:
        flash("Saldo insuficiente en la cuenta seleccionada; no se registró el pago.")
        return redirect(url_for("approvals"))
    a.balance-=r.amount
    r.status="Pagado"; r.company_account_id=a.id; r.paid_by=current_user().id
    log_action("pago ejecutado y saldo descontado","solicitudes",r.id,f"Cuenta {a.name}; importe {r.amount}; operador {current_user().username}")
    db.session.commit(); flash("Pago registrado como ejecutado y saldo descontado una sola vez.")
    return redirect(url_for("approvals"))

@app.route("/usuarios",methods=["GET","POST"])
@admin_required
def users():
    if request.method=="POST":
        username=request.form.get("username","").strip()
        password=request.form.get("password","")
        role=request.form.get("role","caja")
        areas=request.form.getlist("areas")
        if not username or len(password)<10 or role not in AREAS or role=="admin":
            flash("Usuario requerido, contraseña mínima de 10 caracteres y área válida.")
        elif User.query.filter_by(username=username).first():
            flash("Ese usuario ya existe.")
        else:
            areas=[a for a in dict.fromkeys(areas+[role]) if a in AREAS and a!="admin"]
            u=User(username=username,password_hash=generate_password_hash(password),role=role,areas=",".join(areas))
            db.session.add(u); db.session.flush(); log_action("crear usuario","usuarios",u.id,f"{username}; rol {role}; áreas {u.areas}")
            db.session.commit(); flash("Usuario creado."); return redirect(url_for("users"))
    items=User.query.order_by(User.username).all()
    return render_template_string(BASE+"""
    <section class="card"><h2>Usuarios y permisos</h2>
    <form method="post" class="grid"><div><label>Usuario</label><input name="username" required></div><div><label>Contraseña inicial (mínimo 10 caracteres)</label><input type="password" name="password" minlength="10" required></div>
    <div><label>Área / rol principal</label><select name="role">{% for k,v in AREAS.items() if k != 'admin' %}<option value="{{k}}">{{v}}</option>{% endfor %}</select></div><div><label>Áreas adicionales</label>{% for k,v in AREAS.items() if k != 'admin' %}<label style="font-weight:400"><input style="width:auto" type="checkbox" name="areas" value="{{k}}"> {{v}}</label>{% endfor %}</div><div style="align-self:end"><button class="btn">Crear usuario</button></div></form></section>
    <section class="card"><h2>Usuarios existentes</h2><table><tr><th>Usuario</th><th>Rol</th><th>Áreas asignadas</th><th>Activo</th><th>Creado</th><th>Acciones</th></tr>{% for u in items %}<tr><td>{{u.username}}</td><td>{{AREAS.get(u.role,u.role)}}</td><td>{{', '.join(AREAS.get(a,a) for a in (u.areas or '').split(',') if a)}}</td><td>{{'Sí' if u.active else 'No'}}</td><td>{{u.created_at.strftime('%d/%m/%Y %H:%M')}}</td><td><div class="actions"><a class="btn" href="{{url_for('edit_user',uid=u.id)}}">Editar</a>{% if u.id != user.id %}<form method="post" action="{{url_for('delete_user',uid=u.id)}}" onsubmit="return confirm('¿Desactivar este usuario?');"><button class="btn" style="background:#a92d3c;border-color:#a92d3c">Eliminar</button></form>{% endif %}</div></td></tr>{% endfor %}</table></section></main><footer>Freddy Rojas · Cada registro conserva usuario y fecha/hora</footer></body></html>""",title="Usuarios",items=items)


@app.route("/usuarios/<int:uid>/editar",methods=["GET","POST"])
@admin_required
def edit_user(uid):
    u=db.get_or_404(User,uid)
    if request.method=="POST":
        username=request.form.get("username","").strip()
        role=request.form.get("role","caja")
        areas=request.form.getlist("areas")
        password=request.form.get("password","")
        duplicate=User.query.filter(User.username==username,User.id!=u.id).first()
        if not username or duplicate or role not in AREAS or (role=="admin" and u.role!="admin"):
            flash("Revisá el nombre de usuario y el área principal.")
        else:
            if u.role=="admin" and role!="admin" and User.query.filter_by(role="admin",active=True).count()<=1:
                flash("No se puede quitar el rol al único administrador activo.")
                return redirect(url_for("edit_user",uid=u.id))
            active_value=request.form.get("active")=="on"
            if u.id==current_user().id and not active_value:
                flash("No podés desactivar tu propia cuenta.")
                return redirect(url_for("edit_user",uid=u.id))
            if password and len(password)<10:
                flash("La nueva contraseña debe tener al menos 10 caracteres.")
                return redirect(url_for("edit_user",uid=u.id))
            u.username=username; u.role=role
            areas=[a for a in dict.fromkeys(areas+[role]) if a in AREAS]
            if role=="admin": areas=list(AREAS.keys())
            u.areas=",".join(areas); u.active=active_value
            if password: u.password_hash=generate_password_hash(password)
            db.session.flush()
            log_action("editar usuario","usuarios",u.id,f"Usuario {u.username}; rol {u.role}; áreas {u.areas}; activo {u.active}; contraseña {'actualizada' if password else 'sin cambios'}")
            db.session.commit(); flash("Usuario actualizado.")
            return redirect(url_for("users"))
    selected=(u.areas or "").split(",")
    return render_template_string(BASE+"""
    <section class="card" style="max-width:760px"><h2>Editar usuario: {{u.username}}</h2>
    <form method="post"><label>Nombre de usuario</label><input name="username" value="{{u.username}}" required>
    <label>Rol principal</label><select name="role">{% for k,v in AREAS.items() %}{% if k!='admin' or u.role=='admin' %}<option value="{{k}}" {% if u.role==k %}selected{% endif %}>{{v}}</option>{% endif %}{% endfor %}</select>
    <label>Áreas permitidas</label>{% for k,v in AREAS.items() %}{% if k!='admin' or u.role=='admin' %}<label style="font-weight:400"><input style="width:auto" type="checkbox" name="areas" value="{{k}}" {% if k in selected %}checked{% endif %}> {{v}}</label>{% endif %}{% endfor %}
    <label>Nueva contraseña (opcional; dejar vacío para conservarla)</label><input type="password" name="password" minlength="10">
    <label><input style="width:auto" type="checkbox" name="active" {% if u.active %}checked{% endif %}> Usuario activo</label>
    <p class="actions"><button class="btn">Guardar cambios</button> <a class="btn" href="{{url_for('users')}}">Cancelar</a></p></form></section></main><footer>El Toro S.A.</footer></body></html>""",title="Editar usuario",u=u,selected=selected)


@app.post("/usuarios/<int:uid>/eliminar")
@admin_required
def delete_user(uid):
    u=db.get_or_404(User,uid)
    if u.id==current_user().id:
        flash("No podés eliminar tu propia cuenta.")
        return redirect(url_for("users"))
    if u.role=="admin" and u.active and User.query.filter_by(role="admin",active=True).count()<=1:
        flash("No se puede eliminar al único administrador activo.")
        return redirect(url_for("users"))
    username=u.username
    # Desactivar en lugar de borrar físicamente para conservar la trazabilidad histórica.
    u.active=False
    log_action("desactivar usuario","usuarios",u.id,f"Desactivado por {current_user().username}; usuario {username}")
    db.session.commit()
    flash("Usuario desactivado; se conservan los registros históricos.")
    return redirect(url_for("users"))


@app.get("/accesos")
@admin_required
def access_report():
    rows = db.session.query(AuditLog, User.username).outerjoin(User, AuditLog.user_id == User.id).filter(
        AuditLog.action.in_(["inicio de sesión", "cerrar sesión"])
    ).order_by(AuditLog.created_at.desc()).limit(500).all()
    return render_template_string(BASE + """
    <section class="card"><h2>Informe de accesos</h2><p>Últimos 500 ingresos y cierres de sesión registrados.</p>
    <div style="overflow-x:auto"><table><tr><th>Fecha y hora (UTC)</th><th>Usuario</th><th>Evento</th></tr>
    {% for entry, username in rows %}<tr><td>{{entry.created_at.strftime('%d/%m/%Y %H:%M:%S')}}</td><td>{{username or 'Usuario eliminado'}}</td><td>{{entry.action}}</td></tr>{% else %}<tr><td colspan="3">Todavía no hay accesos registrados.</td></tr>{% endfor %}
    </table></div></section></main><footer>El Toro S.A. · Registro de accesos</footer></body></html>
    """, title="Informe de accesos", rows=rows)


@app.route("/mi-cuenta/contrasena", methods=["GET","POST"])
@login_required
def change_password():
    u = current_user()
    if u.role != "admin":
        abort(403)
    if request.method == "POST":
        current = request.form.get("current_password","")
        new = request.form.get("new_password","")
        confirm = request.form.get("confirm_password","")
        if not check_password_hash(u.password_hash, current):
            flash("La contraseña actual no coincide.")
        elif len(new) < 12:
            flash("La nueva contraseña debe tener al menos 12 caracteres.")
        elif new != confirm:
            flash("La confirmación no coincide.")
        else:
            u.password_hash = generate_password_hash(new)
            log_action("cambiar contraseña","usuarios",u.id,"El usuario cambió su contraseña.")
            db.session.commit()
            flash("Contraseña cambiada correctamente.")
            return redirect(url_for("index"))
    return render_template_string(BASE + """
    <section class="card" style="max-width:520px"><h2>Mi contraseña</h2>
    <form method="post"><label>Contraseña actual</label><input type="password" name="current_password" autocomplete="current-password" required>
    <label>Nueva contraseña (mínimo 12 caracteres)</label><input type="password" name="new_password" minlength="12" autocomplete="new-password" required>
    <label>Confirmar nueva contraseña</label><input type="password" name="confirm_password" minlength="12" autocomplete="new-password" required>
    <p><button class="btn">Cambiar contraseña</button></p></form></section>
    </main><footer>Freddy Rojas · Cada registro conserva usuario y fecha/hora</footer></body></html>
    """, title="Mi contraseña")

@app.get("/informes")
@login_required
def reports():
    available=[(key,meta[0]) for key,meta in MODULES.items() if allowed(key)]
    return render_template_string(BASE+"""
    <section class="card"><h2>Informes por sector</h2><p>Elegí un sector para consultar e imprimir sus operaciones registradas.</p>
    <div class="grid">{% for key,label in available %}<div class="card"><h3>{{label}}</h3><p><a class="btn" href="{{url_for('report_module',module=key)}}">Abrir informe</a></p></div>{% endfor %}</div>
    <p><a class="btn" href="{{url_for('general_history')}}">Historial general</a></p></section></main><footer>El Toro S.A.</footer></body></html>""",title="Informes",available=available)

@app.get("/informes/<module>")
@login_required
def report_module(module):
    if module not in MODULES: abort(404)
    if not allowed(module): abort(403)
    q=request.args.get("q","").strip().casefold(); since=request.args.get("desde",""); until=request.args.get("hasta",""); amount_filter=request.args.get("monto","").strip()
    items=Record.query.filter_by(module=module).order_by(Record.created_at.desc()).all(); results=[]
    for r in items:
        d=json.loads(r.data or "{}"); hay=(r.title+" "+r.status+" "+str(r.amount)+" "+r.data).casefold()
        if q and q not in hay: continue
        if since and r.created_at.strftime("%Y-%m-%d")<since: continue
        if until and r.created_at.strftime("%Y-%m-%d")>until: continue
        if amount_filter and amount_filter not in str(r.amount): continue
        results.append((r,d))
    return render_template_string(BASE+"""
    <section class="card"><h2>Informe: {{label}}</h2><form method="get" class="grid">
    <div><label>Buscar cualquier dato</label><input name="q" value="{{q}}"></div><div><label>Desde</label><input type="date" name="desde" value="{{since}}"></div><div><label>Hasta</label><input type="date" name="hasta" value="{{until}}"></div><div><label>Monto</label><input name="monto" value="{{amount_filter}}"></div>
    <div style="align-self:end"><button class="btn">Buscar</button> <a class="btn" href="{{url_for('report_module',module=module)}}">Limpiar</a></div></form>
    <p><button class="btn" type="button" onclick="window.print()">Imprimir informe</button></p>
    <table><tr><th>Fecha/hora</th><th>Operación</th><th>Detalle</th><th>Estado</th><th>Monto</th><th>Imprimir</th></tr>
    {% for r,d in results %}<tr><td>{{r.created_at.strftime('%d/%m/%Y %H:%M')}}</td><td>{{r.title}}</td><td>{% for k,v in d.items() %}{% if v is string %}<div><b>{{k}}:</b> {{v}}</div>{% elif v is sequence and v is not string %}{% for line in v %}{% if line is mapping %}<div>{% for lk,lv in line.items() %}{{lk}}: {{lv}} · {% endfor %}</div>{% else %}{{line}}{% endif %}{% endfor %}{% endif %}{% endfor %}</td><td>{{r.status}}</td><td>{{r.amount}}</td><td><a class="btn" href="{{url_for('print_record',rid=r.id)}}">Imprimir</a></td></tr>{% endfor %}</table></section></main><footer>El Toro S.A.</footer></body></html>""",title="Informe "+label if False else "Informe",label=MODULES[module][0],module=module,q=q,since=since,until=until,amount_filter=amount_filter,results=results)

@app.get("/historial")
@login_required
def general_history():
    available=[key for key in MODULES if allowed(key)]
    q=request.args.get("q","").strip().casefold(); sector=request.args.get("sector",""); since=request.args.get("desde",""); until=request.args.get("hasta",""); amount_filter=request.args.get("monto","").strip()
    items=Record.query.order_by(Record.created_at.desc()).all(); results=[]
    for r in items:
        if r.module not in available: continue
        d=json.loads(r.data or "{}"); hay=(r.title+" "+r.module+" "+r.status+" "+str(r.amount)+" "+r.data).casefold()
        if sector and r.module!=sector: continue
        if q and q not in hay: continue
        if since and r.created_at.strftime("%Y-%m-%d")<since: continue
        if until and r.created_at.strftime("%Y-%m-%d")>until: continue
        if amount_filter and amount_filter not in str(r.amount): continue
        results.append((r,d))
    sectors=[(k,MODULES[k][0]) for k in available]
    return render_template_string(BASE+"""
    <section class="card"><h2>Historial general</h2><form method="get" class="grid"><div><label>Buscar por cualquier información</label><input name="q" value="{{q}}"></div>
    <div><label>Sector</label><select name="sector"><option value="">Todos los sectores</option>{% for k,v in sectors %}<option value="{{k}}" {% if sector==k %}selected{% endif %}>{{v}}</option>{% endfor %}</select></div>
    <div><label>Desde</label><input type="date" name="desde" value="{{since}}"></div><div><label>Hasta</label><input type="date" name="hasta" value="{{until}}"></div><div><label>Monto</label><input name="monto" value="{{amount_filter}}"></div>
    <div style="align-self:end"><button class="btn">Buscar</button> <a class="btn" href="{{url_for('general_history')}}">Limpiar</a></div></form><p><button class="btn" type="button" onclick="window.print()">Imprimir historial</button></p>
    <table><tr><th>Fecha/hora</th><th>Sector</th><th>Operación</th><th>Estado</th><th>Monto</th><th>Imprimir</th></tr>{% for r,d in results %}<tr><td>{{r.created_at.strftime('%d/%m/%Y %H:%M')}}</td><td>{{MODULES.get(r.module,(r.module,))[0]}}</td><td>{{r.title}}</td><td>{{r.status}}</td><td>{{r.amount}}</td><td><a class="btn" href="{{url_for('print_record',rid=r.id)}}">Imprimir</a></td></tr>{% endfor %}</table></section></main><footer>El Toro S.A.</footer></body></html>""",title="Historial general",q=q,sector=sector,since=since,until=until,amount_filter=amount_filter,sectors=sectors,results=results)

@app.get("/imprimir/<int:rid>")
@login_required
def print_record(rid):
    rec=db.get_or_404(Record,rid)
    if not allowed(rec.module): abort(403)
    data=json.loads(rec.data or "{}")
    return render_template_string(BASE+"""
    <section class="card"><h2>{{MODULES.get(rec.module,(rec.module,))[0]}}</h2><h3>{{rec.title}}</h3>
    <p><b>Fecha:</b> {{rec.created_at.strftime('%d/%m/%Y %H:%M')}} &nbsp; <b>Estado:</b> {{rec.status}}</p>
    <table><tr><th>Dato</th><th>Información</th></tr>{% for k,v in data.items() %}{% if v is mapping %}<tr><td>{{k}}</td><td>{% for a,b in v.items() %}{{a}}: {{b}}<br>{% endfor %}</td></tr>{% elif v is sequence and v is not string %}<tr><td>{{k}}</td><td>{% for line in v %}{% if line is mapping %}{% for a,b in line.items() %}<b>{{a}}:</b> {{b}} &nbsp; {% endfor %}<br>{% else %}{{line}}<br>{% endif %}{% endfor %}</td></tr>{% else %}<tr><td>{{k}}</td><td>{{v}}</td></tr>{% endif %}{% endfor %}<tr><th>Monto total</th><th>{{rec.amount}}</th></tr></table>
    <p><button class="btn" onclick="window.print()">Imprimir</button> <a class="btn" href="{{url_for('module_page',module=rec.module)}}">Volver al sector</a></p></section></main><footer>El Toro S.A.</footer></body></html>""",title="Imprimir",rec=rec,data=data)

@app.get("/admin/respaldo.json")
@admin_required
def backup_export():
    payload = {
        "app": "El Toro S.A.",
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "warning": "Respaldo manual JSON; almacenar en un lugar privado y seguro.",
        "users": [{"id":u.id,"username":u.username,"role":u.role,"areas":u.areas,"active":u.active,"created_at":u.created_at.isoformat()} for u in User.query.order_by(User.id).all()],
        "materials": [{"id":m.id,"name":m.name,"price":str(m.price),"wholesale_price":str(m.wholesale_price) if m.wholesale_price is not None else None,"unit":m.unit,"stock":str(m.stock),"updated_at":m.updated_at.isoformat() if m.updated_at else None} for m in Material.query.order_by(Material.id).all()],
        "company_accounts": [{"id":a.id,"name":a.name,"bank":a.bank,"number":a.number,"currency":a.currency,"opening_balance":str(a.opening_balance),"balance":str(a.balance),"active":a.active,"created_at":a.created_at.isoformat()} for a in CompanyAccount.query.order_by(CompanyAccount.id).all()],
        "records": [{"id":r.id,"module":r.module,"title":r.title,"data":json.loads(r.data or "{}"),"amount":str(r.amount),"status":r.status,"company_account_id":r.company_account_id,"created_by":r.created_by,"approved_by":r.approved_by,"paid_by":r.paid_by,"created_at":r.created_at.isoformat(),"updated_at":r.updated_at.isoformat()} for r in Record.query.order_by(Record.id).all()],
        "audit_log": [{"id":a.id,"user_id":a.user_id,"action":a.action,"module":a.module,"record_id":a.record_id,"detail":a.detail,"created_at":a.created_at.isoformat()} for a in AuditLog.query.order_by(AuditLog.id).all()]
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    log_action("exportar respaldo manual","backup",None,f"Exportó {len(payload['records'])} registros")
    db.session.commit()
    return send_file(BytesIO(content), mimetype="application/json", as_attachment=True,
                     download_name="el_toro_sa_respaldo_" + datetime.utcnow().strftime("%Y%m%d_%H%M%S") + ".json")

@app.errorhandler(403)
def forbidden(e):
    return render_template_string(BASE+""" <section class="card"><h2>Acceso denegado</h2><p>Tu usuario no tiene permisos para esa acción. Si necesitás acceso, pedí al administrador que te asigne el área correspondiente.</p><a class="btn" href="{{url_for('index')}}">Volver</a></section></main><footer>Freddy Rojas · Cada registro conserva usuario y fecha/hora</footer></body></html>""",title="Acceso denegado"),403

import features  # Registra los módulos financieros y de flota de El Toro S.A.

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT","10000")))
