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
  ("nombre","Material","text",True),("precio","Precio vigente por unidad","number",True),
  ("unidad","Unidad (kg, unidad, litro, etc.)","text",True),("stock","Stock inicial","number",False)]),
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
 "compras": ("Compras", "inventario", [
  ("proveedor","Proveedor","text",True),("material","Material","text",True),("cantidad","Cantidad ingresada","number",True),
  ("precio_unitario","Precio unitario","number",True),("tipo_cambio","Tipo de cambio a PYG si aplica","number",False),("comprobante","Comprobante","text",False)]),
 "ventas": ("Ventas y salidas", "inventario", [
  ("cliente","Cliente","text",True),("material","Material","text",True),("cantidad","Cantidad vendida / salida","number",True),
  ("precio_unitario","Precio unitario","number",True),("moneda","Moneda (PYG / USD)","text",True),("tipo_cambio","Tipo de cambio usado","number",False),("destino","Destino / envío","text",False)]),
 "cuentas_pagar": ("Cuentas por pagar", "tesoreria", [
  ("beneficiario","Beneficiario","text",True),("concepto","Concepto","text",True),("importe","Importe adeudado","number",True),
  ("vencimiento","Vencimiento","date",False),("cheque_adelantado","¿Incluye cheque adelantado? (sí/no)","text",False)]),
 "cuentas_cobrar": ("Cuentas por cobrar", "tesoreria", [
  ("cliente","Cliente","text",True),("concepto","Concepto","text",True),("importe","Importe por cobrar","number",True),
  ("vencimiento","Vencimiento","date",False),("estado","Estado / seguimiento","text",False)]),
 "cheques": ("Cheques adelantados", "tesoreria", [
  ("beneficiario","Beneficiario","text",True),("numero","Número de cheque","text",True),("importe","Importe","number",True),
  ("fecha","Fecha del cheque","date",True),("vencimiento","Fecha de vencimiento","date",True),("estado","Estado","text",True)]),
 "combustible": ("Combustible por camión", "estacion", [
  ("camion","Camión / chapa / código","text",True),("litros","Cantidad cargada (litros)","number",True),
  ("fecha","Fecha y hora de carga","datetime-local",True),("importe","Costo total","number",True),("odometro","Kilometraje / horómetro","number",False),("responsable","Responsable","text",False)]),
 "gomeria": ("Gomería y servicios", "gomeria", [
  ("camion","Camión / chapa / código","text",True),("servicio","Trabajo realizado","text",True),("repuesto","Repuesto utilizado","text",False),
  ("cantidad","Cantidad","number",False),("costo","Costo","number",False),("responsable","Responsable","text",False),("observaciones","Observaciones","text",False)]),
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
<title>{{ title }} · Freddy Rojas</title><style>
:root{font-family:system-ui,Arial;color:#1c2833;background:#f2f5f7}*{box-sizing:border-box}body{margin:0}
header{background:#173b57;color:white;padding:16px 20px;display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}
header a{color:white}main{max-width:1100px;margin:22px auto;padding:0 14px}.card{background:white;border-radius:12px;padding:18px;margin-bottom:15px;box-shadow:0 2px 10px #0000000a}
nav{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 18px}nav a,.btn{background:#e4edf3;color:#173b57;padding:9px 12px;border-radius:8px;text-decoration:none;border:0;display:inline-block;font-weight:600;cursor:pointer}
input,select,textarea{width:100%;padding:10px;border:1px solid #c9d3db;border-radius:7px;font:inherit;background:white}label{display:block;font-size:.92rem;font-weight:600;margin:10px 0 5px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}.muted{color:#61717e}.danger{color:#9e2a2b}.ok{color:#216e39}.warn{background:#fff5d8;padding:12px;border-radius:8px}
table{width:100%;border-collapse:collapse;background:white}th,td{text-align:left;padding:9px;border-bottom:1px solid #e2e7eb;vertical-align:top;overflow-wrap:anywhere}th{background:#f4f7f9}
.small{font-size:.85rem}.actions{display:flex;gap:8px;flex-wrap:wrap}button{font:inherit}footer{text-align:center;color:#667;padding:22px}.flash{background:#e7f5e9;padding:10px;border-radius:7px;margin:8px 0}
</style></head><body><header><div><strong>Freddy Rojas</strong><div class="small">Gestión independiente del negocio</div></div>
<div>{% if user %}{{ user.username }} · {{ AREAS.get(user.role,user.role) }} · <a href="{{ url_for('logout') }}">Salir</a>{% endif %}</div></header>
<main>{% with messages=get_flashed_messages() %}{% for m in messages %}<div class="flash">{{m}}</div>{% endfor %}{% endwith %}
{% if user %}<nav><a href="{{url_for('index')}}">Inicio</a>{% for key,meta in MODULES.items() %}{% if user.role=='admin' or key in (user.areas or '').split(',') or meta[1] in (user.areas or '').split(',') %}<a href="{{url_for('module_page',module=key)}}">{{meta[0]}}</a>{% endif %}{% endfor %}{% if user.role=='admin' %}<a href="{{url_for('users')}}">Usuarios</a>{% endif %}<a href="{{url_for('approvals')}}">Autorizaciones</a><a href="{{url_for('change_password')}}">Mi contraseña</a>{% if user.role=='admin' %}<a href="{{url_for('backup_export')}}">Exportar respaldo</a>{% endif %}</nav>{% endif %}
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
    <section class="card"><h2>Panel de control</h2><p class="muted">Los accesos y las operaciones dependen del área asignada a cada usuario.</p>
    {% if not config.get('DATABASE_URL') %}<p class="warn">Modo de demostración: esta instancia usa almacenamiento local temporal. No cargar operaciones reales hasta conectar una base de datos persistente y configurar copias de seguridad.</p>{% endif %}
    <div class="grid"><div class="card"><h3>Solicitudes pendientes</h3><strong>{{pending}}</strong><p><a href="{{url_for('approvals')}}">Revisar autorizaciones</a></p></div>
    {% if user.role=='admin' %}<div class="card"><h3>Cuentas de El Toro S.A.</h3><p>{{accounts|length}} cuenta(s) activa(s)</p><p>Solo administración puede crear cuentas o corregir saldos.</p></div>{% endif %}
    <div class="card"><h3>Registros recientes</h3><strong>{{records|length}}</strong><p>Los movimientos quedan asociados al usuario y hora.</p></div></div></section>
    <section class="card"><h2>Últimos movimientos</h2>{% if records %}<table><tr><th>Fecha/hora</th><th>Módulo</th><th>Registro</th><th>Estado</th><th>Importe</th></tr>{% for r in records %}<tr><td>{{r.created_at.strftime('%d/%m/%Y %H:%M')}}</td><td>{{MODULES.get(r.module,(r.module,))[0]}}</td><td>{{r.title}}</td><td>{{r.status}}</td><td>{{r.amount}}</td></tr>{% endfor %}</table>{% else %}<p class="muted">Todavía no hay registros.</p>{% endif %}</section>
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
            name = request.form.get("nombre","").strip()
            if not name: flash("El material requiere nombre.")
            else:
                try:
                    price = Decimal(request.form.get("precio","0") or "0")
                    stock = Decimal(request.form.get("stock","0") or "0")
                    if price < 0 or stock < 0: raise InvalidOperation()
                    m = Material(name=name,price=price,unit=request.form.get("unidad","kg").strip() or "kg",stock=stock)
                    db.session.add(m); db.session.flush()
                    log_action("crear material y precio","materiales",m.id,name)
                    db.session.commit(); flash("Material guardado.")
                except (InvalidOperation, ValueError):
                    db.session.rollback(); flash("Precio o stock inválido.")
                return redirect(url_for("module_page",module=module))
        items = Material.query.order_by(Material.name).all()
        return render_template_string(BASE + """
        <section class="card"><h2>{{title}}</h2><p class="muted">Solo administración puede agregar materiales y cambiar precios. Los tickets conservan el precio aplicado.</p>
        <form method="post" class="grid">{% for key,label,kind,req in fields %}<div><label>{{label}}</label><input name="{{key}}" type="{{kind}}" {% if req %}required{% endif %} {% if kind=='number' %}step="0.001" min="0"{% endif %}></div>{% endfor %}<div style="align-self:end"><button class="btn">Guardar material</button></div></form></section>
        <section class="card"><h2>Materiales vigentes</h2><table><tr><th>Material</th><th>Precio</th><th>Unidad</th><th>Stock</th><th>Actualizar precio</th></tr>{% for m in items %}<tr><td>{{m.name}}</td><td>{{m.price}}</td><td>{{m.unit}}</td><td>{{m.stock}}</td><td><form method="post" action="{{url_for('update_material_price',mid=m.id)}}" class="actions"><input aria-label="Nuevo precio" name="precio" type="number" step="0.01" min="0" required><button class="btn">Guardar precio</button></form></td></tr>{% endfor %}</table></section></main><footer>Freddy Rojas · Cada registro conserva usuario y fecha/hora</footer></body></html>""", title=title, fields=fields, items=items)
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
    if request.method == "POST":
        data = {key: request.form.get(key,"").strip() for key,label,kind,req in fields}
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
        if module == "compras":
            mat=Material.query.filter(db.func.lower(Material.name)==data.get("material","").lower()).first()
            if mat:
                try: mat.stock += Decimal(data.get("cantidad","0").replace(",","."))
                except InvalidOperation: pass
        if module in ("ventas","movimientos_stock"):
            if module=="ventas":
                mat=Material.query.filter(db.func.lower(Material.name)==data.get("material","").lower()).first()
                if mat:
                    try: mat.stock -= Decimal(data.get("cantidad","0").replace(",","."))
                    except InvalidOperation: pass
            if module=="movimientos_stock" and data.get("tipo","").lower() in ("uso","salida"):
                # Hydraulic spare parts remain traceable in this movement record.
                pass
        db.session.commit(); flash("Registro guardado con usuario y fecha/hora."); return redirect(url_for("module_page",module=module))
    items=Record.query.filter_by(module=module).order_by(Record.created_at.desc()).limit(100).all()
    parsed=[(r,json.loads(r.data or "{}")) for r in items]
    return render_template_string(BASE+"""
    <section class="card"><h2>{{title}}</h2><form method="post" class="grid">
    {% for key,label,kind,req in fields %}<div><label>{{label}}</label><input name="{{key}}" type="{{kind}}" {% if req %}required{% endif %} {% if kind=='number' %}step="0.001"{% endif %}></div>{% endfor %}
    <div style="align-self:end"><button class="btn">Guardar registro</button></div></form>
    {% if module=='tickets' %}<p class="muted small">El precio se toma del material vigente si coincide su nombre. Revisá el total antes de solicitar el pago.</p>{% endif %}
    </section><section class="card"><h2>Historial reciente</h2>{% if parsed %}<table><tr><th>Fecha/hora</th><th>Registro</th><th>Detalle</th><th>Estado</th><th>Importe</th></tr>
    {% for r,d in parsed %}<tr><td>{{r.created_at.strftime('%d/%m/%Y %H:%M')}}</td><td>{{r.title}}</td><td>{% for k,v in d.items() %}<div><b>{{k}}:</b> {{v}}</div>{% endfor %}</td><td>{{r.status}}</td><td>{{r.amount}}</td></tr>{% endfor %}</table>{% else %}<p class="muted">No hay registros todavía.</p>{% endif %}</section></main><footer>Freddy Rojas · Cada registro conserva usuario y fecha/hora</footer></body></html>""",title=title,fields=fields,module=module,parsed=parsed)


@app.post("/materiales/<int:mid>/precio")
@admin_required
def update_material_price(mid):
    material = db.get_or_404(Material, mid)
    try:
        new_price = Decimal(request.form.get("precio","").replace(",","."))
        if new_price < 0: raise InvalidOperation()
    except (InvalidOperation, ValueError):
        flash("El precio debe ser un número válido igual o mayor que cero.")
        return redirect(url_for("module_page", module="materiales"))
    old_price = material.price
    material.price = new_price
    log_action("cambio de precio de material", "materiales", material.id,
               f"{material.name}: {old_price} -> {new_price}; precio nuevo solo para tickets futuros")
    db.session.commit()
    flash("Precio actualizado. Los tickets anteriores conservan su precio histórico.")
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
    <section class="card"><h2>Usuarios y permisos</h2><p>El administrador crea usuarios, asigna un área principal y puede asignar áreas adicionales. Los permisos también se comprueban en el servidor.</p>
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

@app.get("/admin/respaldo.json")
@admin_required
def backup_export():
    payload = {
        "app": "Freddy Rojas",
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "warning": "Respaldo manual JSON; almacenar en un lugar privado y seguro.",
        "users": [{"id":u.id,"username":u.username,"role":u.role,"areas":u.areas,"active":u.active,"created_at":u.created_at.isoformat()} for u in User.query.order_by(User.id).all()],
        "materials": [{"id":m.id,"name":m.name,"price":str(m.price),"unit":m.unit,"stock":str(m.stock),"updated_at":m.updated_at.isoformat() if m.updated_at else None} for m in Material.query.order_by(Material.id).all()],
        "company_accounts": [{"id":a.id,"name":a.name,"bank":a.bank,"number":a.number,"currency":a.currency,"opening_balance":str(a.opening_balance),"balance":str(a.balance),"active":a.active,"created_at":a.created_at.isoformat()} for a in CompanyAccount.query.order_by(CompanyAccount.id).all()],
        "records": [{"id":r.id,"module":r.module,"title":r.title,"data":json.loads(r.data or "{}"),"amount":str(r.amount),"status":r.status,"company_account_id":r.company_account_id,"created_by":r.created_by,"approved_by":r.approved_by,"paid_by":r.paid_by,"created_at":r.created_at.isoformat(),"updated_at":r.updated_at.isoformat()} for r in Record.query.order_by(Record.id).all()],
        "audit_log": [{"id":a.id,"user_id":a.user_id,"action":a.action,"module":a.module,"record_id":a.record_id,"detail":a.detail,"created_at":a.created_at.isoformat()} for a in AuditLog.query.order_by(AuditLog.id).all()]
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    log_action("exportar respaldo manual","backup",None,f"Exportó {len(payload['records'])} registros")
    db.session.commit()
    return send_file(BytesIO(content), mimetype="application/json", as_attachment=True,
                     download_name="freddy_rojas_respaldo_" + datetime.utcnow().strftime("%Y%m%d_%H%M%S") + ".json")

@app.errorhandler(403)
def forbidden(e):
    return render_template_string(BASE+""" <section class="card"><h2>Acceso denegado</h2><p>Tu usuario no tiene permisos para esa acción. Si necesitás acceso, pedí al administrador que te asigne el área correspondiente.</p><a class="btn" href="{{url_for('index')}}">Volver</a></section></main><footer>Freddy Rojas · Cada registro conserva usuario y fecha/hora</footer></body></html>""",title="Acceso denegado"),403

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT","10000")))
