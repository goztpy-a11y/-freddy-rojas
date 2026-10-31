# Inventario independiente de Depósito Operativo para Freddy Rojas.
# Comparte el rol Inventario, pero usa registros y saldos separados de materiales y Gomería.
import json
from decimal import Decimal, InvalidOperation
from flask import request, redirect, url_for, flash, abort
import app as app_module
from app import app, db, Record, MODULES, current_user, login_required, log_action, paraguay_now
from features import _data, _page

PRODUCTS = "deposito_productos"
MOVEMENTS = "deposito_movimientos"

app.config.setdefault("DEPOSITO_OPERATIVO_ENABLED", True)

# Los registros se guardan en Record con claves internas propias; no se publican como módulos genéricos.

_original_allowed = app_module.allowed
def _allowed_with_deposito(module):
    user = current_user()
    if user and user.role == "admin":
        return True
    assigned = {area.strip() for area in (user.areas or "").split(",") if area.strip()} if user else set()
    if ("inventario" in assigned or "estacion" in assigned) and module in {PRODUCTS, MOVEMENTS, "deposito_operativo"}:
        return True
    return _original_allowed(module)

app_module.allowed = _allowed_with_deposito

def _can_deposito():
    user = current_user()
    assigned = {area.strip() for area in (user.areas or "").split(",") if area.strip()} if user else set()
    if not user or not (user.role == "admin" or "inventario" in assigned or "estacion" in assigned):
        abort(403)

def _products():
    return Record.query.filter_by(module=PRODUCTS).order_by(Record.title.asc()).all()

def _stock_data(record):
    data = _data(record)
    try:
        stock = Decimal(str(data.get("stock", "0") or "0"))
    except (InvalidOperation, ValueError, TypeError):
        stock = Decimal("0")
    return data, stock

