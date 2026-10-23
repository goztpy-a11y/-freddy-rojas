# Funciones ampliadas de finanzas, proveedores y flota para El Toro S.A.
import json
from decimal import Decimal, InvalidOperation
from datetime import datetime
from flask import request, redirect, url_for, render_template_string, flash, abort
from app import app, db, Record, MODULES, current_user, allowed, login_required, admin_required, log_action, BASE

MODULES.update({
    "pagos_diarios": ("Pagos diarios y por ticket", "caja", []),
    "prestamos": ("Préstamos", "caja", []),
    "prestamos_pagos": ("Pagos de préstamos", "caja", []),
    "pagos_cuentas": ("Movimientos de pagos", "tesoreria", []),
    "cobros_cuentas": ("Cobros de cuentas por cobrar", "tesoreria", []),
    "proveedores": ("Proveedores y precios asignados", "caja", []),
    "planillas": ("Cuenta de proveedores", "caja", []),
    "fletes": ("Fletes", "caja", []),
    "flota": ("Camiones de la empresa y retiros", "estacion", []),
    "combustible_stock": ("Stock de combustible", "estacion", []),
    "combustible_camion": ("Cargas de combustible por camión", "estacion", []),
    "mantenimiento": ("Mantenimiento de camiones y maquinarias", "estacion", []),
    "gomeria_camiones": ("Gomería por camión", "gomeria", []),
    "caja_chica": ("Caja chica", "caja", []),
})

def _data(r):
    try: return json.loads(r.data or "{}")
    except Exception: return {}

def _rows(module):
    return Record.query.filter_by(module=module).order_by(Record.created_at.desc()).all()

def _save(module, title, data, amount=0, status="Registrado"):
    rec=Record(module=module,title=title,data=json.dumps(data,ensure_ascii=False),
               amount=Decimal(str(amount or 0)),status=status,created_by=current_user().id)
    db.session.add(rec); db.session.flush()
    log_action("crear registro",module,rec.id,title)
    db.session.commit()
    return rec

def _can_caja():
    if not (current_user().role=="admin" or allowed("caja")): abort(403)

def _can_area(area):
    if not (current_user().role=="admin" or allowed(area)): abort(403)

def _page(title, body, **kwargs):
    return render_template_string(BASE+body+"""</main><footer>Freddy Rojas · Gestión empresarial</footer></body></html>""",title=title,**kwargs)

@app.get("/pagos-diarios")
@login_required
def pagos_diarios():
    _can_caja()
    all_rows=_rows("pagos_diarios")
    q=request.args.get("q","").strip().casefold()
    month=request.args.get("mes",datetime.now().strftime("%Y-%m"))
    today=datetime.now().strftime("%Y-%m-%d")
    if q:
        all_rows=[r for r in all_rows if q in (r.title+" "+r.data+" "+str(r.amount)).casefold()]
    today_rows=[r for r in all_rows if _data(r).get("fecha",r.created_at.strftime("%Y-%m-%d"))==today]
    history=[r for r in all_rows if _data(r).get("fecha",r.created_at.strftime("%Y-%m-%d"))[:7]==month]
    total_today=sum((Decimal(str(r.amount or 0)) for r in today_rows),Decimal("0"))
    total_history=sum((Decimal(str(r.amount or 0)) for r in history),Decimal("0"))
    return _page("Pagos diarios", """
    <section class="card"><h2>Registrar pago diario</h2><form method="post" action="{{url_for('crear_pago_diario')}}" class="grid">
    <div><label>Número de ticket</label><input name="ticket" required></div><div><label>Número de comprobante de este pago</label><input name="comprobante" required></div>
    <div><label>Cliente / proveedor</label><input name="persona" required></div><div><label>Importe total del ticket/deuda (Gs.)</label><input name="total" type="number" min="0.01" step="0.01" required></div>
    <div><label>Importe que se paga ahora (Gs.)</label><input name="pago" type="number" min="0.01" step="0.01" required></div>
    <div><label>Fecha del pago</label><input name="fecha" type="date" value="{{today}}" required></div>
    <div><label>Medio de pago</label><select name="medio" required><option value="">Seleccionar</option><option>Efectivo</option><option>Transferencia</option><option>Cheque</option><option>Otro</option></select></div>
    <div><label>Cuenta / referencia</label><input name="cuenta"></div><div><label>Concepto y observaciones</label><input name="detalle"></div>
    <div style="align-self:end"><button>Guardar pago</button></div></form></section>
    <section class="card"><h2>Pagos de hoy · {{today}} · Total: Gs. {{total_today}}</h2><button type="button" onclick="window.print()">Imprimir pagos de hoy</button>
    <table><tr><th>Fecha</th><th>Ticket</th><th>Comprobante</th><th>Persona</th><th>Total deuda</th><th>Pagó ahora</th><th>Saldo tras pago</th><th>Medio</th><th>Detalle</th></tr>
    {% for r in today_rows %}{% set d=decode(r) %}<tr><td>{{d.get('fecha','')}}</td><td>{{d.get('ticket','')}}</td><td>{{d.get('comprobante','')}}</td><td>{{d.get('persona','')}}</td><td>{{d.get('total','')}}</td><td>{{r.amount}}</td><td>{{d.get('saldo','')}}</td><td>{{d.get('medio','')}}</td><td>{{d.get('detalle','')}} {{d.get('cuenta','')}}</td></tr>{% endfor %}</table></section>
    <section class="card"><h2>Historial mensual de pagos · Total: Gs. {{total_history}}</h2><form method="get" class="grid"><div><label>Mes del historial</label><input name="mes" type="month" value="{{month}}"></div><div><label>Buscar ticket, comprobante, persona o importe</label><input name="q" value="{{q}}"></div><div style="align-self:end"><button>Consultar</button><button type="button" onclick="window.print()">Imprimir historial</button></div></form>
    <table><tr><th>Fecha</th><th>Ticket</th><th>Comprobante</th><th>Persona</th><th>Total deuda</th><th>Pagó ahora</th><th>Saldo tras pago</th><th>Medio</th><th>Detalle</th></tr>
    {% for r in history %}{% set d=decode(r) %}<tr><td>{{d.get('fecha','')}}</td><td>{{d.get('ticket','')}}</td><td>{{d.get('comprobante','')}}</td><td>{{d.get('persona','')}}</td><td>{{d.get('total','')}}</td><td>{{r.amount}}</td><td>{{d.get('saldo','')}}</td><td>{{d.get('medio','')}}</td><td>{{d.get('detalle','')}} {{d.get('cuenta','')}}</td></tr>{% endfor %}</table></section>
    """,today_rows=today_rows,history=history,total_today=total_today,total_history=total_history,today=today,month=month,q=q,decode=_data)


@app.post("/pagos-diarios/crear")
@login_required
def crear_pago_diario():
    _can_caja()
    ticket=request.form.get("ticket","").strip()
    comp=request.form.get("comprobante","").strip()
    persona=request.form.get("persona","").strip()
    try:
        total=Decimal(request.form.get("total","").replace(",",".")); pago=Decimal(request.form.get("pago","").replace(",","."))
        if not ticket or not comp or not persona or total<=0 or pago<=0 or pago>total: raise InvalidOperation()
    except (InvalidOperation,ValueError):
        flash("Revisá el ticket y los importes: el pago debe ser mayor que cero y no superar la deuda total.")
        return redirect(url_for("pagos_diarios"))
    # El comprobante identifica cada pago; el mismo ticket admite pagos parciales sucesivos.
    if any(_data(r).get("comprobante","").casefold()==comp.casefold() for r in _rows("pagos_diarios")):
        flash("Comprobante repetido: no se guardó el pago. Usá un número de comprobante distinto.")
        return redirect(url_for("pagos_diarios"))
    previous=[r for r in _rows("pagos_diarios") if _data(r).get("ticket","").casefold()==ticket.casefold()]
    paid=sum((Decimal(str(r.amount or 0)) for r in previous),Decimal("0"))
    if previous:
        if any(_data(r).get("persona","").strip().casefold()!=persona.casefold() for r in previous):
            flash("Ese número de ticket ya pertenece a otro cliente/proveedor.")
            return redirect(url_for("pagos_diarios"))
        old_total=Decimal(str(_data(previous[0]).get("total",total)))
        if old_total!=total:
            flash("El total ingresado no coincide con el total ya registrado para ese ticket.")
            return redirect(url_for("pagos_diarios"))
        if paid+pago>total:
            flash("Ticket ya registrado y el pago excede el saldo pendiente. Saldo disponible: Gs. "+str(total-paid))
            return redirect(url_for("pagos_diarios"))
    saldo=total-paid-pago
    _save("pagos_diarios","Pago ticket "+ticket,{"ticket":ticket,"comprobante":comp,"persona":persona,
        "total":str(total),"fecha":request.form.get("fecha",""),"medio":request.form.get("medio",""),
        "cuenta":request.form.get("cuenta","").strip(),"detalle":request.form.get("detalle","").strip(),
        "pagado_acumulado":str(paid+pago),"saldo":str(saldo)},pago,"Pagado" if saldo==0 else "Pago parcial")
    flash("Pago registrado. Saldo pendiente: Gs. "+str(saldo))
    return redirect(url_for("pagos_diarios"))

