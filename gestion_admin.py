# Administracion de clientes y control ampliado de flota para Freddy Rojas.
import json
import sys
from decimal import Decimal, InvalidOperation
from flask import request, redirect, url_for, render_template_string, flash, abort
import app as core
from app import app, db, Record, CompanyAccount, current_user, login_required, log_action, paraguay_now, local_time

def _d(record):
    try:
        return json.loads(record.data or "{}")
    except Exception:
        return {}

def _rs(module):
    return Record.query.filter_by(module=module).order_by(Record.created_at.desc()).all()

def _save(module, title, data, amount=0, status="Registrado"):
    rec = Record(module=module, title=title, data=json.dumps(data, ensure_ascii=False),
                 amount=Decimal(str(amount or 0)), status=status, created_by=current_user().id)
    db.session.add(rec)
    db.session.flush()
    log_action("crear registro", module, rec.id, title)
    return rec

def _admin():
    if not current_user() or current_user().role != "admin":
        abort(403)

def _area_station():
    if not current_user() or not (current_user().role == "admin" or core.allowed("estacion")):
        abort(403)

def _page(title, body, **kwargs):
    return render_template_string(core.BASE + body + "</main><footer>Freddy Rojas · Gestión empresarial</footer></body></html>", title=title, **kwargs)

# Insertar los accesos en la navegación existente, sin tocar otros sistemas.
if "Administrar clientes" not in core.BASE:
    core.BASE = core.BASE.replace(
        '<a href="{{url_for(\'module_page\',module=\'materiales\')}}">＋ &nbsp; Agregar material</a>',
        '<a href="{{url_for(\'module_page\',module=\'materiales\')}}">＋ &nbsp; Agregar material</a><a href="{{url_for(\'admin_clientes\')}}">▣ &nbsp; Administrar clientes</a>'
    )
    core.BASE = core.BASE.replace(
        '<a href="{{url_for(\'admin_section\',section=\'estacion\')}}">⛽ &nbsp; Estación de servicio</a>',
        '<a href="{{url_for(\'admin_section\',section=\'estacion\')}}">⛽ &nbsp; Estación de servicio</a><a href="{{url_for(\'control_flota\')}}">🚚 &nbsp; Control de camiones y maquinarias</a>'
    )

# Los módulos existentes importaron BASE antes de esta ampliación; sincronizar la navegación en todos.
for _module_name in ("features", "pagos_ui", "pagos_save", "caja_tickets", "salidas_material", "materiales_report"):
    _loaded_module = sys.modules.get(_module_name)
    if _loaded_module is not None and hasattr(_loaded_module, "BASE"):
        _loaded_module.BASE = core.BASE

