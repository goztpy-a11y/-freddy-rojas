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
 "clientes": ("Clientes y proveedores", "caja", [
  ("nombre","Nombre / razón social","text",True),("documento","RUC / documento","text",False),
  ("telefono","Teléfono","text",False),("direccion","Dirección","text",False),
  ("datos_bancarios","Datos bancarios del cliente (no cuenta de la empresa)","text",False)]),
 "materiales": ("Materiales y precios", "admin", [
  ("nombre","Material","text",True),("precio_minorista","Precio minorista (opcional)","number",False),
  ("precio_mayorista","Precio mayorista (opcional)","number",False)]),
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
  ("repuesto","Repuesto","text",True),("tipo","Movimiento (entrada / uso / salida)","text",True),
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
    if initial_password and not User.query.filter_by(username=os.environ.get("ADMIN_USERNAME", "admin")).first():
        db.session.add(User(username=os.environ.get("ADMIN_USERNAME", "admin"),
            password_hash=generate_password_hash(initial_password), role="admin", areas=",".join(AREAS.keys())))
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
    assigned = (user.areas or "").split(",")
    required_area = MODULES.get(module, (None, module))[1]
    return module in assigned or required_area in assigned

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
<title>{{ title }} · El Toro S.A.</title><style>
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
</style></head><body><header><div><strong>El Toro S.A.</strong><div class="small">Sistema de gestión empresarial</div></div>
<div>{% if user %}<span>{{ user.username }} · {{ AREAS.get(user.role,user.role) }}</span> · <button class="print-page" type="button" onclick="window.print()">Imprimir</button> · <a href="{{ url_for('logout') }}">Cerrar sesión</a>{% endif %}</div></header>
{% if user %}<aside class="sidebar"><div class="sidebar-brand"><div class="brand-mark">ET</div><div class="brand-copy"><strong>EL TORO S.A.</strong><span>GESTIÓN EMPRESARIAL</span></div></div>
<nav><a href="{{url_for('index')}}">⌂ &nbsp; Panel principal</a><a href="{{url_for('reports')}}">Informes</a><a href="{{url_for('general_history')}}">Historial general</a><a href="{{url_for('pagos_diarios')}}">Pagos diarios</a><a href="{{url_for('prestamos')}}">Préstamos</a><a href="{{url_for('proveedores')}}">Proveedores y precios</a><a href="{{url_for('planillas')}}">Cuenta de proveedores</a><a href="{{url_for('fletes')}}">Fletes</a><a href="{{url_for('flota')}}">Camiones y retiros</a><a href="{{url_for('combustible_stock')}}">Stock y cargas de combustible</a><a href="{{url_for('mantenimiento')}}">Mantenimiento de flota</a><a href="{{url_for('gomeria_camiones')}}">Gomería por camión</a><a href="{{url_for('auditoria_pagos')}}">Auditoría de pagos</a>{% for key,meta in MODULES.items() %}{% if user.role=='admin' or key in (user.areas or '').split(',') or meta[1] in (user.areas or '').split(',') %}<a href="{{url_for('module_page',module=key)}}">{{meta[0]}}</a>{% endif %}{% endfor %}{% if user.role=='admin' %}<a href="{{url_for('users')}}">Usuarios y permisos</a>{% endif %}<a href="{{url_for('approvals')}}">Autorizaciones</a><a href="{{url_for('change_password')}}">Mi contraseña</a>{% if user.role=='admin' %}<a href="{{url_for('backup_export')}}">Exportar respaldo</a>{% endif %}</nav></aside>{% endif %}
<main>{% with messages=get_flashed_messages() %}{% for m in messages %}<div class="flash">{{m}}</div>{% endfor %}{% endwith %}
"""

@app.context_processor
def inject_globals():
    return {"user": current_user(), "AREAS": AREAS, "MODULES": MODULES, "now": datetime.now()}

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
    records = Record.query.order_by(Record.created_at.desc()).limit(8).all()
    pending = Record.query.filter_by(module="solicitudes",status="Pendiente de autorización").count()
    accounts = CompanyAccount.query.filter_by(active=True).all() if u.role == "admin" else []
    return render_template_string(BASE + """
    <section class="card dashboard-overview"><h2>Resumen ejecutivo</h2>
    {% if not config.get('DATABASE_URL') %}<p class="warn">Modo de demostración: esta instancia usa almacenamiento local temporal. No cargar operaciones reales hasta conectar una base de datos persistente y configurar copias de seguridad.</p>{% endif %}
    <div class="grid"><div class="card"><h3>Solicitudes pendientes</h3><strong>{{pending}}</strong><p><a href="{{url_for('approvals')}}">Ver autorizaciones&nbsp; →</a></p></div>
    {% if user.role=='admin' %}<div class="card"><h3>Cuentas empresariales activas</h3><strong>{{accounts|length}}</strong><p><a href="{{url_for('module_page',module='cuentas_empresa')}}">Consultar cuentas&nbsp; →</a></p></div>{% endif %}
    <div class="card"><h3>Movimientos recientes</h3><strong>{{records|length}}</strong><p><a href="#ultimos-movimientos">Ver actividad&nbsp; →</a></p></div></div></section>
    <section class="card" id="ultimos-movimientos"><h2>Actividad reciente</h2>{% if records %}<table><tr><th>Fecha/hora</th><th>Módulo</th><th>Registro</th><th>Estado</th><th>Importe</th></tr>{% for r in records %}<tr><td>{{r.created_at.strftime('%d/%m/%Y %H:%M')}}</td><td>{{MODULES.get(r.module,(r.module,))[0]}}</td><td>{{r.title}}</td><td>{{r.status}}</td><td>{{r.amount}}</td></tr>{% endfor %}</table>{% else %}<p class="muted">Todavía no hay registros.</p>{% endif %}</section>
    </main><footer>Freddy Rojas · Cada registro conserva usuario y fecha/hora</footer></body></html>""", title="Inicio", pending=pending, accounts=accounts, records=records)

@app.route("/modulo/<module>", methods=["GET","POST"])
@login_required
def module_page(module):
    if module not in MODULES: abort(404)
    if not allowed(module):
        flash("Tu usuario no tiene permiso para acceder a este módulo.")
        abort(403)
    title, area, fields = MODULES[module]
    if module == "materiales":
        if request.method == "POST":
            name=request.form.get("nombre","").strip()
            minor=request.form.get("precio_minorista","").strip().replace(",",".")
            major=request.form.get("precio_mayorista","").strip().replace(",",".")
            if not name: flash("Ingresá el nombre del material.")
            elif Material.query.filter(db.func.lower(Material.name)==name.lower()).first(): flash("Ese material ya existe. Actualizá sus precios desde el listado.")
            else:
                try:
                    pminor=Decimal(minor) if minor else Decimal("0")
                    pmajor=Decimal(major) if major else None
                    if pminor<0 or (pmajor is not None and pmajor<0): raise InvalidOperation()
                    m=Material(name=name,price=pminor,wholesale_price=pmajor,unit="kg",stock=0)
                    db.session.add(m); db.session.flush()
                    log_action("crear material y precios","materiales",m.id,f"{name}; minorista={minor or 'no definido'}; mayorista={major or 'no definido'}")
                    db.session.commit(); flash("Material guardado.")
                except (InvalidOperation,ValueError): db.session.rollback(); flash("Los precios deben ser números válidos.")
            return redirect(url_for("module_page",module=module))
        items=Material.query.order_by(Material.name).all()
        return render_template_string(BASE+"""
        <section class="card"><h2>{{title}}</h2><form method="post" class="grid">
        <div><label>Nombre del material</label><input name="nombre" required></div>
        <div><label>Precio minorista (opcional)</label><input name="precio_minorista" type="number" min="0" step="0.01"></div>
        <div><label>Precio mayorista (opcional)</label><input name="precio_mayorista" type="number" min="0" step="0.01"></div>
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
            data={"cliente":client,"materiales":lines,"tipo_precio":price_type,"cuenta_cliente":request.form.get("cuenta_cliente","").strip(),"observaciones":request.form.get("observaciones","").strip(),"total":str(total)}
            rec=Record(module="tickets",title=client,data=json.dumps(data,ensure_ascii=False),amount=total,status="Pendiente de pago",created_by=current_user().id)
            db.session.add(rec); db.session.flush(); log_action("crear ticket de entrada","tickets",rec.id,f"{client}; total {total}"); db.session.commit()
            flash("Ticket guardado."); return redirect(url_for("module_page",module=module))
        q=request.args.get("q","").strip().casefold(); hist=Record.query.filter_by(module="tickets").order_by(Record.created_at.desc()).all()
        parsed=[(r,json.loads(r.data or "{}")) for r in hist if not q or q in (r.title+" "+r.data+" "+str(r.amount)).casefold()]
        return render_template_string(BASE+"""
        <section class="card"><h2>{{title}}</h2><form method="post" id="ticket-form"><div class="grid">
        <div><label>Cliente / proveedor</label><input name="cliente" required></div><div><label>Tipo de precio</label><select name="tipo_precio"><option value="minorista">Minorista</option><option value="mayorista">Mayorista</option></select></div>
        <div><label>Cuenta bancaria del cliente (opcional)</label><input name="cuenta_cliente"></div><div><label>Observaciones</label><input name="observaciones"></div></div>
        <h3>Materiales del ticket</h3><div id="ticket-lines"><div class="grid ticket-line"><div><label>Material</label><select name="material" required><option value="">Seleccionar material</option>{% for m in materials %}<option value="{{m.name}}">{{m.name}}</option>{% endfor %}</select></div><div><label>Cantidad / kg</label><input name="cantidad" type="number" min="0.001" step="0.001" required></div></div></div>
        <p><button type="button" class="btn" onclick="addTicketLine()">+ Agregar material</button></p><button class="btn">Guardar ticket</button></form></section>
        <section class="card"><h2>Historial de tickets</h2><form method="get" class="actions"><input name="q" placeholder="Buscar cliente, material, monto..." value="{{q}}"><button class="btn">Buscar</button><a class="btn" href="{{url_for('module_page',module='tickets')}}">Limpiar</a></form><p><button class="btn" type="button" onclick="window.print()">Imprimir listado</button></p>
        <table><tr><th>Fecha/hora</th><th>Cliente</th><th>Materiales</th><th>Estado</th><th>Total</th><th>Acciones</th></tr>{% for r,d in parsed %}<tr><td>{{r.created_at.strftime('%d/%m/%Y %H:%M')}}</td><td>{{r.title}}</td><td>{% for line in d.get('materiales',[]) %}{{line.material}} · {{line.cantidad}} · {{line.total}}<br>{% endfor %}</td><td>{{r.status}}</td><td>{{r.amount}}</td><td><a class="btn" href="{{url_for('print_record',rid=r.id)}}">Imprimir ticket</a></td></tr>{% endfor %}</table></section>
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
        q=request.args.get("q","").strip().casefold()
        items=[r for r in items if not q or q in (r.title+" "+r.data+" "+str(r.amount)).casefold()]
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
        <section class="card"><h2>Historial de gastos</h2><form class="actions"><input name="q" value="{{q}}" placeholder="Buscar artículo, concepto, comprobante"><button>Buscar</button><button type="button" onclick="window.print()">Imprimir</button></form>
        <table><tr><th>Fecha</th><th>Categoría</th><th>Detalle</th><th>Medio</th><th>Total</th><th>Estado</th><th>Imprimir</th></tr>
        {% for r in items %}{% set d=decode(r) %}<tr><td>{{d.get('fecha')}}</td><td>{{d.get('categoria')}}</td><td>{% for x in d.get('items',[]) %}{{x.get('articulo')}} · {{x.get('cantidad')}} × {{x.get('precio_unitario')}} = {{x.get('subtotal')}}<br>{% endfor %}</td><td>{{d.get('medio')}}</td><td>{{r.amount}}</td><td>{{r.status}}</td><td><a class="btn" href="{{url_for('print_record',rid=r.id)}}">Imprimir</a></td></tr>{% endfor %}</table></section></main><footer>El Toro S.A.</footer></body></html>
        """,title=title,items=items,q=q,today=datetime.now().strftime("%Y-%m-%d"),decode=lambda r:json.loads(r.data or "{}"))
    if module in ("cuentas_pagar","cuentas_cobrar","cheques"):
        payment_rows=Record.query.filter_by(module="pagos_cuentas").order_by(Record.created_at.desc()).all()
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
                              if json.loads(p.data or "{}").get("modulo_origen")==module and str(json.loads(p.data or "{}").get("registro_id"))==str(rid)),Decimal("0"))
                    balance=original.amount-paid
                    if amount<=0 or amount>balance: raise InvalidOperation()
                    paydata={"modulo_origen":module,"registro_id":rid,"fecha":request.form.get("fecha",""),
                        "beneficiario":original_data.get("beneficiario",original_data.get("cliente","")),
                        "concepto":original_data.get("concepto",""),"numero_cheque":original_data.get("numero",""),
                        "importe":str(amount),"medio":request.form.get("medio","Efectivo"),"detalle":request.form.get("detalle","")}
                    pay=Record(module="pagos_cuentas",title="Pago · "+original.title,data=json.dumps(paydata,ensure_ascii=False),
                        amount=amount,status="Pagado",created_by=current_user().id)
                    db.session.add(pay); db.session.flush()
                    new_balance=balance-amount
                    original.status="Pagado" if new_balance==0 else "Pago parcial"
                    log_action("registrar pago parcial/final",module,original.id,f"Pago {amount}; saldo {new_balance}; medio {paydata['medio']}")
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
                              if json.loads(p.data or "{}").get("modulo_origen")==module and str(json.loads(p.data or "{}").get("registro_id"))==str(rid)),Decimal("0"))
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
                      if json.loads(p.data or "{}").get("modulo_origen")==module and str(json.loads(p.data or "{}").get("registro_id"))==str(rec.id)),Decimal("0"))
            summaries.append((rec,d,paid,max(Decimal("0"),rec.amount-paid)))
        return render_template_string(BASE+"""
        <section class="card"><h2>{{title}}</h2><form method="post" class="grid">
        {% for key,label,kind,req in fields %}<div><label>{{label}}</label>
        {% if kind=='checkbox' %}<label><input type="checkbox" name="{{key}}" value="Sí" style="width:auto"> Incluye cheque adelantado</label>
        {% elif kind=='select' and module=='cuentas_cobrar' %}<select name="{{key}}"><option>Pendiente</option><option>En proceso</option><option>Pagado</option><option>Atrasado</option></select>
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
    {% elif kind=='select' and module=='cuentas_cobrar' %}<select name="{{key}}"><option>Pendiente</option><option>En proceso</option><option>Pagado</option><option>Atrasado</option></select>
    {% elif kind=='select' and module=='cheques' %}<select name="{{key}}" required><option>Pendiente</option><option>Desembolsado</option></select>
     {% elif kind=='select' and module=='gomeria' %}<select name="{{key}}" required><option value="Reparación de cubierta">Reparación de cubierta</option><option value="Cambio de cubierta">Cambio de cubierta</option><option value="Reparación de cámara">Reparación de cámara</option><option value="Cambio de cámara">Cambio de cámara</option><option value="Otro">Otro</option></select>
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
    if u.role!="admin" and not allowed("solicitudes") and not allowed("tesoreria"): abort(403)
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
        if not username or len(password)<10 or role not in AREAS:
            flash("Usuario requerido, contraseña mínima de 10 caracteres y área válida.")
        elif User.query.filter_by(username=username).first():
            flash("Ese usuario ya existe.")
        else:
            areas=list(dict.fromkeys(areas+[role]))
            u=User(username=username,password_hash=generate_password_hash(password),role=role,areas=",".join(areas))
            db.session.add(u); db.session.flush(); log_action("crear usuario","usuarios",u.id,f"{username}; rol {role}; áreas {u.areas}")
            db.session.commit(); flash("Usuario creado."); return redirect(url_for("users"))
    items=User.query.order_by(User.username).all()
    return render_template_string(BASE+"""
    <section class="card"><h2>Usuarios y permisos</h2>
    <form method="post" class="grid"><div><label>Usuario</label><input name="username" required></div><div><label>Contraseña inicial (mínimo 10 caracteres)</label><input type="password" name="password" minlength="10" required></div>
    <div><label>Área / rol principal</label><select name="role">{% for k,v in AREAS.items() %}<option value="{{k}}">{{v}}</option>{% endfor %}</select></div><div><label>Áreas adicionales</label>{% for k,v in AREAS.items() %}<label style="font-weight:400"><input style="width:auto" type="checkbox" name="areas" value="{{k}}"> {{v}}</label>{% endfor %}</div><div style="align-self:end"><button class="btn">Crear usuario</button></div></form></section>
    <section class="card"><h2>Usuarios existentes</h2><table><tr><th>Usuario</th><th>Rol</th><th>Áreas asignadas</th><th>Activo</th><th>Creado</th></tr>{% for u in items %}<tr><td>{{u.username}}</td><td>{{AREAS.get(u.role,u.role)}}</td><td>{{u.areas}}</td><td>{{'Sí' if u.active else 'No'}}</td><td>{{u.created_at.strftime('%d/%m/%Y %H:%M')}}</td></tr>{% endfor %}</table></section></main><footer>Freddy Rojas · Cada registro conserva usuario y fecha/hora</footer></body></html>""",title="Usuarios",items=items)


@app.route("/mi-cuenta/contrasena", methods=["GET","POST"])
@login_required
def change_password():
    u = current_user()
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