@app.route("/prestamos",methods=["GET","POST"])
@login_required
def prestamos():
    _can_caja()
    if request.method=="POST":
        if request.form.get("accion")=="pago":
            try:
                loan_id=int(request.form.get("prestamo_id","")); loan=db.session.get(Record,loan_id)
                amount=Decimal(request.form.get("importe","").replace(",",".")); d=_data(loan) if loan else {}
                if not loan or loan.module!="prestamos" or amount<=0: raise InvalidOperation()
                paid=sum((Decimal(str(_data(x).get("importe",0))) for x in _rows("prestamos_pagos") if str(_data(x).get("prestamo_id"))==str(loan_id)),Decimal("0"))
                balance=Decimal(str(d.get("monto",0)))-paid
                if amount>balance: raise InvalidOperation()
                _save("prestamos_pagos","Pago préstamo "+str(loan_id),{"prestamo_id":loan_id,"cliente":d.get("cliente"),"entidad":d.get("entidad"),"fecha":request.form.get("fecha",""),"importe":str(amount),"medio":request.form.get("medio",""),"cuota":request.form.get("cuota",""),"observaciones":request.form.get("observaciones","")},amount,"Pagado")
                flash("Pago del préstamo registrado.")
            except (ValueError,InvalidOperation):
                flash("No se pudo registrar el pago: verificá el préstamo y el saldo.")
            return redirect(url_for("prestamos"))
        try:
            cliente=request.form.get("cliente","").strip(); entidad=request.form.get("entidad","").strip()
            monto=Decimal(request.form.get("monto","").replace(",",".")); plazo=int(request.form.get("plazo","12"))
            if not cliente or not entidad or monto<=0 or plazo<1 or plazo>12: raise InvalidOperation()
            _save("prestamos","Préstamo · "+cliente,{"cliente":cliente,"entidad":entidad,"fecha":request.form.get("fecha",""),"monto":str(monto),"plazo_meses":plazo,"modalidad":request.form.get("modalidad","Efectivo"),"vencimiento":request.form.get("vencimiento",""),"observaciones":request.form.get("observaciones","")},monto,"Pendiente")
            flash("Préstamo registrado.")
        except (ValueError,InvalidOperation):
            flash("Revisá los datos del préstamo; el plazo permitido es de 1 a 12 meses.")
        return redirect(url_for("prestamos"))
    loans=_rows("prestamos"); payments=_rows("prestamos_pagos"); summaries=[]
    for r in loans:
        d=_data(r); paid=sum((Decimal(str(_data(p).get("importe",0))) for p in payments if str(_data(p).get("prestamo_id"))==str(r.id)),Decimal("0"))
        total=Decimal(str(d.get("monto",0))); bal=total-paid
        summaries.append((r,d,paid,bal))
    return _page("Préstamos", """
    <section class="card"><h2>Registrar préstamo</h2><form method="post" class="grid">
    <div><label>Entidad / proveedor</label><input name="entidad" required></div><div><label>Cliente</label><input name="cliente" required></div>
    <div><label>Fecha</label><input name="fecha" type="date" value="{{today}}" required></div><div><label>Monto (Gs.)</label><input name="monto" type="number" min="0.01" step="0.01" required></div>
    <div><label>Plazo (máximo 12 meses)</label><input name="plazo" type="number" min="1" max="12" value="12" required></div>
    <div><label>Modalidad de pago</label><select name="modalidad"><option>Efectivo</option><option>Automático</option></select></div>
    <div><label>Próximo vencimiento</label><input name="vencimiento" type="date"></div><div><label>Observaciones</label><input name="observaciones"></div><div style="align-self:end"><button>Guardar préstamo</button></div></form></section>
    <section class="card"><h2>Préstamos y saldos</h2><button onclick="window.print()" type="button">Imprimir</button><table><tr><th>Entidad / cliente</th><th>Fecha</th><th>Monto</th><th>Pagado</th><th>Saldo</th><th>Plazo</th><th>Estado</th><th>Registrar pago</th></tr>
    {% for r,d,paid,balance in summaries %}<tr><td>{{d.get('entidad')}} / {{d.get('cliente')}}</td><td>{{d.get('fecha')}}</td><td>{{d.get('monto')}}</td><td>{{paid}}</td><td>{{balance}}</td><td>{{d.get('plazo_meses')}} meses</td><td>{{'Pagado' if balance==0 else ('Vencido' if d.get('vencimiento') and d.get('vencimiento')<today else 'Pendiente')}}</td><td>{% if balance>0 %}<form method="post"><input type="hidden" name="accion" value="pago"><input type="hidden" name="prestamo_id" value="{{r.id}}"><input name="importe" type="number" min="0.01" max="{{balance}}" step="0.01" placeholder="Importe" required><input name="fecha" type="date" value="{{today}}" required><select name="medio"><option>Efectivo</option><option>Transferencia</option><option>Automático</option><option>Cheque</option></select><input name="cuota" placeholder="N.º cuota"><input name="observaciones" placeholder="Detalle"><button>Registrar pago</button></form>{% endif %}</td></tr>{% endfor %}</table></section>
    <section class="card"><h2>Historial de pagos de préstamos</h2><table><tr><th>Fecha</th><th>Préstamo</th><th>Cliente</th><th>Importe</th><th>Medio</th></tr>{% for p in payments %}{% set d=decode(p) %}<tr><td>{{d.get('fecha')}}</td><td>{{d.get('entidad','')}} #{{d.get('prestamo_id')}}</td><td>{{d.get('cliente')}}</td><td>{{p.amount}}</td><td>{{d.get('medio')}}</td></tr>{% endfor %}</table></section>
    """,summaries=summaries,payments=payments,today=datetime.now().strftime("%Y-%m-%d"),decode=_data)

@app.route("/proveedores",methods=["GET","POST"])
@login_required
def proveedores():
    _can_caja()
    from app import Material
    mats=Material.query.order_by(Material.name).all()
    if request.method=="POST":
        nombre=request.form.get("nombre","").strip()
        if not nombre:
            flash("Ingresá el nombre del proveedor."); return redirect(url_for("proveedores"))
        existing=[_data(r) for r in _rows("proveedores")]
        if any(d.get("nombre","").casefold()==nombre.casefold() for d in existing):
            flash("Ese proveedor ya está registrado."); return redirect(url_for("proveedores"))
        code="PROV-"+str(len(existing)+1).zfill(5)
        prices={}
        valid_ids={str(m.id) for m in mats}
        for key,val in request.form.items():
            if key.startswith("precio_") and val.strip():
                mid=key[7:]
                if mid not in valid_ids:
                    flash("Se recibió un material no válido."); return redirect(url_for("proveedores"))
                try:
                    price=Decimal(val.replace(",","."))
                    if price<0: raise InvalidOperation()
                    prices[mid]=str(price)
                except (InvalidOperation,ValueError):
                    flash("Hay un precio inválido."); return redirect(url_for("proveedores"))
        _save("proveedores",code+" · "+nombre,{"codigo":code,"nombre":nombre,"cedula":request.form.get("cedula","").strip(),"telefono":request.form.get("telefono","").strip(),"direccion":request.form.get("direccion","").strip(),"precios_materiales":prices},0,"Activo")
        flash("Proveedor registrado con código "+code+" y precios guardados.")
        return redirect(url_for("proveedores"))
    return _page("Proveedores y precios", """
    <section class="card"><h2>Registrar proveedor y precios por material</h2>
    <form method="post" class="grid">
    <div><label>Nombre / razón social</label><input name="nombre" required></div>
    <div><label>RUC / cédula (opcional)</label><input name="cedula"></div>
    <div><label>Teléfono</label><input name="telefono"></div>
    <div><label>Dirección</label><input name="direccion"></div>
    <div style="grid-column:1/-1"><h3>Precios de este proveedor por material</h3><p>Ingresá el precio que este proveedor paga por cada material. Cada proveedor conserva sus propios precios; podés dejar vacío el material que no ofrece.</p>
    <div style="overflow-x:auto"><table><tr><th>Material</th><th>Precio para este proveedor (Gs.)</th></tr>
    {% for m in mats %}<tr><td>{{m.name}}</td><td><input aria-label="Precio de {{m.name}}" name="precio_{{m.id}}" type="number" min="0" step="0.01" placeholder="Ingresar precio" style="max-width:260px"></td></tr>{% else %}<tr><td colspan="2">Todavía no hay materiales. Registrá primero los materiales.</td></tr>{% endfor %}
    </table></div></div>
    <div style="align-self:end"><button class="btn">Guardar proveedor y precios</button></div>
    </form></section>
    <section class="card"><p>Para consultar el listado completo, ingresá en <a href="{{url_for('listado_proveedores')}}">Proveedores</a>.</p></section>
    """,mats=mats)