@app.route("/administrar-clientes", methods=["GET", "POST"])
@login_required
def admin_clientes():
    _admin()
    action = request.form.get("accion", "")
    if request.method == "POST":
        if action == "seleccionar":
            ids = request.form.getlist("proveedor_id")
            existing = {str(_d(r).get("proveedor_id")) for r in _rs("admin_clientes_seleccionados")}
            added = 0
            for value in ids:
                if not value.isdigit() or value in existing:
                    continue
                supplier = db.session.get(Record, int(value))
                if not supplier or supplier.module != "proveedores":
                    continue
                sd = _d(supplier)
                _save("admin_clientes_seleccionados", "Cliente administrado · " + sd.get("nombre", supplier.title),
                      {"proveedor_id": supplier.id, "nombre": sd.get("nombre", supplier.title), "codigo": sd.get("codigo", "")}, 0, "Activo")
                added += 1
            db.session.commit()
            flash("Se agregaron " + str(added) + " cliente(s) a Administración.")
            return redirect(url_for("admin_clientes"))
        if action == "deuda":
            try:
                selected_id = int(request.form.get("seleccion_id", ""))
                selected = db.session.get(Record, selected_id)
                if not selected or selected.module != "admin_clientes_seleccionados":
                    raise InvalidOperation()
                amount = Decimal(request.form.get("deuda", "").strip().replace(",", ".")).quantize(Decimal("0.01"))
                if amount < 0:
                    raise InvalidOperation()
                d = _d(selected)
                d["deuda_actual"] = str(amount)
                d["deuda_actualizada"] = paraguay_now().strftime("%Y-%m-%d %H:%M:%S")
                selected.data = json.dumps(d, ensure_ascii=False)
                selected.updated_at = paraguay_now()
                log_action("actualizar deuda de cliente", "admin_clientes_seleccionados", selected.id,
                           d.get("nombre", "") + "; deuda fijada en Gs. " + str(amount))
                db.session.commit()
                flash("Deuda actualizada para " + d.get("nombre", "el cliente") + ": Gs. " + str(amount))
            except (InvalidOperation, ValueError, TypeError):
                db.session.rollback()
                flash("Ingresá un monto válido de deuda, igual o mayor que cero.")
            return redirect(url_for("admin_clientes"))
        if action == "pagar":
            try:
                selected_id = int(request.form.get("seleccion_id", ""))
                selected = db.session.get(Record, selected_id)
                if not selected or selected.module != "admin_clientes_seleccionados":
                    raise InvalidOperation()
                d = _d(selected)
                debt = Decimal(str(d.get("deuda_actual", "0"))).quantize(Decimal("0.01"))
                amount = Decimal(request.form.get("importe", "").strip().replace(",", ".")).quantize(Decimal("0.01"))
                account_id = int(request.form.get("cuenta_id", ""))
                account = db.session.get(CompanyAccount, account_id)
                if not account or not account.active or amount <= 0 or amount > debt:
                    raise InvalidOperation()
                if amount > Decimal(str(account.balance or 0)):
                    flash("Saldo bancario insuficiente. No se registró el pago al cliente.")
                    return redirect(url_for("admin_clientes"))
                remaining = (debt - amount).quantize(Decimal("0.01"))
                date = request.form.get("fecha", "") or paraguay_now().strftime("%Y-%m-%d")
                method = request.form.get("medio", "Transferencia").strip()
                detail = request.form.get("detalle", "").strip()
                payment_data = {
                    "cliente": d.get("nombre", ""), "seleccion_id": selected.id,
                    "proveedor_id": d.get("proveedor_id"), "fecha": date,
                    "deuda_antes": str(debt), "importe": str(amount), "deuda_restante": str(remaining),
                    "medio": method, "cuenta_empresa": account.name, "cuenta_id": account.id,
                    "detalle": detail, "saldo_bancario_antes": str(account.balance)
                }
                payment = _save("pagos_cliente_admin", "Pago a cliente · " + d.get("nombre", ""), payment_data,
                                amount, "Pagado" if remaining == 0 else "Pago parcial")
                account.balance = (Decimal(str(account.balance or 0)) - amount).quantize(Decimal("0.01"))
                d["deuda_actual"] = str(remaining)
                d["deuda_actualizada"] = paraguay_now().strftime("%Y-%m-%d %H:%M:%S")
                selected.data = json.dumps(d, ensure_ascii=False)
                selected.updated_at = paraguay_now()
                report_data = {
                    "modulo_origen": "pagos_cliente_admin", "registro_id": payment.id,
                    "fecha": date, "beneficiario": d.get("nombre", ""), "cliente": d.get("nombre", ""),
                    "concepto": "Pago de deuda a cliente", "importe": str(amount), "medio": method,
                    "detalle": detail, "cuenta_empresa": account.name, "cuenta_id": account.id,
                    "saldo_bancario": str(account.balance), "deuda_restante": str(remaining)
                }
                report = Record(module="pagos_cuentas", title="Pago a cliente · " + d.get("nombre", ""),
                                data=json.dumps(report_data, ensure_ascii=False), amount=amount,
                                status="Pagado", company_account_id=account.id, created_by=current_user().id)
                db.session.add(report)
                db.session.flush()
                log_action("pagar deuda a cliente y descontar banco", "pagos_cliente_admin", payment.id,
                           d.get("nombre", "") + "; pago Gs. " + str(amount) + "; deuda restante Gs. " +
                           str(remaining) + "; saldo banco Gs. " + str(account.balance))
                log_action("registrar pago en informe de pagos", "pagos_cuentas", report.id, report.title)
                db.session.commit()
                flash("Pago registrado. Deuda restante: Gs. " + str(remaining) +
                      ". Saldo bancario actualizado: Gs. " + str(account.balance) + ".")
            except (InvalidOperation, ValueError, TypeError):
                db.session.rollback()
                flash("No se pudo registrar el pago. Verificá cliente, cuenta, deuda e importe.")
            return redirect(url_for("admin_clientes"))

    suppliers = [(r, _d(r)) for r in _rs("proveedores")]
    already = {str(_d(r).get("proveedor_id")) for r in _rs("admin_clientes_seleccionados")}
    selectable = [(r, d) for r, d in suppliers if str(r.id) not in already]
    selected = [(r, _d(r)) for r in _rs("admin_clientes_seleccionados")]
    accounts = CompanyAccount.query.filter_by(active=True).order_by(CompanyAccount.id.asc()).all()
    payments = _rs("pagos_cliente_admin")
    payments_by_id = {}
    for p in payments:
        pd = _d(p)
        payments_by_id.setdefault(str(pd.get("seleccion_id")), []).append((p, pd))
    kg_by_name = {}
    for module in ("tickets", "tickets_entrada", "pagos_diarios", "planillas", "ventas", "flota"):
        for r in _rs(module):
            x = _d(r)
            name = str(x.get("cliente") or x.get("persona") or x.get("proveedor") or x.get("nombre") or x.get("camion") or "").strip().casefold()
            kg = x.get("cantidad", x.get("kg", 0))
            if name:
                try:
                    kg_by_name[name] = kg_by_name.get(name, Decimal("0")) + Decimal(str(kg or 0))
                except (InvalidOperation, ValueError, TypeError):
                    pass
    return _page("Administrar clientes", """
    <section class="card"><h2>Agregar clientes registrados</h2>
      <p>Seleccioná uno o varios proveedores ya registrados para agregarlos a la lista de administración de deudas.</p>
      <form method="post"><input type="hidden" name="accion" value="seleccionar">
      <div style="overflow-x:auto"><table><tr><th>Seleccionar</th><th>Código</th><th>Cliente</th><th>Documento</th><th>Teléfono</th></tr>
      {% for r,d in selectable %}<tr><td><input type="checkbox" name="proveedor_id" value="{{r.id}}" style="width:auto"></td><td>{{d.get('codigo','')}}</td><td>{{d.get('nombre',r.title)}}</td><td>{{d.get('cedula','—')}}</td><td>{{d.get('telefono','—')}}</td></tr>{% else %}<tr><td colspan="5">No hay más clientes registrados para agregar.</td></tr>{% endfor %}</table></div>
      <p><button>Agregar seleccionados</button></p></form>
    </section>
    <section class="card"><h2>Clientes administrados y deudas</h2><div style="overflow-x:auto"><table>
      <tr><th>Cliente</th><th>Kg ingresados</th><th>Deuda actual (Gs.)</th><th>Actualizar deuda manual</th><th>Registrar pago</th></tr>
      {% for r,d in selected %}<tr><td><b>{{d.get('nombre',r.title)}}</b><br><span class="muted">{{d.get('codigo','')}}</span></td>
      <td>{{kg_by_name.get(d.get('nombre','').casefold(),0)}}</td><td><b>Gs. {{d.get('deuda_actual','0')}}</b></td>
      <td><form method="post" class="actions"><input type="hidden" name="accion" value="deuda"><input type="hidden" name="seleccion_id" value="{{r.id}}"><input name="deuda" type="number" min="0" step="0.01" value="{{d.get('deuda_actual','0')}}" required><button>Guardar deuda</button></form></td>
      <td><form method="post" class="grid" style="min-width:260px"><input type="hidden" name="accion" value="pagar"><input type="hidden" name="seleccion_id" value="{{r.id}}">
      <div><label>Importe a pagar (Gs.)</label><input name="importe" type="number" min="0.01" step="0.01" max="{{d.get('deuda_actual','0')}}" required></div>
      <div><label>Cuenta bancaria de la empresa</label><select name="cuenta_id" required>{% for a in accounts %}<option value="{{a.id}}">{{a.name or 'Cuenta central'}} · saldo Gs. {{a.balance}}</option>{% endfor %}</select></div>
      <div><label>Fecha</label><input name="fecha" type="date" value="{{today}}" required></div><div><label>Medio</label><select name="medio"><option>Transferencia</option><option>Efectivo</option><option>Cheque</option><option>Otro</option></select></div>
      <div><label>Detalle / comprobante</label><input name="detalle"></div><div style="align-self:end"><button {% if not accounts or (d.get('deuda_actual','0')|float)<=0 %}disabled{% endif %}>Pagar cliente</button></div></form></td></tr>
      {% else %}<tr><td colspan="5">Todavía no seleccionaste clientes para administrar.</td></tr>{% endfor %}
      </table></div></section>
    <section class="card"><h2>Historial de pagos a clientes</h2><div style="overflow-x:auto"><table><tr><th>Fecha y hora</th><th>Cliente</th><th>Deuda anterior</th><th>Importe pagado</th><th>Deuda restante</th><th>Cuenta</th><th>Medio</th><th>Saldo bancario actual registrado</th></tr>
      {% for p in payments %}{% set d=decode(p) %}<tr><td>{{local_time(p.created_at).strftime('%d/%m/%Y %H:%M:%S')}}</td><td>{{d.get('cliente','')}}</td><td>Gs. {{d.get('deuda_antes','')}}</td><td>Gs. {{p.amount}}</td><td>Gs. {{d.get('deuda_restante','')}}</td><td>{{d.get('cuenta_empresa','')}}</td><td>{{d.get('medio','')}}</td><td>Gs. {{d.get('saldo_bancario_antes','')}}</td></tr>{% else %}<tr><td colspan="8">Todavía no hay pagos registrados.</td></tr>{% endfor %}
      </table></div></section>
    """, selectable=selectable, selected=selected, accounts=accounts, payments=payments,
       today=paraguay_now().strftime("%Y-%m-%d"), decode=_d, kg_by_name=kg_by_name)