@app.route("/deposito-operativo", methods=["GET", "POST"])
@login_required
def deposito_operativo():
    _can_deposito()
    if request.method == "POST":
        action = request.form.get("accion", "").strip()
        try:
            if action == "producto":
                name = request.form.get("nombre", "").strip()
                brand = request.form.get("marca", "").strip()
                presentation = request.form.get("presentacion", "").strip()
                unit = request.form.get("unidad", "litro").strip()
                minimum = Decimal((request.form.get("stock_minimo", "0").strip() or "0").replace(",", "."))
                if not name or not unit or not minimum.is_finite() or minimum < 0:
                    raise InvalidOperation()
                if any(_data(p).get("nombre", "").casefold() == name.casefold() for p in _products()):
                    flash("Ya existe un producto con ese nombre. Usá el producto existente para registrar una entrada.")
                    return redirect(url_for("deposito_operativo"))
                data = {"nombre": name, "marca": brand, "presentacion": presentation,
                        "unidad": unit, "stock": "0", "stock_minimo": str(minimum),
                        "creado_por": current_user().username}
                rec = Record(module=PRODUCTS, title=name, data=json.dumps(data, ensure_ascii=False),
                             amount=0, status="Activo", created_by=current_user().id)
                db.session.add(rec)
                db.session.flush()
                log_action("crear producto de Depósito Operativo", PRODUCTS, rec.id, name)
                db.session.commit()
                flash("Producto agregado al Depósito Operativo.")
            elif action in ("entrada", "salida"):
                product_id = int(request.form.get("producto_id", "0"))
                qty = Decimal(request.form.get("cantidad", "").strip().replace(",", "."))
                date = request.form.get("fecha", "").strip() or paraguay_now().strftime("%Y-%m-%d")
                detail = request.form.get("detalle", "").strip()
                if not qty.is_finite() or qty <= 0:
                    raise InvalidOperation()
                product = Record.query.filter_by(id=product_id, module=PRODUCTS).with_for_update().first()
                if not product:
                    flash("Seleccioná un producto válido.")
                    return redirect(url_for("deposito_operativo"))
                data, stock = _stock_data(product)
                new_stock = stock + qty if action == "entrada" else stock - qty
                if new_stock < 0:
                    flash("Stock insuficiente de " + data.get("nombre", product.title) + ". Disponible: " + str(stock) + " " + data.get("unidad", ""))
                    return redirect(url_for("deposito_operativo"))
                data["stock"] = str(new_stock)
                product.data = json.dumps(data, ensure_ascii=False)
                product.updated_at = paraguay_now()
                movement_data = {
                    "producto_id": product.id, "producto": data.get("nombre", product.title),
                    "marca": data.get("marca", ""), "tipo": "Entrada" if action == "entrada" else "Salida",
                    "cantidad": str(qty), "unidad": data.get("unidad", ""),
                    "fecha": date, "detalle": detail, "stock_resultante": str(new_stock),
                    "responsable": current_user().username
                }
                movement = Record(module=MOVEMENTS,
                    title=movement_data["tipo"] + " · " + movement_data["producto"],
                    data=json.dumps(movement_data, ensure_ascii=False), amount=0,
                    status=movement_data["tipo"], created_by=current_user().id)
                db.session.add(movement)
                db.session.flush()
                log_action("movimiento de Depósito Operativo", MOVEMENTS, movement.id,
                           movement_data["tipo"] + " " + str(qty) + " " + data.get("unidad", "") + " de " + data.get("nombre", product.title))
                db.session.commit()
                flash(movement_data["tipo"] + " registrada. Stock actual: " + str(new_stock) + " " + data.get("unidad", ""))
            else:
                flash("Acción no válida.")
        except (InvalidOperation, ValueError, TypeError):
            db.session.rollback()
            flash("Revisá los datos y la cantidad ingresada.")
        return redirect(url_for("deposito_operativo"))

    products = []
    for product in _products():
        data, stock = _stock_data(product)
        products.append({"id": product.id, "nombre": data.get("nombre", product.title),
                         "marca": data.get("marca", ""), "presentacion": data.get("presentacion", ""),
                         "unidad": data.get("unidad", "litro"), "stock": stock,
                         "stock_minimo": data.get("stock_minimo", "0")})
    movements = [(r, _data(r)) for r in Record.query.filter_by(module=MOVEMENTS).order_by(Record.created_at.desc()).limit(500).all()]
    return _page("Depósito Operativo", """
    <section class="card"><h2>Agregar producto</h2>
      <form method="post" class="grid">
        <input type="hidden" name="accion" value="producto">
        <div><label>Producto</label><input name="nombre" required maxlength="160" placeholder="Ej.: Aceite hidráulico"></div>
        <div><label>Marca</label><input name="marca" maxlength="120"></div>
        <div><label>Presentación</label><input name="presentacion" placeholder="Ej.: bidón de 20 litros"></div>
        <div><label>Unidad de control</label><select name="unidad"><option value="litro">Litro</option><option value="unidad">Unidad</option><option value="bidón">Bidón</option><option value="tambor">Tambor</option><option value="kg">Kg</option></select></div>
        <div><label>Stock mínimo</label><input name="stock_minimo" type="number" min="0" step="0.001" value="0"></div>
        <div style="align-self:end"><button>Agregar producto</button></div>
      </form>
    </section>
    <section class="card"><h2>Registrar entrada o salida</h2>
      <form method="post" class="grid">
        <div><label>Movimiento</label><select name="accion"><option value="entrada">Entrada</option><option value="salida">Salida / consumo</option></select></div>
        <div><label>Producto</label><select name="producto_id" required><option value="">Seleccionar producto</option>{% for p in products %}<option value="{{p.id}}">{{p.nombre}} · stock {{p.stock}} {{p.unidad}}</option>{% endfor %}</select></div>
        <div><label>Cantidad</label><input name="cantidad" type="number" min="0.001" step="0.001" required></div>
        <div><label>Fecha</label><input name="fecha" type="date" value="{{today}}" required></div>
        <div><label>Detalle / destino</label><input name="detalle" placeholder="Compra, camión, maquinaria o motivo"></div>
        <div style="align-self:end"><button>Guardar movimiento</button></div>
      </form>
    </section>
    <section class="card"><h2>Existencias de Depósito Operativo</h2><button type="button" onclick="window.print()">Imprimir inventario</button>
      <div style="overflow-x:auto"><table><tr><th>Producto</th><th>Marca</th><th>Presentación</th><th>Stock actual</th><th>Stock mínimo</th><th>Estado</th></tr>
      {% for p in products %}<tr><td>{{p.nombre}}</td><td>{{p.marca}}</td><td>{{p.presentacion}}</td><td><b>{{p.stock}} {{p.unidad}}</b></td><td>{{p.stock_minimo}} {{p.unidad}}</td><td>{% if p.stock <= p.stock_minimo|float %}<b>Stock bajo</b>{% else %}Disponible{% endif %}</td></tr>{% else %}<tr><td colspan="6">Todavía no hay productos registrados.</td></tr>{% endfor %}</table></div>
    </section>
    <section class="card"><h2>Historial de movimientos</h2><button type="button" onclick="window.print()">Imprimir historial</button>
      <div style="overflow-x:auto"><table><tr><th>Fecha</th><th>Fecha y hora de registro</th><th>Movimiento</th><th>Producto</th><th>Cantidad</th><th>Stock resultante</th><th>Detalle / destino</th><th>Responsable</th></tr>
      {% for r,d in movements %}<tr><td>{{d.get('fecha','')}}</td><td>{{local_time(r.created_at).strftime('%d/%m/%Y %H:%M')}}</td><td>{{d.get('tipo','')}}</td><td>{{d.get('producto','')}}</td><td>{{d.get('cantidad','')}} {{d.get('unidad','')}}</td><td>{{d.get('stock_resultante','')}}</td><td>{{d.get('detalle','')}}</td><td>{{d.get('responsable','')}}</td></tr>{% else %}<tr><td colspan="8">Todavía no hay movimientos.</td></tr>{% endfor %}</table></div>
    </section>
    """, products=products, movements=movements, today=paraguay_now().strftime("%Y-%m-%d"))

# Añadir el acceso dentro de la pantalla del rol Inventario sin tocar otras áreas.
_original_admin_section = app.view_functions.get("admin_section")
if _original_admin_section:
    def _admin_section_with_deposito(*args, **kwargs):
        response = _original_admin_section(*args, **kwargs)
        section = kwargs.get("section")
        if section is None and args:
            section = args[0]
        if section == "inventario" and isinstance(response, str):
            link = '<section class="card" style="margin:16px 0"><h2>Depósito Operativo</h2><p>Inventario independiente de aceites hidráulicos, fluidos de frenos, ATF y otros lubricantes.</p><a class="btn" href="/deposito-operativo">Abrir Depósito Operativo</a></section>'
            response = response.replace('<section class="area-grid">', link + '<section class="area-grid">', 1)
        return response
    app.view_functions["admin_section"] = _admin_section_with_deposito