@app.get("/listado-proveedores")
@login_required
def listado_proveedores():
    _can_caja()
    items=[(r,_data(r)) for r in _rows("proveedores")]
    from app import Material
    mats=Material.query.order_by(Material.name).all()
    last={d.get("nombre"):max([x.created_at.strftime("%d/%m/%Y") for x in _rows("tickets")+_rows("pagos_diarios")+_rows("planillas") if d.get("nombre","").casefold() in (x.title+" "+x.data).casefold()] or ["Sin movimientos"]) for r,d in items}
    return _page("Proveedores", """
    <section class="card"><h2>Listado de proveedores</h2><button class="btn" type="button" onclick="window.print()">Imprimir listado</button>
    <div style="overflow-x:auto"><table><tr><th>Código</th><th>Proveedor</th><th>RUC / cédula</th><th>Teléfono</th><th>Dirección</th><th>Última actividad</th><th>Precios por material</th><th>Movimiento mensual</th><th>Editar</th></tr>
    {% for r,d in items %}<tr><td>{{d.get('codigo')}}</td><td>{{d.get('nombre')}}</td><td>{{d.get('cedula') or '—'}}</td><td>{{d.get('telefono') or '—'}}</td><td>{{d.get('direccion') or '—'}}</td><td>{{last.get(d.get('nombre'),'Sin movimientos')}}</td>
    <td>{% for mid,price in d.get('precios_materiales',{}).items() %}{% for m in mats %}{% if mid==m.id|string %}{{m.name}}: {{price}}<br>{% endif %}{% endfor %}{% endfor %}{% if not d.get('precios_materiales') %}—{% endif %}</td>
    <td><a class="btn" href="{{url_for('movimiento_proveedor',nombre=d.get('nombre'))}}">Ver movimientos</a></td>
    <td>{% if user.role=='admin' %}<a class="btn" href="{{url_for('editar_proveedor',rid=r.id)}}">Editar</a>{% else %}—{% endif %}</td></tr>{% else %}<tr><td colspan="9">Todavía no hay proveedores registrados.</td></tr>{% endfor %}</table></div></section>
    """,items=items,mats=mats,last=last)


@app.route("/proveedores/<int:rid>/editar",methods=["GET","POST"])
@login_required
def editar_proveedor(rid):
    if current_user().role!="admin": abort(403)
    rec=db.get_or_404(Record,rid)
    if rec.module!="proveedores": abort(404)
    d=_data(rec)
    from app import Material
    mats=Material.query.order_by(Material.name).all()
    if request.method=="POST":
        nombre=request.form.get("nombre","").strip()
        if not nombre:
            flash("El nombre del proveedor es obligatorio.")
            return redirect(url_for("editar_proveedor",rid=rid))
        prices={}
        for key,val in request.form.items():
            if key.startswith("precio_") and val.strip():
                try:
                    amount=Decimal(val.replace(",","."))
                    if amount<0: raise InvalidOperation()
                    prices[key[7:]]=str(amount)
                except (InvalidOperation,ValueError):
                    flash("Hay un precio no válido.")
                    return redirect(url_for("editar_proveedor",rid=rid))
        d.update({"nombre":nombre,"cedula":request.form.get("cedula","").strip(),"telefono":request.form.get("telefono","").strip(),"direccion":request.form.get("direccion","").strip(),"precios_materiales":prices})
        rec.title=str(d.get("codigo",""))+" · "+nombre
        rec.data=json.dumps(d,ensure_ascii=False); rec.updated_at=datetime.utcnow()
        log_action("editar proveedor y precios","proveedores",rec.id,nombre)
        db.session.commit()
        flash("Proveedor y precios actualizados.")
        return redirect(url_for("proveedores"))
    return _page("Editar proveedor", """
    <section class="card"><h2>Editar proveedor {{d.get('codigo')}}</h2><form method="post" class="grid">
    <div><label>Nombre / razón social</label><input name="nombre" value="{{d.get('nombre','')}}" required></div><div><label>Cédula (opcional)</label><input name="cedula" value="{{d.get('cedula','')}}"></div><div><label>Teléfono</label><input name="telefono" value="{{d.get('telefono','')}}"></div><div><label>Dirección</label><input name="direccion" value="{{d.get('direccion','')}}"></div>
    <div style="grid-column:1/-1"><h3>Precios de este proveedor por material</h3><div style="overflow-x:auto"><table><tr><th>Material</th><th>Precio para este proveedor (Gs.)</th></tr>
    {% for m in mats %}<tr><td>{{m.name}}</td><td><input aria-label="Precio de {{m.name}}" name="precio_{{m.id}}" type="number" min="0" step="0.01" value="{{d.get('precios_materiales',{}).get(m.id|string,'')}}" style="max-width:260px"></td></tr>{% else %}<tr><td colspan="2">Todavía no hay materiales registrados.</td></tr>{% endfor %}
    </table></div></div>
    <div style="align-self:end"><button>Guardar cambios</button> <a class="btn" href="{{url_for('proveedores')}}">Cancelar</a></div></form></section>
    """,d=d,mats=mats)

@app.get("/proveedores/movimiento/<path:nombre>")
@login_required
def movimiento_proveedor(nombre):
    _can_caja()
    rows=[r for r in _rows("tickets")+_rows("pagos_diarios")+_rows("planillas") if nombre.casefold() in (r.title+" "+r.data).casefold()]
    month=request.args.get("mes",datetime.now().strftime("%Y-%m"))
    rows=[r for r in rows if r.created_at.strftime("%Y-%m")==month]
    return _page("Movimiento proveedor", """
    <section class="card"><h2>Movimiento de {{nombre}}</h2><form class="actions"><label>Mes</label><input type="month" name="mes" value="{{month}}"><button>Consultar</button><button type="button" onclick="window.print()">Imprimir corte</button></form>
    <table><tr><th>Fecha</th><th>Sector</th><th>Operación</th><th>Detalle</th><th>Monto</th></tr>{% for r in rows %}<tr><td>{{r.created_at.strftime('%d/%m/%Y')}}</td><td>{{r.module}}</td><td>{{r.title}}</td><td>{{r.data}}</td><td>{{r.amount}}</td></tr>{% endfor %}</table></section>
    """,nombre=nombre,month=month,rows=rows)

@app.route("/planillas",methods=["GET","POST"])
@login_required
def planillas():
    _can_caja()
    if request.method=="POST":
        d={k:request.form.get(k,"").strip() for k in ["cliente","fecha","material_id","kg","monto_deuda","diferencia","pago","medio","flete","salida","detalle"]}
        try:
            kg=Decimal(d["kg"] or "0"); debt=Decimal(d["monto_deuda"] or "0"); diff=Decimal(d["diferencia"] or "0"); pay=Decimal(d["pago"] or "0"); freight=Decimal(d["flete"] or "0")
            if not d["cliente"] or min(kg,debt,diff,pay,freight)<0: raise InvalidOperation()
            material=db.session.get(__import__("app").Material,int(d["material_id"])) if d["material_id"] else None
            price=Decimal("0")
            if material:
                vendor=next((_data(v) for v in _rows("proveedores") if _data(v).get("nombre","").casefold()==d["cliente"].casefold()),{})
                assigned=vendor.get("precios_materiales",{}).get(str(material.id))
                price=Decimal(str(assigned)) if assigned not in (None,"") else (material.wholesale_price if material.wholesale_price is not None else material.price)
            goods=(kg*price).quantize(Decimal("0.01"))
            previous=[_data(r) for r in _rows("planillas") if _data(r).get("cliente","").casefold()==d["cliente"].casefold()]
            previous_balance=Decimal(str(previous[0].get("saldo_final",previous[0].get("monto_deuda",0)))) if previous else debt
            balance=previous_balance+goods+diff+freight-pay
            if balance<0: raise InvalidOperation()
            d.update({"kg":str(kg),"monto_deuda":str(previous_balance),"precio_unitario":str(price),"monto_mercaderia":str(goods),"diferencia":str(diff),"pago":str(pay),"flete":str(freight),"saldo_final":str(balance)})
            _save("planillas",d["cliente"]+" · planilla",d,pay,"Pagado" if balance==0 else ("Pago parcial" if pay else "Registrado"))
            flash("Planilla guardada. Mercadería: Gs. "+str(goods)+". Saldo actualizado: Gs. "+str(balance))
        except (InvalidOperation,ValueError):
            flash("Revisá el cliente, material y valores numéricos; el pago no puede superar el saldo.")
        return redirect(url_for("planillas"))
    rows=_rows("planillas")
    from app import Material
    materials=Material.query.order_by(Material.name).all()
    vendors=[_data(r).get("nombre") for r in _rows("proveedores")]
    return _page("Cuenta de proveedores", """
    <section class="card"><h2>Cuenta de proveedores · diferencias, mercadería, pagos y salidas</h2><form method="post" class="grid">
    <div><label>Cliente / proveedor</label><input name="cliente" list="proveedores-lista" required><datalist id="proveedores-lista">{% for v in vendors %}<option value="{{v}}">{% endfor %}</datalist></div><div><label>Fecha</label><input name="fecha" type="date" value="{{today}}" required></div>
    <div><label>Material</label><select name="material_id"><option value="">Sin material / ajuste manual</option>{% for m in materials %}<option value="{{m.id}}">{{m.name}}</option>{% endfor %}</select></div><div><label>Kilogramos recibidos</label><input name="kg" type="number" min="0" step="0.001" value="0"></div><div><label>Deuda inicial si no hay historial (Gs.)</label><input name="monto_deuda" type="number" min="0" step="0.01" value="0"></div>
    <div><label>Diferencia de este movimiento (Gs.)</label><input name="diferencia" type="number" min="0" step="0.01" value="0"></div><div><label>Pago parcial (Gs.)</label><input name="pago" type="number" min="0" step="0.01" value="0"></div>
    <div><label>Medio de pago</label><select name="medio"><option>Efectivo</option><option>Transferencia</option><option>Cheque</option><option>Otro</option></select></div><div><label>Flete (Gs.)</label><input name="flete" type="number" min="0" step="0.01" value="0"></div>
    <div><label>Salida / retiro</label><input name="salida" placeholder="Detalle de salida"></div><div><label>Observaciones</label><input name="detalle"></div><div style="align-self:end"><button>Guardar planilla</button></div></form></section>
    <section class="card"><h2>Historial de planillas</h2><button type="button" onclick="window.print()">Imprimir</button><table><tr><th>Fecha</th><th>Cliente</th><th>Material</th><th>Kg</th><th>Precio unitario</th><th>Mercadería</th><th>Saldo anterior</th><th>Diferencia</th><th>Pago</th><th>Flete</th><th>Saldo actualizado</th><th>Salida</th></tr>{% for r in rows %}{% set d=decode(r) %}<tr><td>{{d.get('fecha')}}</td><td>{{d.get('cliente')}}</td><td>{% for m in materials %}{% if m.id|string==d.get('material_id') %}{{m.name}}{% endif %}{% endfor %}</td><td>{{d.get('kg')}}</td><td>{{d.get('precio_unitario')}}</td><td>{{d.get('monto_mercaderia')}}</td><td>{{d.get('monto_deuda')}}</td><td>{{d.get('diferencia')}}</td><td>{{d.get('pago')}}</td><td>{{d.get('flete')}}</td><td><b>{{d.get('saldo_final')}}</b></td><td>{{d.get('salida')}}</td></tr>{% endfor %}</table></section>
    """,rows=rows,materials=materials,vendors=vendors,today=datetime.now().strftime("%Y-%m-%d"),decode=_data)