@app.route("/control-flota", methods=["GET", "POST"])
@login_required
def control_flota():
    _area_station()
    if request.method == "POST":
        action = request.form.get("accion", "")
        try:
            if action == "equipo":
                _admin()
                name = request.form.get("nombre", "").strip()
                kind = request.form.get("tipo", "Camión")
                plate = request.form.get("chapa", "").strip()
                reading = Decimal(request.form.get("lectura_actual", "0").replace(",", "."))
                interval = Decimal(request.form.get("intervalo", "15000").replace(",", "."))
                if not name or reading < 0 or interval <= 0 or kind not in ("Camión", "Maquinaria"):
                    raise InvalidOperation()
                if kind == "Camión" and not plate:
                    raise InvalidOperation()
                code = "EQ-" + str(len(_rs("flota_equipo")) + 1).zfill(4)
                data = {"codigo": code, "nombre": name, "chapa": plate, "tipo": kind,
                        "lectura_actual": str(reading), "intervalo": str(interval),
                        "proximo_mantenimiento": str(reading + interval),
                        "unidad": "km" if kind == "Camión" else "horas"}
                _save("flota_equipo", code + " · " + name, data, 0, "Activo")
                _save("lecturas_equipo", "Lectura inicial · " + name,
                      {"equipo": name, "lectura": str(reading), "fecha": paraguay_now().strftime("%Y-%m-%d"), "nota": "Lectura inicial de equipo"}, 0, "Lectura")
                db.session.commit()
                flash("Equipo registrado. Próximo mantenimiento: " + str(reading + interval) + (" km." if kind == "Camión" else " horas."))
            elif action == "viaje":
                name = request.form.get("equipo", "").strip()
                dest = request.form.get("destino", "").strip()
                kg = Decimal(request.form.get("kg", "0").replace(",", "."))
                fuel = Decimal(request.form.get("litros", "0").replace(",", ".") or "0")
                cost = Decimal(request.form.get("costo_combustible", "0").replace(",", ".") or "0")
                reading = Decimal(request.form.get("lectura", "0").replace(",", ".") or "0")
                if not name or not dest or kg < 0 or fuel < 0 or cost < 0 or reading < 0:
                    raise InvalidOperation()
                equipment = next((_d(r) for r in _rs("flota_equipo") if _d(r).get("nombre") == name), None)
                if not equipment or equipment.get("tipo") != "Camión":
                    raise InvalidOperation()
                data = {"equipo": name, "camion": name, "chapa": equipment.get("chapa", ""),
                        "fecha": request.form.get("fecha", "") or paraguay_now().strftime("%Y-%m-%d"),
                        "destino": dest, "kg": str(kg), "litros": str(fuel),
                        "costo_combustible": str(cost), "lectura": str(reading),
                        "observaciones": request.form.get("observaciones", "").strip()}
                _save("flota_viajes", "Viaje · " + name + " · " + dest, data, cost, "Registrado")
                if reading > 0:
                    _save("lecturas_equipo", "Lectura de viaje · " + name,
                          {"equipo": name, "lectura": str(reading), "fecha": data["fecha"], "nota": "Lectura registrada en viaje"}, 0, "Lectura")
                db.session.commit()
                flash("Viaje guardado en el historial del camión.")
            elif action == "mantenimiento":
                _area_station()
                name = request.form.get("equipo", "").strip()
                reading = Decimal(request.form.get("lectura", "0").replace(",", "."))
                cost = Decimal(request.form.get("costo", "0").replace(",", ".") or "0")
                interval = Decimal(request.form.get("intervalo", "0").replace(",", ".") or "0")
                work = request.form.get("detalle", "").strip()
                parts = request.form.get("repuestos", "").strip()
                if not name or reading < 0 or cost < 0 or interval <= 0 or not work:
                    raise InvalidOperation()
                equipment_record = next((r for r in _rs("flota_equipo") if _d(r).get("nombre") == name), None)
                if not equipment_record:
                    raise InvalidOperation()
                ed = _d(equipment_record)
                unit = "km" if ed.get("tipo") == "Camión" else "horas"
                next_reading = reading + interval
                data = {"equipo": name, "fecha": request.form.get("fecha", "") or paraguay_now().strftime("%Y-%m-%d"),
                        "lectura": str(reading), "intervalo": str(interval), "proximo_mantenimiento": str(next_reading),
                        "unidad": unit, "tipo": request.form.get("tipo_mantenimiento", "Preventivo"),
                        "detalle": work, "repuestos": parts, "costo": str(cost),
                        "responsable": request.form.get("responsable", "").strip()}
                _save("mantenimiento", "Mantenimiento · " + name, data, cost, "Mantenimiento registrado")
                ed.update({"lectura_actual": str(reading), "intervalo": str(interval), "proximo_mantenimiento": str(next_reading)})
                equipment_record.data = json.dumps(ed, ensure_ascii=False)
                equipment_record.updated_at = paraguay_now()
                _save("lecturas_equipo", "Lectura posterior a mantenimiento · " + name,
                      {"equipo": name, "lectura": str(reading), "fecha": data["fecha"], "nota": "Lectura registrada al realizar mantenimiento"}, 0, "Lectura")
                db.session.commit()
                flash("Mantenimiento guardado. Próximo mantenimiento: " + str(next_reading) + " " + unit + ".")
            else:
                raise InvalidOperation()
        except (InvalidOperation, ValueError, TypeError):
            db.session.rollback()
            flash("No se guardó el registro. Revisá los datos numéricos, el equipo y los campos obligatorios.")
        return redirect(url_for("control_flota"))

    equip = [(r, _d(r)) for r in _rs("flota_equipo")]
    trips = [(r, _d(r)) for r in _rs("flota_viajes")]
    maintenance = [(r, _d(r)) for r in _rs("mantenimiento")]
    readings = _rs("lecturas_equipo")
    latest = {}
    for rr in readings:
        rd = _d(rr)
        if rd.get("equipo") not in latest:
            latest[rd.get("equipo")] = rd
    summaries = []
    for er, ed in equip:
        name = ed.get("nombre", "")
        rd = latest.get(name, {})
        current = Decimal(str(rd.get("lectura", ed.get("lectura_actual", 0)) or 0))
        next_due = Decimal(str(ed.get("proximo_mantenimiento", current + Decimal(str(ed.get("intervalo", 0))))))
        summaries.append({"nombre": name, "chapa": ed.get("chapa", ""), "tipo": ed.get("tipo", ""),
                          "actual": current, "proximo": next_due, "unidad": ed.get("unidad", "km" if ed.get("tipo") == "Camión" else "horas"),
                          "estado": "VENCIDO" if current >= next_due else ("PRÓXIMO" if next_due-current <= Decimal(str(ed.get("intervalo", 0)))*Decimal("0.15") else "Al día")})
    return _page("Control de camiones y maquinarias", """
    <section class="card"><h2>Flota registrada</h2>{% if user.role=='admin' %}<form method="post" class="grid"><input type="hidden" name="accion" value="equipo">
      <div><label>Nombre / código</label><input name="nombre" required></div><div><label>Tipo</label><select name="tipo"><option>Camión</option><option>Maquinaria</option></select></div>
      <div><label>Chapa (obligatoria para camión)</label><input name="chapa"></div><div><label>Lectura actual (km u horas)</label><input name="lectura_actual" type="number" min="0" step="0.1" value="0" required></div>
      <div><label>Intervalo de mantenimiento (km u horas)</label><input name="intervalo" type="number" min="1" step="0.1" value="15000" required></div><div style="align-self:end"><button>Agregar equipo</button></div></form>{% endif %}
      <div style="overflow-x:auto"><table><tr><th>Equipo</th><th>Chapa</th><th>Tipo</th><th>Lectura actual</th><th>Próximo mantenimiento</th><th>Estado</th></tr>
      {% for e in summaries %}<tr><td>{{e.nombre}}</td><td>{{e.chapa or '—'}}</td><td>{{e.tipo}}</td><td>{{e.actual}} {{e.unidad}}</td><td>{{e.proximo}} {{e.unidad}}</td><td><b class="{{'danger' if e.estado=='VENCIDO' else ('ok' if e.estado=='Al día' else '')}}">{{e.estado}}</b></td></tr>{% else %}<tr><td colspan="6">Todavía no hay equipos registrados.</td></tr>{% endfor %}</table></div>
    </section>
    <section class="card"><h2>Registrar viaje de camión</h2><form method="post" class="grid"><input type="hidden" name="accion" value="viaje">
      <div><label>Camión</label><select name="equipo" required><option value="">Seleccionar</option>{% for r,d in equip %}{% if d.get('tipo')=='Camión' %}<option>{{d.get('nombre')}}</option>{% endif %}{% endfor %}</select></div>
      <div><label>Fecha</label><input name="fecha" type="date" value="{{today}}" required></div><div><label>Destino</label><input name="destino" required></div><div><label>Kilos traídos</label><input name="kg" type="number" min="0" step="0.001" required></div>
      <div><label>Lectura del odómetro (opcional)</label><input name="lectura" type="number" min="0" step="0.1"></div><div><label>Combustible utilizado (litros)</label><input name="litros" type="number" min="0" step="0.01" value="0"></div>
      <div><label>Costo del combustible (Gs., opcional)</label><input name="costo_combustible" type="number" min="0" step="1" value="0"></div><div><label>Observaciones</label><input name="observaciones"></div><div style="align-self:end"><button>Guardar viaje</button></div></form></section>
    <section class="card"><h2>Registrar mantenimiento</h2><form method="post" class="grid"><input type="hidden" name="accion" value="mantenimiento">
      <div><label>Camión / maquinaria</label><select name="equipo" required><option value="">Seleccionar</option>{% for r,d in equip %}<option>{{d.get('nombre')}}</option>{% endfor %}</select></div><div><label>Fecha</label><input name="fecha" type="date" value="{{today}}" required></div>
      <div><label>Lectura actual (km u horas)</label><input name="lectura" type="number" min="0" step="0.1" required></div><div><label>Intervalo hasta próximo mantenimiento</label><input name="intervalo" type="number" min="1" step="0.1" required></div>
      <div><label>Tipo</label><select name="tipo_mantenimiento"><option>Preventivo</option><option>Correctivo</option><option>Inspección</option></select></div><div><label>Trabajo realizado</label><input name="detalle" required></div>
      <div><label>Repuestos utilizados</label><input name="repuestos"></div><div><label>Costo (Gs., opcional)</label><input name="costo" type="number" min="0" step="1" value="0"></div><div><label>Responsable</label><input name="responsable"></div><div style="align-self:end"><button>Guardar mantenimiento</button></div></form></section>
    <section class="card"><h2>Historial de viajes</h2><div style="overflow-x:auto"><table><tr><th>Fecha y hora</th><th>Camión</th><th>Destino</th><th>Kg</th><th>Combustible (L)</th><th>Costo combustible</th><th>Odómetro</th></tr>
      {% for r,d in trips %}<tr><td>{{d.get('fecha')}} · {{local_time(r.created_at).strftime('%H:%M:%S')}}</td><td>{{d.get('equipo')}}</td><td>{{d.get('destino')}}</td><td>{{d.get('kg')}}</td><td>{{d.get('litros')}}</td><td>Gs. {{d.get('costo_combustible')}}</td><td>{{d.get('lectura')}}</td></tr>{% else %}<tr><td colspan="7">Todavía no hay viajes registrados.</td></tr>{% endfor %}
      </table></div></section>
    <section class="card"><h2>Historial de mantenimiento</h2><div style="overflow-x:auto"><table><tr><th>Fecha y hora</th><th>Equipo</th><th>Lectura</th><th>Trabajo</th><th>Repuestos</th><th>Costo</th><th>Próximo mantenimiento</th></tr>
      {% for r,d in maintenance %}<tr><td>{{d.get('fecha')}} · {{local_time(r.created_at).strftime('%H:%M:%S')}}</td><td>{{d.get('equipo')}}</td><td>{{d.get('lectura')}} {{d.get('unidad')}}</td><td>{{d.get('detalle')}}</td><td>{{d.get('repuestos')}}</td><td>Gs. {{d.get('costo','0')}}</td><td>{{d.get('proximo_mantenimiento')}} {{d.get('unidad')}}</td></tr>{% else %}<tr><td colspan="7">Todavía no hay mantenimientos registrados.</td></tr>{% endfor %}
      </table></div></section>
    """, equip=equip, summaries=summaries, trips=trips, maintenance=maintenance,
       today=paraguay_now().strftime("%Y-%m-%d"), decode=_d)