@app.route("/flota",methods=["GET","POST"])
@login_required
def flota():
    _can_area("estacion")
    if request.method=="POST":
        action=request.form.get("accion","movimiento")
        try:
            if action=="equipo":
                if current_user().role!="admin": abort(403)
                name=request.form.get("camion","").strip(); interval=Decimal(request.form.get("intervalo","15000").replace(",",".")); daily=Decimal(request.form.get("diario","0").replace(",","."))
                if not name or interval<=0 or daily<0: raise InvalidOperation()
                code="EQ-"+str(len(_rows("flota_equipo"))+1).zfill(4)
                _save("flota_equipo",code+" · "+name,{"codigo":code,"nombre":name,"tipo":request.form.get("tipo","Camión"),"intervalo":str(interval),"diario":str(daily),"unidad":"km" if request.form.get("tipo")=="Camión" else "horas"},0,"Activo")
                flash("Equipo registrado: "+code)
            else:
                name=request.form.get("camion","").strip(); kg=Decimal(request.form.get("kg","0").replace(",","."))
                if not name or kg<0: raise InvalidOperation()
                _save("flota",name+" · retiro",{"camion":name,"fecha":request.form.get("fecha",""),"kg":str(kg),"material":request.form.get("material","").strip(),"observaciones":request.form.get("observaciones","").strip()},0,"Registrado")
                flash("Retiro del camión registrado.")
        except (InvalidOperation,ValueError):
            flash("Revisá el nombre y los valores numéricos.")
        return redirect(url_for("flota"))
    equip=[(r,_data(r)) for r in _rows("flota_equipo")]
    moves=[(r,_data(r)) for r in _rows("flota")]
    sales=[(r,_data(r)) for r in _rows("ventas")]
    fuel=[(r,_data(r)) for r in (_rows("combustible_camion")+_rows("combustible"))]
    truck_summaries=[]
    for er,ed in equip:
        if ed.get("tipo")=="Camión":
            truck_moves=[md for mr,md in moves if md.get("camion")==ed.get("nombre")]
            truck_sales=[sd for sr,sd in sales if sd.get("camion")==ed.get("nombre")]
            truck_fuel=[fd for fr,fd in fuel if fd.get("camion")==ed.get("nombre")]
            truck_tires=[_data(gr) for gr in (_rows("gomeria_camiones")+_rows("gomeria")) if _data(gr).get("camion")==ed.get("nombre")]
            truck_summaries.append({"nombre":ed.get("nombre"),
                "kg_entregados":sum((Decimal(str(sd.get("cantidad",0))) for sd in truck_sales),Decimal("0")),
                "kg_retiros":sum((Decimal(str(md.get("kg",0))) for md in truck_moves),Decimal("0")),
                "litros":sum((Decimal(str(fd.get("litros",0))) for fd in truck_fuel),Decimal("0")),
                "gomeria":sum((Decimal(str(td.get("costo",0))) for td in truck_tires),Decimal("0")),
                "count":len(truck_moves)+len(truck_sales)})
    return _page("Flota", """
    {% if user.role=='admin' %}<section class="card"><h2>Agregar camión o maquinaria</h2><form method="post" class="grid"><input type="hidden" name="accion" value="equipo">
    <div><label>Nombre / chapa / código</label><input name="camion" required></div><div><label>Tipo</label><select name="tipo"><option>Camión</option><option>Maquinaria</option></select></div>
    <div><label>Intervalo mantenimiento (km u horas)</label><input id="intervalo-equipo" name="intervalo" type="number" min="1" value="15000" required></div><div><label>Uso estimado diario (km u horas)</label><input id="diario-equipo" name="diario" type="number" min="0" step="0.1" value="0" required></div><div style="align-self:end"><button>Guardar equipo</button></div></form><script>const tipoEquipo=document.querySelector('select[name="tipo"]');tipoEquipo.addEventListener('change',()=>{document.getElementById('intervalo-equipo').value=tipoEquipo.value==='Camión'?15000:325;document.getElementById('diario-equipo').value=tipoEquipo.value==='Camión'?0:(tipoEquipo.value==='Maquinaria'?16:0);});</script></section>{% endif %}
    <section class="card"><h2>Registrar retiro de mercadería</h2><form method="post" class="grid"><input type="hidden" name="accion" value="movimiento">
    <div><label>Camión</label><select name="camion" required><option value="">Seleccionar</option>{% for r,d in equip %}{% if d.get('tipo')=='Camión' %}<option>{{d.get('nombre')}}</option>{% endif %}{% endfor %}</select></div>
    <div><label>Fecha</label><input type="date" name="fecha" value="{{today}}" required></div><div><label>Kilogramos traídos</label><input type="number" name="kg" min="0" step="0.001" required></div><div><label>Material / carga</label><input name="material"></div><div><label>Observaciones</label><input name="observaciones"></div><div style="align-self:end"><button>Registrar retiro</button></div></form></section>
    <section class="card"><h2>Resumen por camión</h2><button type="button" onclick="window.print()">Imprimir</button><table><tr><th>Camión</th><th>Kg entregados en ventas</th><th>Kg de retiros registrados</th><th>Combustible cargado (L)</th><th>Gomería (Gs.)</th><th>Registros</th></tr>
    {% for s in truck_summaries %}<tr><td>{{s.nombre}}</td><td>{{s.kg_entregados}}</td><td>{{s.kg_retiros}}</td><td>{{s.litros}}</td><td>{{s.gomeria}}</td><td>{{s.count}}</td></tr>{% endfor %}</table></section>
    """,equip=equip,moves=moves,fuel=fuel,truck_summaries=truck_summaries,today=datetime.now().strftime("%Y-%m-%d"))

@app.route("/combustible-stock",methods=["GET","POST"])
@login_required
def combustible_stock():
    _can_area("estacion")
    if request.method=="POST":
        if current_user().role!="admin": abort(403)
        try:
            litros=Decimal(request.form.get("litros","").replace(",",".")); ifnote=request.form.get("detalle","").strip()
            if litros<=0: raise InvalidOperation()
            _save("combustible_stock","Entrada de combustible",{"fecha":request.form.get("fecha",""),"litros":str(litros),"detalle":ifnote},litros,"Entrada")
            flash("Stock de combustible actualizado.")
        except (InvalidOperation,ValueError):
            flash("Ingresá litros válidos mayores que cero.")
        return redirect(url_for("combustible_stock"))
    entries=_rows("combustible_stock"); charges=_rows("combustible_camion"); legacy=_rows("combustible")
    stock=sum((Decimal(str(_data(r).get("litros",0))) for r in entries),Decimal("0"))-sum((Decimal(str(_data(r).get("litros",0))) for r in charges+legacy),Decimal("0"))
    charges=charges+legacy
    return _page("Stock combustible", """
    {% if user.role=='admin' %}<section class="card"><h2>Cargar stock de combustible</h2><form method="post" class="grid"><div><label>Litros ingresados</label><input name="litros" type="number" min="0.01" step="0.01" required></div><div><label>Fecha</label><input name="fecha" type="date" value="{{today}}" required></div><div><label>Detalle / comprobante</label><input name="detalle"></div><div style="align-self:end"><button>Agregar al stock</button></div></form></section>{% endif %}
    <section class="card"><h2>Stock disponible: {{stock}} litros</h2><form method="post" action="{{url_for('cargar_combustible')}}" class="grid">
    <div><label>Camión</label><select name="camion" required><option value="">Seleccionar</option>{% for r in equip %}{% set d=decode(r) %}{% if d.get('tipo')=='Camión' %}<option>{{d.get('nombre')}}</option>{% endif %}{% endfor %}</select></div>
    <div><label>Litros cargados</label><input name="litros" type="number" min="0.01" step="0.01" required></div><div><label>Fecha</label><input name="fecha" type="date" value="{{today}}" required></div><div><label>Responsable</label><input name="responsable"></div><div><label>Observaciones</label><input name="detalle"></div><div style="align-self:end"><button>Cargar combustible</button></div></form></section>
    <section class="card"><h2>Historial de stock y cargas</h2><table><tr><th>Fecha</th><th>Tipo</th><th>Detalle</th><th>Litros</th></tr>{% for r in entries %}{% set d=decode(r) %}<tr><td>{{d.get('fecha')}}</td><td>Entrada</td><td>{{d.get('detalle')}}</td><td>+{{d.get('litros')}}</td></tr>{% endfor %}{% for r in charges %}{% set d=decode(r) %}<tr><td>{{d.get('fecha')}}</td><td>Carga · {{d.get('camion')}}</td><td>{{d.get('responsable')}} {{d.get('detalle')}}</td><td>-{{d.get('litros')}}</td></tr>{% endfor %}</table></section>
    """,stock=stock,entries=entries,charges=charges,equip=_rows("flota_equipo"),today=datetime.now().strftime("%Y-%m-%d"),decode=_data)

@app.post("/combustible-stock/cargar")
@login_required
def cargar_combustible():
    _can_area("estacion")
    try:
        litros=Decimal(request.form.get("litros","").replace(",",".")); entries=_rows("combustible_stock"); charges=_rows("combustible_camion")+_rows("combustible")
        stock=sum((Decimal(str(_data(r).get("litros",0))) for r in entries),Decimal("0"))-sum((Decimal(str(_data(r).get("litros",0))) for r in charges),Decimal("0"))
        if litros<=0 or litros>stock: raise InvalidOperation()
        camion=request.form.get("camion","").strip()
        if not camion: raise InvalidOperation()
        _save("combustible_camion","Carga combustible · "+camion,{"camion":camion,"litros":str(litros),"fecha":request.form.get("fecha",""),"responsable":request.form.get("responsable",""),"detalle":request.form.get("detalle","")},0,"Cargado")
        flash("Carga registrada y descontada del stock.")
    except (InvalidOperation,ValueError):
        flash("No se pudo cargar: verificá litros y stock disponible.")
    return redirect(url_for("combustible_stock"))

@app.route("/mantenimiento",methods=["GET","POST"])
@login_required
def mantenimiento():
    _can_area("estacion")
    if request.method=="POST":
        try:
            action=request.form.get("accion","mantenimiento"); equipo=request.form.get("equipo","").strip()
            if action=="lectura":
                reading=Decimal(request.form.get("lectura","").replace(",","."))
                if not equipo or reading<0: raise InvalidOperation()
                _save("lecturas_equipo","Lectura · "+equipo,{"equipo":equipo,"lectura":str(reading),"fecha":request.form.get("fecha",""),"nota":request.form.get("nota","")},0,"Lectura")
                flash("Lectura actualizada.")
            else:
                reading=Decimal(request.form.get("lectura","").replace(",","."))
                if not equipo or reading<0: raise InvalidOperation()
                _save("mantenimiento","Mantenimiento · "+equipo,{"equipo":equipo,"lectura":str(reading),"fecha":request.form.get("fecha",""),"tipo":request.form.get("tipo_mantenimiento","Preventivo"),"detalle":request.form.get("detalle",""),"responsable":request.form.get("responsable","")},0,"Mantenimiento registrado")
                _save("lecturas_equipo","Lectura posterior a mantenimiento · "+equipo,{"equipo":equipo,"lectura":str(reading),"fecha":request.form.get("fecha",""),"nota":"Lectura registrada al realizar mantenimiento"},0,"Lectura")
                flash("Mantenimiento guardado y lectura base actualizada.")
        except (InvalidOperation,ValueError):
            flash("Ingresá una lectura válida.")
        return redirect(url_for("mantenimiento"))
    equip=[_data(r) for r in _rows("flota_equipo")]
    maint=_rows("mantenimiento"); readings=_rows("lecturas_equipo"); summaries=[]
    for e in equip:
        name=e.get("nombre"); istruck=e.get("tipo")=="Camión"; unit="km" if istruck else "horas"
        latest_read=next((_data(r) for r in readings if _data(r).get("equipo")==name),None)
        latest_maint=next((_data(r) for r in maint if _data(r).get("equipo")==name),None)
        current=Decimal(str(latest_read.get("lectura",0) if latest_read else 0))
        daily=Decimal(str(e.get("diario",0)))
        if latest_read and latest_read.get("fecha") and daily>0:
            try:
                last_day=datetime.strptime(latest_read.get("fecha"),"%Y-%m-%d").date()
                current += daily*Decimal(str(max(0,(datetime.now().date()-last_day).days)))
            except ValueError: pass
        base=Decimal(str(latest_maint.get("lectura",current) if latest_maint else current))
        interval=Decimal(str(e.get("intervalo",15000)))
        used=max(Decimal("0"),current-base); remaining=max(Decimal("0"),interval-used)
        summaries.append({"nombre":name,"tipo":e.get("tipo"),"unidad":unit,"intervalo":interval,"diario":daily,"actual":current,"ultimo":latest_maint.get("fecha","Sin mantenimiento") if latest_maint else "Sin mantenimiento","usado":used,"restante":remaining,"dias":(remaining/daily).quantize(Decimal("0.1")) if daily>0 else None})
    return _page("Mantenimiento", """
    <section class="card"><h2>Registrar lectura de uso</h2><form method="post" class="grid"><input type="hidden" name="accion" value="lectura"><div><label>Camión / maquinaria</label><select name="equipo" required><option value="">Seleccionar</option>{% for e in equip %}<option>{{e.get('nombre')}}</option>{% endfor %}</select></div><div><label>Fecha</label><input type="date" name="fecha" value="{{today}}" required></div><div><label>Lectura actual (km u horas)</label><input type="number" name="lectura" min="0" step="0.1" required></div><div><label>Nota</label><input name="nota"></div><div style="align-self:end"><button>Actualizar lectura</button></div></form></section>
    <section class="card"><h2>Registrar mantenimiento</h2><form method="post" class="grid"><div><label>Camión / maquinaria</label><select name="equipo" required><option value="">Seleccionar</option>{% for e in equip %}<option>{{e.get('nombre')}}</option>{% endfor %}</select></div><div><label>Fecha</label><input type="date" name="fecha" value="{{today}}" required></div><div><label>Lectura actual al mantenimiento (km u horas)</label><input type="number" name="lectura" min="0" step="0.1" required></div><div><label>Tipo de mantenimiento</label><select name="tipo_mantenimiento"><option>Preventivo</option><option>Correctivo</option><option>Inspección</option></select></div><div><label>Trabajo realizado</label><input name="detalle" required></div><div><label>Responsable</label><input name="responsable"></div><div style="align-self:end"><button>Guardar mantenimiento</button></div></form></section>
    <section class="card"><h2>Estado y próximo mantenimiento</h2><button type="button" onclick="window.print()">Imprimir</button><table><tr><th>Equipo</th><th>Unidad</th><th>Uso diario estimado</th><th>Intervalo</th><th>Lectura actual</th><th>Uso desde mantenimiento</th><th>Restante</th><th>Estimación de días</th><th>Último mantenimiento</th></tr>{% for s in summaries %}<tr><td>{{s.nombre}} ({{s.tipo}})</td><td>{{s.unidad}}</td><td>{{s.diario}}</td><td>{{s.intervalo}}</td><td>{{s.actual}}</td><td>{{s.usado}}</td><td><b>{{s.restante}} {{s.unidad}}</b></td><td>{{s.dias if s.dias is not none else 'Configurar uso diario'}}</td><td>{{s.ultimo}}</td></tr>{% endfor %}</table></section>
    <section class="card"><h2>Historial de mantenimientos</h2><table><tr><th>Fecha</th><th>Equipo</th><th>Lectura</th><th>Tipo</th><th>Trabajo</th><th>Responsable</th></tr>{% for r in maint %}{% set d=decode(r) %}<tr><td>{{d.get('fecha')}}</td><td>{{d.get('equipo')}}</td><td>{{d.get('lectura')}}</td><td>{{d.get('tipo')}}</td><td>{{d.get('detalle')}}</td><td>{{d.get('responsable')}}</td></tr>{% endfor %}</table></section>
    """,equip=equip,summaries=summaries,maint=maint,today=datetime.now().strftime("%Y-%m-%d"),decode=_data)

@app.route("/gomeria-camiones",methods=["GET","POST"])
@login_required
def gomeria_camiones():
    _can_area("gomeria")
    if request.method=="POST":
        try:
            camion=request.form.get("camion","").strip()
            fecha=request.form.get("fecha","").strip()
            servicio=request.form.get("servicio","").strip()
            detalle=request.form.get("detalle","").strip()
            cantidad=Decimal(request.form.get("cantidad","0").replace(",",".") or "0")
            raw_cost=request.form.get("costo","").strip().replace(",",".")
            costo=Decimal(raw_cost) if raw_cost else Decimal("0")
            if not camion or not fecha or not servicio or not detalle or cantidad<0 or costo<0:
                raise InvalidOperation()
            data={"camion":camion,"fecha":fecha,"servicio":servicio,"detalle":detalle,"cantidad":str(cantidad),
                  "costo":str(costo),"responsable":request.form.get("responsable","").strip(),
                  "observaciones":request.form.get("observaciones","").strip()}
            _save("gomeria_camiones",camion+" · "+servicio,data,costo,"Pagado" if costo>0 else "Registrado")
            if costo>0:
                log_action("gomería con costo registrado","gomeria_camiones",None,f"{camion}; {servicio}; Gs. {costo}")
            flash("Servicio de gomería registrado.")
        except (InvalidOperation,ValueError):
            flash("Revisá los datos del servicio y el costo; el costo puede quedar vacío si no se pagó.")
        return redirect(url_for("gomeria_camiones"))
    rows=[(r,_data(r)) for r in (_rows("gomeria_camiones")+_rows("gomeria"))]
    rows.sort(key=lambda item:item[0].created_at,reverse=True)
    equip=[_data(r) for r in _rows("flota_equipo") if _data(r).get("tipo")=="Camión"]
    return _page("Gomería por camión", """
    <section class="card"><h2>Registrar servicio de gomería</h2><form method="post" class="grid">
    <div><label>Camión</label><select name="camion" required><option value="">Seleccionar</option>{% for e in equip %}<option>{{e.get('nombre')}}</option>{% endfor %}</select></div>
    <div><label>Fecha</label><input name="fecha" type="date" value="{{today}}" required></div>
    <div><label>Tipo de servicio</label><select name="servicio" required><option>Reparación de cubierta</option><option>Cambio de cubierta</option><option>Reparación de cámara</option><option>Cambio de cámara</option><option>Otro</option></select></div>
    <div><label>Descripción del trabajo</label><input name="detalle" required></div><div><label>Cantidad (si aplica)</label><input name="cantidad" type="number" min="0" step="0.001"></div>
    <div><label>Costo pagado (Gs., opcional)</label><input name="costo" type="number" min="0" step="0.01"></div>
    <div><label>Responsable</label><input name="responsable"></div><div><label>Observaciones</label><input name="observaciones"></div>
    <div style="align-self:end"><button>Guardar servicio</button></div></form></section>
    <section class="card"><h2>Historial de gomería por camión</h2><button type="button" onclick="window.print()">Imprimir</button>
    <table><tr><th>Fecha</th><th>Camión</th><th>Servicio</th><th>Descripción</th><th>Cantidad</th><th>Costo</th><th>Responsable</th><th>Observaciones</th><th>Imprimir</th></tr>
    {% for r,d in rows %}<tr><td>{{d.get('fecha')}}</td><td>{{d.get('camion')}}</td><td>{{d.get('servicio')}}</td><td>{{d.get('detalle')}}</td><td>{{d.get('cantidad')}}</td><td>{{d.get('costo')}}</td><td>{{d.get('responsable')}}</td><td>{{d.get('observaciones')}}</td><td><a class="btn" href="{{url_for('print_record',rid=r.id)}}">Imprimir</a></td></tr>{% endfor %}</table></section>
    """,rows=rows,equip=equip,today=datetime.now().strftime("%Y-%m-%d"))


@app.get("/auditoria-pagos")
@login_required
def auditoria_pagos():
    _can_area("auditoria")
    q=request.args.get("q","").strip().casefold(); start=request.args.get("desde",""); end=request.args.get("hasta","")
    modules=["pagos_diarios","prestamos_pagos","pagos_cuentas","gastos","combustible_camion","gomeria_camiones","gomeria","fletes","planillas","solicitudes"]
    rows=[]
    for mod in modules:
        for r in _rows(mod):
            d=_data(r)
            if q and q not in (r.title+" "+r.data+" "+str(r.amount)).casefold(): continue
            record_date=str(d.get("fecha") or r.created_at.strftime("%Y-%m-%d"))[:10]
            if start and record_date<start: continue
            if end and record_date>end: continue
            rows.append(r)
    # Incluir todas las salidas reales de dinero y pagos ejecutados; no las solicitudes pendientes ni las cuentas por cobrar.
    rows=[r for r in rows if r.module not in ("solicitudes","cuentas_pagar") or r.status in ("Pagado","Pago parcial","Desembolsado")]
    rows.sort(key=lambda x:x.created_at,reverse=True)
    return _page("Auditoría de pagos", """
    <section class="card"><h2>Auditoría · Salidas de dinero y pagos</h2><form method="get" class="grid"><div><label>Buscar ticket, proveedor, importe, medio o concepto</label><input name="q" value="{{q}}"></div><div><label>Desde</label><input type="date" name="desde" value="{{start}}"></div><div><label>Hasta</label><input type="date" name="hasta" value="{{end}}"></div><div style="align-self:end"><button>Buscar</button><button type="button" onclick="window.print()">Imprimir auditoría</button></div></form>
    <table><tr><th>Fecha/hora</th><th>Sector</th><th>Operación</th><th>Detalle completo</th><th>Estado</th><th>Importe</th><th>Registro</th></tr>{% for r in rows %}<tr><td>{{r.created_at.strftime('%d/%m/%Y %H:%M')}}</td><td>{{MODULES.get(r.module,(r.module,))[0]}}</td><td>{{r.title}}</td><td>{{r.data}}</td><td>{{r.status}}</td><td>{{r.amount}}</td><td><a class="btn" href="{{url_for('print_record',rid=r.id)}}">Imprimir</a></td></tr>{% endfor %}</table></section>
    """,rows=rows,q=q,start=start,end=end)
 
@app.route("/fletes",methods=["GET","POST"])
@login_required
def fletes():
    _can_caja()
    if request.method=="POST":
        try:
            fecha=request.form.get("fecha","").strip()
            chofer=request.form.get("chofer","").strip()
            destino=request.form.get("destino","").strip()
            camion=request.form.get("camion","").strip()
            importe=Decimal(request.form.get("importe","0").replace(",","."))
            detalle=request.form.get("detalle","").strip()
            if not fecha or not chofer or not destino or not camion or importe<0:
                raise InvalidOperation()
            data={"fecha":fecha,"chofer":chofer,"destino":destino,"camion":camion,"importe":str(importe),"detalle":detalle}
            _save("fletes","Flete · "+camion+" · "+destino,data,importe,"Pagado" if importe>0 else "Registrado")
            flash("Flete guardado.")
        except (InvalidOperation,ValueError):
            flash("Revisá la fecha, el chofer, el destino, el camión y el importe.")
        return redirect(url_for("fletes"))
    rows=[(r,_data(r)) for r in _rows("fletes")]
    q=request.args.get("q","").strip().casefold()
    rows=[(r,d) for r,d in rows if not q or q in (r.title+" "+r.data+" "+str(r.amount)).casefold()]
    equip=[_data(r) for r in _rows("flota_equipo") if _data(r).get("tipo")=="Camión"]
    return _page("Fletes", """
    <section class="card"><h2>Registrar flete</h2><form method="post" class="grid">
    <div><label>Fecha</label><input name="fecha" type="date" value="{{today}}" required></div>
    <div><label>Chofer</label><input name="chofer" required></div><div><label>Destino / lugar de entrega</label><input name="destino" required></div>
    <div><label>Camión utilizado</label><input name="camion" list="camiones-lista" required><datalist id="camiones-lista">{% for e in equip %}<option value="{{e.get('nombre')}}">{% endfor %}</datalist></div>
    <div><label>Importe del flete (Gs.)</label><input name="importe" type="number" min="0" step="0.01" value="0" required></div>
    <div><label>Observaciones</label><input name="detalle"></div><div style="align-self:end"><button>Guardar flete</button></div></form></section>
    <section class="card"><h2>Historial de fletes</h2><form class="actions"><input name="q" value="{{q}}" placeholder="Buscar chofer, destino, camión"><button>Buscar</button><button type="button" onclick="window.print()">Imprimir</button></form>
    <table><tr><th>Fecha</th><th>Chofer</th><th>Destino</th><th>Camión</th><th>Importe</th><th>Detalle</th><th>Imprimir</th></tr>
    {% for r,d in rows %}<tr><td>{{d.get('fecha')}}</td><td>{{d.get('chofer')}}</td><td>{{d.get('destino')}}</td><td>{{d.get('camion')}}</td><td>{{d.get('importe')}}</td><td>{{d.get('detalle')}}</td><td><a class="btn" href="{{url_for('print_record',rid=r.id)}}">Imprimir</a></td></tr>{% endfor %}</table></section>
    """,rows=rows,q=q,equip=equip,today=datetime.now().strftime("%Y-%m-%d"))


# Caja chica: saldo disponible, gastos clasificados y trazabilidad de movimientos.
@app.route("/caja-chica", methods=["GET", "POST"])
@login_required
def caja_chica():
    _can_caja()
    if request.method == "POST":
        action=request.form.get("accion","gasto")
        fecha=request.form.get("fecha", datetime.now().strftime("%Y-%m-%d")).strip()
        medio=request.form.get("medio","").strip()
        try:
            if action == "saldo":
                saldo=Decimal(request.form.get("saldo","").strip().replace(",","."))
                if saldo < 0 or not fecha:
                    raise InvalidOperation()
                _save("caja_chica","Actualización de saldo de caja chica",{
                    "tipo":"saldo","fecha":fecha,"saldo":str(saldo),
                    "detalle":request.form.get("detalle","").strip(),
                    "medio":medio,"clasificacion":"saldo"
                },saldo,"Saldo actualizado")
                flash("Saldo disponible de caja chica actualizado.")
            else:
                detalle=request.form.get("detalle","").strip()
                importe=Decimal(request.form.get("importe","").strip().replace(",","."))
                clasificacion=request.form.get("clasificacion","caja_chica").strip()
                if not detalle or not fecha or importe<=0 or clasificacion not in ("caja_chica","gastos") or not medio:
                    raise InvalidOperation()
                _save("caja_chica","Gasto caja chica · "+detalle[:150],{
                    "tipo":"gasto","fecha":fecha,"detalle":detalle,"importe":str(importe),
                    "medio":medio,"clasificacion":clasificacion
                },importe,"Registrado")
                log_action("registrar gasto de caja chica","caja_chica",None,
                           f"{detalle}; importe {importe}; clasificación {clasificacion}; medio {medio}")
                flash("Movimiento de caja chica guardado.")
        except (InvalidOperation,ValueError):
            db.session.rollback()
            flash("Revisá la fecha, la descripción y el monto. El saldo no puede ser negativo y el gasto debe ser mayor que cero.")
        return redirect(url_for("caja_chica"))
    rows=_rows("caja_chica")
    latest_balance=next((r for r in rows if _data(r).get("tipo")=="saldo"),None)
    if latest_balance:
        bd=_data(latest_balance)
        balance=Decimal(str(bd.get("saldo","0")))
        expenses=[r for r in rows if _data(r).get("tipo")=="gasto" and r.created_at>latest_balance.created_at]
        balance-=sum((Decimal(str(r.amount or 0)) for r in expenses),Decimal("0"))
    else:
        balance=Decimal("0")
    q=request.args.get("q","").strip().casefold()
    # El historial de Caja chica debe mostrar solo gastos; los ajustes de saldo
    # son operaciones administrativas y no representan dinero gastado.
    shown=[r for r in rows if _data(r).get("tipo")=="gasto" and
           (not q or q in (r.title+" "+r.data+" "+str(r.amount)).casefold())]
    return _page("Caja chica", """
    <section class="card"><h2>Saldo disponible de caja chica</h2><h3>Gs. {{balance}}</h3>
    <form method="post" class="grid"><input type="hidden" name="accion" value="saldo">
    <div><label>Monto disponible actual (Gs.)</label><input name="saldo" type="number" min="0" step="0.01" required></div>
    <div><label>Fecha</label><input name="fecha" type="date" value="{{today}}" required></div>
    <div><label>Detalle del ajuste (opcional)</label><input name="detalle"></div>
    <div style="align-self:end"><button>Guardar monto disponible</button></div></form></section>
    <section class="card"><h2>Registrar gasto de caja chica</h2><form method="post" class="grid">
    <input type="hidden" name="accion" value="gasto">
    <div><label>En qué se gastó</label><input name="detalle" required></div>
    <div><label>Monto gastado (Gs.)</label><input name="importe" type="number" min="0.01" step="0.01" required></div>
    <div><label>Fecha</label><input name="fecha" type="date" value="{{today}}" required></div>
    <div><label>Medio de pago</label><select name="medio" required><option value="">Seleccionar</option><option>Efectivo</option><option>Transferencia</option><option>Cheque</option><option>Tarjeta</option><option>Otro</option></select></div>
    <div><label>Clasificación</label><select name="clasificacion" required><option value="caja_chica">Caja chica (no sumar a Gastos)</option><option value="gastos">Gastos (sumar al resumen de Gastos)</option></select></div>
    <div style="align-self:end"><button>Guardar gasto</button></div></form></section>
    <section class="card"><h2>Historial de movimientos</h2><form class="actions"><input name="q" value="{{q}}" placeholder="Buscar descripción o monto"><button>Buscar</button><button type="button" onclick="window.print()">Imprimir</button></form>
    <table><tr><th>Fecha</th><th>Movimiento</th><th>Descripción</th><th>Medio</th><th>Clasificación</th><th>Monto</th></tr>
    {% for r in shown %}{% set d=decode(r) %}<tr><td>{{d.get('fecha')}}</td><td>{{'Actualización de saldo' if d.get('tipo')=='saldo' else 'Gasto'}}</td><td>{{d.get('detalle','—')}}</td><td>{{d.get('medio','—')}}</td><td>{% if d.get('tipo')=='saldo' %}Saldo disponible{% elif d.get('clasificacion')=='gastos' %}Gastos{% else %}Caja chica{% endif %}</td><td>{{d.get('saldo') if d.get('tipo')=='saldo' else r.amount}}</td></tr>{% endfor %}</table></section>
    """,balance=balance,shown=shown,q=q,today=datetime.now().strftime("%Y-%m-%d"),decode=_data)


# Informes profesionales: comparaciones mensuales basadas en registros existentes.
from zoneinfo import ZoneInfo as _ZoneInfo
from datetime import date as _date, timedelta as _timedelta
from sqlalchemy import func as _func
from app import Material as _Material, User as _User

def _analytics_periods():
    now=datetime.now(_ZoneInfo("America/Asuncion"))
    current_start=now.replace(day=1,hour=0,minute=0,second=0,microsecond=0).replace(tzinfo=None)
    if now.month==1:
        prev_start=current_start.replace(year=now.year-1,month=12)
    else:
        prev_start=current_start.replace(month=now.month-1)
    return now,current_start,prev_start

def _record_date(rec, data):
    raw=data.get("fecha")
    if raw:
        try: return datetime.strptime(str(raw)[:10], "%Y-%m-%d")
        except (ValueError,TypeError): pass
    return rec.created_at

def _monthly_records(modules, start, end):
    out=[]
    for mod in modules:
        for rec in Record.query.filter_by(module=mod).all():
            data=_data(rec); dt=_record_date(rec,data)
            if start <= dt < end:
                out.append((rec,data))
    return out

def _period_end(start):
    return start.replace(year=start.year+1,month=1) if start.month==12 else start.replace(month=start.month+1)

def _delta_label(current, previous):
    if current==previous: return ("Igual","flat")
    if current>previous: return ("Subió","up")
    return ("Bajó","down")

def _professional_reports():
    original_reports=app.view_functions.get("reports")
    original_module_report=app.view_functions.get("report_module")
    def reports_pro():
        available=[(key,meta[0]) for key,meta in MODULES.items() if allowed(key)]
        return render_template_string(BASE+"""
        <section class="card"><h2>Informes por sector</h2><p>Consultá los movimientos y compará los resultados de cada sector.</p>
        <style>.report-open{color:#111!important;background:#eef3f8;border-color:#cbd7e5}.report-open:hover{color:#111!important;background:#dce6f1;border-color:#b6c7da}.analytics-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin:16px 0}.analytics-kpi{padding:15px;border:1px solid #e1e8f0;border-radius:11px;background:#f8fafd}.analytics-kpi span{display:block;font-size:11px;color:#62748a;font-weight:700}.analytics-kpi strong{display:block;font-size:22px;color:#173d67;margin-top:5px}.trend-up{color:#16805d;font-weight:800}.trend-down{color:#b54747;font-weight:800}.trend-flat{color:#64748b;font-weight:800}.analytics-table{margin:12px 0 20px}.analytics-table td,.analytics-table th{white-space:normal}.analytics-note{color:#687b91;font-size:12px;margin:8px 0 14px}@media(max-width:600px){.analytics-kpi{padding:11px}.analytics-kpi strong{font-size:18px}}</style>
        <div class="grid">{% for key,label in available %}<div class="card"><h3>{{label}}</h3><p><a class="btn report-open" href="{{url_for('report_module',module=key)}}">Abrir informe</a></p></div>{% endfor %}</div>
        <p><a class="btn report-open" href="{{url_for('general_history')}}">Historial general</a></p></section></main><footer>El Toro S.A.</footer></body></html>""",title="Informes",available=available)

    def report_module_pro(module):
        if module not in MODULES: abort(404)
        if not allowed(module): abort(403)
        q=request.args.get("q","").strip().casefold(); since=request.args.get("desde",""); until=request.args.get("hasta",""); amount_filter=request.args.get("monto","").strip()
        items=Record.query.filter_by(module=module).order_by(Record.created_at.desc()).all(); results=[]
        for r in items:
            d=_data(r); hay=(r.title+" "+r.status+" "+str(r.amount)+" "+r.data).casefold()
            if q and q not in hay: continue
            dt=_record_date(r,d).strftime("%Y-%m-%d")
            if since and dt<since: continue
            if until and dt>until: continue
            if amount_filter and amount_filter not in str(r.amount): continue
            results.append((r,d))
        now,cur_start,prev_start=_analytics_periods()
        cur_end=_period_end(cur_start); prev_end=cur_start
        prev2_start=prev_start
        label=MODULES[module][0]
        stats_kind=None; stats_rows=[]; kpis=[]
        money_modules={
            "pagos_diarios":("Pagos efectuados","Pagos diarios y por ticket"),
            "pagos_cuentas":("Pagos registrados","Movimientos de pagos"),
            "cobros_cuentas":("Cobros registrados","Cobros de cuentas por cobrar"),
            "caja_chica":("Gastos de caja chica","Caja chica"),
            "gastos":("Gastos registrados","Gastos"),
            "solicitudes":("Pagos ejecutados","Solicitudes de pago"),
            "planillas":("Pagos a proveedores","Cuenta de proveedores"),
            "cuentas_cobrar":("Deuda por cobrar","Cuentas por cobrar"),
            "cuentas_pagar":("Deuda por pagar","Cuentas por pagar"),
            "tickets":("Tickets registrados","Tickets de entrada"),
            "prestamos_pagos":("Pagos de préstamos","Pagos de préstamos")
        }
        def amt(rec,data):
            if module=="caja_chica" and data.get("tipo")!="gasto": return Decimal("0")
            if module=="planillas": return Decimal(str(data.get("pago",rec.amount) or 0))
            if module=="cuentas_cobrar": return Decimal(str(data.get("importe",rec.amount) or 0))
            if module=="cuentas_pagar": return Decimal(str(data.get("importe",rec.amount) or 0))
            if module=="solicitudes" and rec.status not in ("Pagado","Pago parcial","Desembolsado"): return Decimal("0")
            return Decimal(str(rec.amount or 0))
        if module in money_modules:
            cur=_monthly_records([module],cur_start,cur_end); prev=_monthly_records([module],prev_start,cur_start)
            cur_total=sum((amt(r,d) for r,d in cur),Decimal("0")); prev_total=sum((amt(r,d) for r,d in prev),Decimal("0"))
            cur_count=sum(1 for r,d in cur if amt(r,d)>0); prev_count=sum(1 for r,d in prev if amt(r,d)>0)
            diff=cur_total-prev_total
            trend,trend_class=_delta_label(cur_total,prev_total)
            kpis=[{"label":"Total del mes actual","value":cur_total,"detail":now.strftime("%B %Y").capitalize()},
                  {"label":"Total del mes anterior","value":prev_total,"detail":prev_start.strftime("%B %Y").capitalize()},
                  {"label":"Variación","value":("+" if diff>0 else "")+str(diff),"detail":trend,"trend":trend_class},
                  {"label":"Operaciones este mes","value":cur_count,"detail":"Mes anterior: "+str(prev_count)}]
            stats_kind="money"
        if module=="materiales":
            materials=_Material.query.order_by(_Material.name).all()
            activity_modules=["tickets","ventas","planillas"]
            cur=_monthly_records(activity_modules,cur_start,cur_end); prev=_monthly_records(activity_modules,prev_start,cur_start)
            for m in materials:
                def measure(records):
                    count=Decimal("0"); qty=Decimal("0")
                    for rec,d in records:
                        mid=str(d.get("material_id",""))
                        name=str(d.get("material","") or d.get("nombre_material",""))
                        matches=(name.casefold()==m.name.casefold() or mid==str(m.id))
                        if not matches: continue
                        count+=1
                        qty+=Decimal(str(d.get("cantidad",d.get("kg",0)) or 0))
                    return count,qty
                cc,cq=measure(cur); pc,pq=measure(prev)
                trend,trend_class=_delta_label(cq,pq)
                stats_rows.append({"name":m.name,"cur_count":cc,"prev_count":pc,"cur_qty":cq,"prev_qty":pq,"trend":trend,"trend_class":trend_class})
            stats_kind="materials"
        if module in ("proveedores","planillas","tickets"):
            vendors=[]
            if module=="proveedores":
                vendors=[_data(r).get("nombre","") for r in _rows("proveedores") if _data(r).get("nombre")]
            else:
                vendors=[_data(r).get("nombre") or _data(r).get("cliente") or _data(r).get("persona") for r in _rows("proveedores")]
                vendors=[v for v in vendors if v]
            if vendors:
                vendors=sorted(set(vendors),key=lambda x:x.casefold())
            else:
                vendors=sorted(set(str(_data(r).get("cliente") or _data(r).get("persona") or _data(r).get("proveedor") or "").strip() for r in _rows("tickets")+_rows("planillas") if (_data(r).get("cliente") or _data(r).get("persona") or _data(r).get("proveedor"))),key=lambda x:x.casefold())
            cur=_monthly_records(["tickets","planillas"],cur_start,cur_end); prev=_monthly_records(["tickets","planillas"],prev_start,cur_start)
            for name in vendors:
                cc=sum(1 for r,d in cur if str(d.get("cliente") or d.get("proveedor") or d.get("persona") or "").casefold()==name.casefold())
                pc=sum(1 for r,d in prev if str(d.get("cliente") or d.get("proveedor") or d.get("persona") or "").casefold()==name.casefold())
                trend,trend_class=_delta_label(Decimal(cc),Decimal(pc))
                stats_rows.append({"name":name,"cur_count":cc,"prev_count":pc,"trend":trend,"trend_class":trend_class})
            if module=="proveedores": stats_kind="vendors"
        return render_template_string(BASE+"""
        <style>.analytics-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin:16px 0}.analytics-kpi{padding:15px;border:1px solid #e1e8f0;border-radius:11px;background:#f8fafd}.analytics-kpi span{display:block;font-size:11px;color:#62748a;font-weight:700}.analytics-kpi strong{display:block;font-size:22px;color:#173d67;margin-top:5px}.trend-up{color:#16805d;font-weight:800}.trend-down{color:#b54747;font-weight:800}.trend-flat{color:#64748b;font-weight:800}.analytics-note{color:#687b91;font-size:12px;margin:8px 0 14px}.analytics-table{margin:12px 0 20px}@media(max-width:600px){.analytics-kpi{padding:11px}.analytics-kpi strong{font-size:18px}}</style>
        <section class="card"><h2>Informe: {{label}}</h2>
        {% if kpis %}<div class="analytics-kpis">{% for k in kpis %}<div class="analytics-kpi"><span>{{k.label}}</span><strong>{% if 'Total' in k.label or 'Deuda' in k.label or 'Gastos' in k.label or 'Pagos' in k.label or 'Cobros' in k.label or 'Variación' in k.label %}Gs. {% endif %}{{k.value}}</strong>{% if k.trend %}<div class="trend-{{k.trend}}">{{k.detail}}</div>{% else %}<div>{{k.detail}}</div>{% endif %}</div>{% endfor %}</div>{% endif %}
        {% if stats_kind=='materials' %}<h3>Estadística mensual por material</h3><p class="analytics-note">Comparación de actividad registrada en tickets, ventas y planillas. Se compara la cantidad (kg/unidades) de este mes con el mes anterior.</p><div style="overflow-x:auto"><table class="analytics-table"><tr><th>Material</th><th>Movimientos este mes</th><th>Movimientos mes anterior</th><th>Cantidad este mes</th><th>Cantidad mes anterior</th><th>Comparación</th></tr>{% for s in stats_rows %}<tr><td><b>{{s.name}}</b></td><td>{{s.cur_count}}</td><td>{{s.prev_count}}</td><td>{{s.cur_qty}}</td><td>{{s.prev_qty}}</td><td class="trend-{{s.trend_class}}">{{s.trend}}</td></tr>{% else %}<tr><td colspan="6">Todavía no hay materiales registrados.</td></tr>{% endfor %}</table></div>
        {% elif stats_kind=='vendors' %}<h3>Actividad mensual por proveedor</h3><p class="analytics-note">Cantidad de operaciones de tickets y planillas asociadas a cada proveedor.</p><div style="overflow-x:auto"><table class="analytics-table"><tr><th>Proveedor</th><th>Este mes</th><th>Mes anterior</th><th>Comparación</th></tr>{% for s in stats_rows %}<tr><td><b>{{s.name}}</b></td><td>{{s.cur_count}}</td><td>{{s.prev_count}}</td><td class="trend-{{s.trend_class}}">{{s.trend}}</td></tr>{% else %}<tr><td colspan="4">Todavía no hay proveedores registrados.</td></tr>{% endfor %}</table></div>{% endif %}
        <form method="get" class="grid"><div><label>Buscar cualquier dato</label><input name="q" value="{{q}}"></div><div><label>Desde</label><input type="date" name="desde" value="{{since}}"></div><div><label>Hasta</label><input type="date" name="hasta" value="{{until}}"></div><div><label>Monto</label><input name="monto" value="{{amount_filter}}"></div><div style="align-self:end"><button>Buscar</button> <a class="btn report-open" href="{{url_for('report_module',module=module)}}">Limpiar</a></div></form>
        <p><button type="button" onclick="window.print()">Imprimir informe</button></p><div style="overflow-x:auto"><table><tr><th>Fecha/hora</th><th>Operación</th><th>Detalle</th><th>Estado</th><th>Monto</th><th>Imprimir</th></tr>
        {% for r,d in results %}<tr><td>{{_record_date(r,d).strftime('%d/%m/%Y %H:%M')}}</td><td>{{r.title}}</td><td>{% for k,v in d.items() %}{% if v is string %}<div><b>{{k}}:</b> {{v}}</div>{% elif v is sequence and v is not string %}{% for line in v %}{% if line is mapping %}<div>{% for lk,lv in line.items() %}{{lk}}: {{lv}} · {% endfor %}</div>{% else %}{{line}}{% endif %}{% endfor %}{% endif %}{% endfor %}</td><td>{{r.status}}</td><td>{{r.amount}}</td><td><a class="btn" href="{{url_for('print_record',rid=r.id)}}">Imprimir</a></td></tr>{% else %}<tr><td colspan="6">No hay registros para los filtros seleccionados.</td></tr>{% endfor %}</table></div></section></main><footer>El Toro S.A.</footer></body></html>""",title="Informe",label=label,module=module,q=q,since=since,until=until,amount_filter=amount_filter,results=results,kpis=kpis,stats_kind=stats_kind,stats_rows=stats_rows,_record_date=_record_date)
    app.view_functions["reports"]=reports_pro
    app.view_functions["report_module"]=report_module_pro

_professional_reports()
