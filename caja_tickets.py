import json
from decimal import Decimal, InvalidOperation
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import request, redirect, url_for, flash, abort
from app import app, db, Record, Material, CompanyAccount, MODULES, current_user, log_action, paraguay_now, local_time
from features import _rows, _data, _can_caja, _page

MODULES["tickets_entrada"] = ("Tickets registrados", "caja", [])

def _central_account():
    return CompanyAccount.query.filter_by(active=True).order_by(CompanyAccount.id.asc()).first()

def registrar_ticket():
    _can_caja()
    materials=Material.query.order_by(Material.name).all()
    vendors=[]
    for r in _rows("proveedores"):
        d=_data(r)
        if d.get("nombre"):
            prices={}
            for m in materials:
                p=d.get("precios_materiales",{}).get(str(m.id))
                if p in (None,""):
                    p=m.wholesale_price if m.wholesale_price is not None else m.price
                prices[str(m.id)]=str(p or 0)
            vendors.append({"nombre":d["nombre"],"codigo":d.get("codigo",""),"precios":prices,"en_pagos":bool(d.get("en_pagos",False)),"proveedor_id":r.id})
    today=datetime.now(ZoneInfo("America/Asuncion")).strftime("%Y-%m-%d")
    if request.method=="POST":
        ticket=request.form.get("ticket","").strip()
        persona=request.form.get("persona","").strip()
        fecha=request.form.get("fecha","").strip()
        ids=request.form.getlist("material_id[]")
        quantities=request.form.getlist("kg[]")
        vendor=next((v for v in vendors if v["nombre"].strip().casefold()==persona.casefold()),None)
        try:
            if not ticket or not persona or not fecha or not vendor or not ids or len(ids)!=len(quantities):
                raise InvalidOperation()
            if any(_data(r).get("ticket","").casefold()==ticket.casefold() for r in _rows("tickets_entrada")):
                flash("Ese número de ticket ya existe. Usá uno diferente.")
                return redirect(url_for("registrar_ticket"))
            lines=[]; total=Decimal("0")
            for mid,raw in zip(ids,quantities):
                mid=mid.strip(); raw=raw.strip().replace(",",".")
                if not mid and not raw: continue
                if not mid or not raw: raise InvalidOperation()
                mat=db.session.get(Material,int(mid)); kg=Decimal(raw)
                if not mat or kg<=0: raise InvalidOperation()
                price=Decimal(str(vendor["precios"].get(str(mat.id),"0") or "0"))
                if price<=0:
                    flash("Configurá primero el precio de "+mat.name+" para ese proveedor.")
                    return redirect(url_for("registrar_ticket"))
                subtotal=(kg*price).quantize(Decimal("0.01"))
                lines.append({"material_id":mat.id,"material":mat.name,"kg":str(kg),"precio_unitario":str(price),"importe":str(subtotal)})
                total+=subtotal
            total=total.quantize(Decimal("0.01"))
            if not lines or total<=0: raise InvalidOperation()
            data={"ticket":ticket,"persona":persona,"fecha":fecha,"materiales":lines,"total":str(total),"saldo":str(total),"pagado_acumulado":"0","estado":"Pendiente","en_pagos":request.form.get("en_pagos")=="1","excluir_de_pagos":request.form.get("en_pagos")!="1","proveedor_id":vendor.get("proveedor_id")}
            rec=Record(module="tickets_entrada",title="Ticket "+ticket+" · "+persona,data=json.dumps(data,ensure_ascii=False),
                       amount=total,status="Pendiente de pago",created_by=current_user().id)
            db.session.add(rec); db.session.flush()
            for line in lines:
                mat=db.session.get(Material,int(line["material_id"]))
                kg=Decimal(str(line["kg"])); mat.stock+=kg
                invdata={"material":mat.name,"material_id":mat.id,"cantidad_ingresada":str(kg),
                    "cantidad_disponible":str(mat.stock),"origen":"ticket_entrada","ticket":ticket,"proveedor":persona,
                    "precio_unitario":line["precio_unitario"],"importe":line["importe"],"fecha":fecha,"registro_ticket_id":rec.id}
                inv=Record(module="inventario",title="Entrada de material · "+mat.name+" · Ticket "+ticket,
                    data=json.dumps(invdata,ensure_ascii=False),amount=Decimal(str(line["importe"])),
                    status="Entrada de ticket",created_by=current_user().id)
                db.session.add(inv); db.session.flush()
                log_action("entrada de material por ticket","inventario",inv.id,f"Ticket {ticket}; {mat.name}: +{kg} kg; stock {mat.stock}")
            log_action("registrar ticket de entrada","tickets_entrada",rec.id,f"Ticket {ticket}; {persona}; total {total}")
            db.session.commit()
            flash("Ticket registrado. Total: Gs. "+str(total)+(". Quedó disponible en Pagos." if data["en_pagos"] else ". Se guardó en el historial; no se envió a Pagos."))
        except (InvalidOperation,ValueError,TypeError):
            db.session.rollback()
            flash("Revisá el número de ticket, proveedor, fecha, materiales, kg y precios.")
        return redirect(url_for("registrar_ticket"))
    q=request.args.get("q","").strip().casefold()
    history_records=(Record.query.filter(Record.module.in_(["tickets_entrada","tickets"]))
                     .order_by(Record.created_at.desc()).all())
    history=[]
    for r in history_records:
        try:
            d=json.loads(r.data or "{}")
        except (ValueError,TypeError):
            d={}
        number=str(d.get("ticket") or d.get("numero_ticket") or d.get("nro_ticket") or ("CARGA-"+str(r.id)))
        person=str(d.get("persona") or d.get("cliente") or r.title or "")
        materials_text=" ".join(str(x.get("material","")) for x in d.get("materiales",[]) if isinstance(x,dict))
        searchable=(number+" "+person+" "+materials_text+" "+str(r.amount or "")).casefold()
        if not q or q in searchable:
            history.append((r,d,number,person))
    return _page("Registrar ticket", """
    <section class="card"><h2>Registrar ticket</h2><form method="post" class="grid" id="ticket-form">
    <div><label>N.º de ticket</label><input name="ticket" required></div>
    <div><label>Proveedor</label><input name="persona" list="proveedores-lista" required><datalist id="proveedores-lista">{% for v in vendors %}<option value="{{v.nombre}}">{{v.codigo}}</option>{% endfor %}</datalist></div>
    <div><label>Fecha del ticket</label><input name="fecha" type="date" value="{{today}}" required></div>
    <div id="payment-option"><label><input type="checkbox" name="en_pagos" value="1" checked> Mostrar en Pagos de tickets</label><p>Marcado por defecto. Desmarcá esta casilla si no querés que el ticket aparezca en Pagos de tickets.</p></div>
    <div style="grid-column:1/-1"><h3>Materiales</h3><table><tr><th>Material</th><th>Kg</th><th>Precio unitario</th><th>Importe</th><th></th></tr><tbody id="material-lines">
    {% for n in range(2) %}<tr><td><select name="material_id[]" class="material-select"><option value="">Elegir</option>{% for m in materials %}<option value="{{m.id}}">{{m.name}}</option>{% endfor %}</select></td><td><input name="kg[]" class="kg-input" type="number" min="0.001" step="0.001"></td><td><input class="price-input" readonly></td><td><input class="subtotal-input" readonly value="0"></td><td><button type="button" class="remove-line">Quitar</button></td></tr>{% endfor %}</tbody></table>
    <template id="material-row"><tr><td><select name="material_id[]" class="material-select"><option value="">Elegir</option>{% for m in materials %}<option value="{{m.id}}">{{m.name}}</option>{% endfor %}</select></td><td><input name="kg[]" class="kg-input" type="number" min="0.001" step="0.001"></td><td><input class="price-input" readonly></td><td><input class="subtotal-input" readonly value="0"></td><td><button type="button" class="remove-line">Quitar</button></td></tr></template>
    <p><button type="button" id="add-material">Agregar material</button></p><div><label>Total del ticket (Gs.)</label><input id="total" readonly value="0"></div></div>
    <div style="align-self:end"><button>Guardar ticket</button></div></form></section>
    <script type="application/json" id="pago-vendors">{{vendors|tojson}}</script><script type="application/json" id="pago-materials">{{material_data|tojson}}</script><script src="{{url_for('static',filename='registrar_ticket.js')}}" defer></script>
    <section class="card"><h2>Historial de tickets registrados</h2>
    <form method="get" class="grid"><div><label>Buscar ticket, proveedor o material</label><input name="q" value="{{q}}" placeholder="Número de ticket, proveedor o material"></div><div style="align-self:end"><button>Buscar</button> <a class="btn" href="{{url_for('registrar_ticket')}}">Limpiar</a></div></form>
    <p><button class="btn" type="button" onclick="window.print()">Imprimir historial</button></p>
    <div style="overflow-x:auto"><table><tr><th>Fecha</th><th>N.º de ticket</th><th>Proveedor</th><th>Materiales</th><th>Total</th><th>Estado</th><th>Acción</th></tr>
    {% for r,d,number,person in history %}<tr><td>{{d.get('fecha') or local_time(r.created_at).strftime('%d/%m/%Y %H:%M')}}</td><td>{{number}}</td><td>{{person}}</td><td>{% for line in d.get('materiales',[]) %}{{line.get('material','—')}} · {{line.get('kg',line.get('cantidad',''))}} kg · Gs. {{line.get('importe',line.get('total',''))}}<br>{% endfor %}</td><td>Gs. {{r.amount or d.get('total','0')}}</td><td>{{r.status}}</td><td><a class="btn" href="{{url_for('print_record',rid=r.id)}}">Ver ticket</a></td></tr>{% else %}<tr><td colspan="7">No hay tickets registrados que coincidan con la búsqueda.</td></tr>{% endfor %}</table></div></section>
    """,today=today,materials=materials,vendors=vendors,material_data=[{"id":m.id,"name":m.name} for m in materials],history=history,q=q,local_time=local_time)

def pagos_diarios():
    _can_caja()
    # Mostrar cargas creadas tanto por Registrar ticket como por el formulario anterior Registrar carga.
    records=(Record.query.filter(Record.module.in_(["tickets_entrada","tickets"]))
             .order_by(Record.created_at.desc()).all())
    # Los tickets nuevos entran a Pagos solo si el proveedor fue marcado en Administrar proveedores.
    # Los registros históricos sin la marca se mantienen visibles para no perder su seguimiento.
    records=[r for r in records if not _data(r).get("excluir_de_pagos",False) and _data(r).get("en_pagos",True) is not False]
    q=request.args.get("q","").strip().casefold()
    month=request.args.get("mes",datetime.now(ZoneInfo("America/Asuncion")).strftime("%Y-%m"))
    if q: records=[r for r in records if q in (r.title+" "+r.data+" "+str(r.amount)).casefold()]
    payments=Record.query.filter_by(module="pagos_diarios").order_by(Record.created_at.desc()).all()
    rows=[]
    for r in records:
        d=_data(r)
        ticket_number=str(d.get("ticket") or d.get("numero_ticket") or d.get("nro_ticket") or ("CARGA-"+str(r.id))).strip()
        paid=Decimal("0")
        # Cada pago se suma una sola vez, aunque tenga tanto ID de origen como número de ticket.
        for p in payments:
            pd=_data(p)
            linked=(str(pd.get("ticket_entrada_id",""))==str(r.id) or
                    str(pd.get("ticket_origen_id",""))==str(r.id) or
                    str(pd.get("ticket","")).strip().casefold()==ticket_number.casefold())
            if linked:
                paid+=Decimal(str(pd.get("importe",p.amount or 0) or p.amount or 0))
        d["_display_ticket"]=ticket_number
        d["_display_persona"]=str(d.get("persona") or d.get("cliente") or "")
        d["_display_fecha"]=str(d.get("fecha") or local_time(r.created_at).strftime("%Y-%m-%d"))
        total=Decimal(str(r.amount or d.get("total","0") or 0))
        remaining=max(Decimal("0"),total-paid).quantize(Decimal("0.01"))
        rows.append((r,d,paid.quantize(Decimal("0.01")),remaining))
    account=_central_account()
    legacy_groups={}
    for p in payments:
        d=_data(p)
        if d.get("ticket_entrada_id"): continue
        ticket=str(d.get("ticket","")).strip()
        if not ticket: continue
        k=ticket.casefold()
        if k not in legacy_groups:
            legacy_groups[k]={"ticket":ticket,"persona":d.get("persona",""),"total":Decimal(str(d.get("total","0") or 0)),"pagado":Decimal("0"),"fecha":d.get("fecha","")}
        legacy_groups[k]["pagado"]+=Decimal(str(p.amount or 0))
    legacy_rows=[]
    for p in payments:
        d=_data(p)
        if d.get("ticket_entrada_id") or not str(d.get("ticket","")).strip(): continue
        group=legacy_groups.get(str(d.get("ticket","")).strip().casefold(),{})
        total=Decimal(str(group.get("total",0) or 0))
        paid=Decimal(str(group.get("pagado",0) or 0))
        legacy_rows.append({"id":p.id,"fecha":d.get("fecha",""),"ticket":d.get("ticket",""),"persona":d.get("persona",""),
            "total":str(total),"importe":str(p.amount or 0),"pagado":str(paid),"saldo":str(max(Decimal("0"),total-paid)),
            "estado":"Pagado" if total<=paid else "Historial anterior"})
    payment_history=[]
    for p in payments:
        d=_data(p)
        if local_time(p.created_at).strftime("%Y-%m")!=month: continue
        if q and q not in (p.title+" "+p.data+" "+str(p.amount)).casefold(): continue
        payment_history.append((p,d))
    return _page("Pagos", """
    <section class="card"><h2>Pagos de tickets</h2><p>Seleccioná el importe que se va a pagar. Cada pago descuenta automáticamente el saldo de la cuenta central.</p>{% if account %}<p><b>Saldo disponible de la cuenta central:</b> {{account.currency}} {{account.balance}}</p>{% endif %}
    {% if not account %}<p class="warn">Primero registrá la cuenta central y su saldo inicial.</p>{% endif %}
    <form method="get" class="grid"><div><label>Buscar ticket o proveedor</label><input name="q" value="{{q}}"></div><div><label>Mes del historial</label><input name="mes" type="month" value="{{month}}"></div><div style="align-self:end"><button>Consultar</button><a class="btn" href="{{url_for('pagos_diarios')}}">Limpiar</a></div></form>
    <table><tr><th>Fecha del ticket</th><th>Registrado el</th><th>Ticket</th><th>Proveedor</th><th>Total</th><th>Pagado</th><th>Saldo</th><th>Estado</th><th>Registrar pago</th></tr>
    {% for r,d,paid,remaining in rows %}<tr><td>{{d.get('_display_fecha','')}}</td><td>{{local_time(r.created_at).strftime('%d/%m/%Y %H:%M:%S')}}</td><td>{{d.get('_display_ticket','')}}</td><td>{{d.get('_display_persona','')}}</td><td>{{r.amount or d.get('total','0')}}</td><td>{{paid}}</td><td>{{remaining}}</td><td>{{'Pagado' if remaining==0 else 'Pendiente' if paid==0 else 'Pago parcial'}}</td><td>{% if remaining>0 %}<form method="post" action="{{url_for('pagar_ticket',rid=r.id)}}"><input name="importe" type="number" min="0.01" step="0.01" value="{{remaining}}" required><select name="medio" required><option>Efectivo</option><option>Transferencia</option><option>Cheque</option><option>Tarjeta</option><option>Otro</option></select><input name="comprobante" placeholder="N.º comprobante (opcional)"><button {% if not account %}disabled{% endif %}>Marcar pagado / registrar monto</button></form>{% else %}Pagado{% endif %}</td></tr>{% else %}<tr><td colspan="9">Todavía no hay tickets registrados.</td></tr>{% endfor %}</table></section>
    <section class="card"><h2>Historial de pagos registrados</h2><table><tr><th>Fecha y hora del pago</th><th>Ticket</th><th>Proveedor</th><th>Medio</th><th>Importe pagado</th><th>Estado</th><th>Comprobante</th><th>Acción</th></tr>
    {% for p,d in payment_history %}<tr><td>{{local_time(p.created_at).strftime('%d/%m/%Y %H:%M:%S')}}</td><td>{{d.get('ticket','')}}</td><td>{{d.get('persona','')}}</td><td>{{d.get('medio','')}}</td><td>{{p.amount}}</td><td>{{p.status}}</td><td>{{d.get('comprobante','')}}</td><td><form method="post" action="{{url_for('eliminar_pago_ticket',pid=p.id)}}" onsubmit="return confirm('¿Eliminar este pago y devolver Gs. {{p.amount}} a la cuenta bancaria de origen?');"><button class="danger">Eliminar</button></form></td></tr>{% else %}<tr><td colspan="8">No hay pagos registrados para ese mes.</td></tr>{% endfor %}</table></section>
    <section class="card"><h2>Historial de pagos anteriores</h2><p>Los importes son pagos individuales. Al eliminar uno, se recalcula el saldo del ticket.</p><table><tr><th>Fecha</th><th>Ticket</th><th>Proveedor</th><th>Total ticket</th><th>Este pago</th><th>Total pagado del ticket</th><th>Saldo según registro</th><th>Estado</th><th>Acción</th></tr>
    {% for d in legacy_rows %}<tr><td>{{d.get('fecha','')}}</td><td>{{d.get('ticket','')}}</td><td>{{d.get('persona','')}}</td><td>{{d.get('total','')}}</td><td>{{d.get('importe')}}</td><td>{{d.get('pagado')}}</td><td>{{d.get('saldo')}}</td><td>{{d.get('estado')}}</td><td><form method="post" action="{{url_for('eliminar_pago_ticket',pid=d.id)}}" onsubmit="return confirm('¿Eliminar este pago y devolver el importe a la cuenta bancaria de origen?');"><button class="danger">Eliminar</button></form></td></tr>{% else %}<tr><td colspan="9">No hay pagos anteriores.</td></tr>{% endfor %}</table></section>
    """,rows=rows,legacy_rows=legacy_rows,payment_history=payment_history,q=q,month=month,account=account,local_time=local_time)

def pagar_ticket(rid):
    _can_caja()
    ticket=db.get_or_404(Record,rid)
    if ticket.module not in ("tickets_entrada","tickets"): abort(404)
    try:
        amount=Decimal(request.form.get("importe","").strip().replace(",","."))
        if amount<=0: raise InvalidOperation()
        account=_central_account()
        if not account:
            flash("Primero registrá la cuenta central.")
            return redirect(url_for("pagos_diarios"))
        if amount>Decimal(str(account.balance or 0)):
            flash("Saldo insuficiente en la cuenta central. No se registró el pago.")
            return redirect(url_for("pagos_diarios"))
        data_ticket=_data(ticket)
        if data_ticket.get("en_pagos",True) is False:
            flash("Este ticket queda en el historial, pero su proveedor no está marcado para Pagos en Administrar proveedores.")
            return redirect(url_for("pagos_diarios"))
        ticket_number=str(data_ticket.get("ticket") or data_ticket.get("numero_ticket") or data_ticket.get("nro_ticket") or ("CARGA-"+str(ticket.id))).strip()
        previous=[]
        for p in Record.query.filter_by(module="pagos_diarios").all():
            pd=_data(p)
            if (str(pd.get("ticket_entrada_id",""))==str(ticket.id) or
                str(pd.get("ticket_origen_id",""))==str(ticket.id) or
                str(pd.get("ticket","")).strip().casefold()==ticket_number.casefold()):
                previous.append(p)
        paid=sum((Decimal(str(p.amount or 0)) for p in previous),Decimal("0"))
        total=Decimal(str(ticket.amount or data_ticket.get("total","0") or 0)); remaining=max(Decimal("0"),total-paid)
        person=str(data_ticket.get("persona") or data_ticket.get("cliente") or "")
        data={"ticket":ticket_number,("ticket_entrada_id" if ticket.module=="tickets_entrada" else "ticket_origen_id"):ticket.id,"persona":person,
              "total":str(total),"fecha":datetime.now(ZoneInfo("America/Asuncion")).strftime("%Y-%m-%d"),
              "medio":request.form.get("medio","Efectivo"),"comprobante":request.form.get("comprobante","").strip(),
              "importe":str(amount),"pagado_acumulado":str(paid+amount),"saldo":str(max(Decimal("0"),remaining-amount)),
              "sobrepago":str(max(Decimal("0"),amount-remaining)),"company_account_id":account.id,"cuenta_empresa":account.name or "Cuenta central"}
        pay=Record(module="pagos_diarios",title="Pago ticket "+str(data["ticket"]),data=json.dumps(data,ensure_ascii=False),
                   amount=amount,status="Pagado" if amount>=remaining else "Pago parcial",company_account_id=account.id,created_by=current_user().id)
        db.session.add(pay); db.session.flush(); account.balance-=amount
        ticket.status="Pagado" if amount>=remaining else "Pago parcial"
        data_ticket["saldo"]=str(max(Decimal("0"),remaining-amount)); data_ticket["pagado_acumulado"]=str(paid+amount)
        ticket.data=json.dumps(data_ticket,ensure_ascii=False)
        log_action("descontar pago de cuenta central","pagos_diarios",pay.id,
                   "Ticket "+str(data["ticket"])+"; importe "+str(amount)+"; saldo central "+str(account.balance))
        log_action("registrar pago de ticket",ticket.module,ticket.id,
                   "Pago "+str(amount)+"; saldo ticket "+data_ticket["saldo"])
        db.session.commit()
        flash("Pago registrado. Importe: Gs. "+str(amount)+"; saldo del ticket: Gs. "+data_ticket["saldo"]+"; saldo central: Gs. "+str(account.balance))
    except (InvalidOperation,ValueError,TypeError):
        db.session.rollback(); flash("Ingresá un importe válido mayor que cero.")
    return redirect(url_for("pagos_diarios"))

app.add_url_rule("/registrar-ticket", endpoint="registrar_ticket", view_func=registrar_ticket, methods=["GET","POST"])
app.add_url_rule("/pagos", endpoint="pagos", view_func=pagos_diarios, methods=["GET"])
app.add_url_rule("/pagos/<int:rid>/pagar", endpoint="pagar_ticket", view_func=pagar_ticket, methods=["POST"])
def eliminar_pago_ticket(pid):
    _can_caja()
    payment=db.get_or_404(Record,pid)
    if payment.module!="pagos_diarios": abort(404)
    data=_data(payment)
    amount=Decimal(str(payment.amount or data.get("importe") or 0))
    # Devolver el dinero exactamente a la cuenta que recibió el descuento original.
    account_id=payment.company_account_id or data.get("company_account_id")
    account=db.session.get(CompanyAccount,int(account_id)) if account_id else None
    if not account:
        flash("No se pudo identificar la cuenta bancaria original. No se eliminó el pago ni se modificó el saldo.")
        return redirect(url_for("pagos_diarios"))
    ticket_id=data.get("ticket_entrada_id") or data.get("ticket_origen_id")
    ticket=None
    if ticket_id:
        candidate=db.session.get(Record,int(ticket_id))
        if candidate and candidate.module in ("tickets_entrada","tickets"): ticket=candidate
    if ticket is None:
        ticket_number=str(data.get("ticket","")).strip().casefold()
        for candidate in Record.query.filter(Record.module.in_(["tickets_entrada","tickets"])).all():
            cd=_data(candidate)
            number=str(cd.get("ticket") or cd.get("numero_ticket") or cd.get("nro_ticket") or "").strip().casefold()
            if number and number==ticket_number:
                ticket=candidate
                break
    account.balance=Decimal(str(account.balance or 0))+amount
    if ticket:
        td=_data(ticket)
        ticket_number=str(td.get("ticket") or td.get("numero_ticket") or td.get("nro_ticket") or data.get("ticket","")).strip()
        remaining_payments=[]
        for other in Record.query.filter_by(module="pagos_diarios").all():
            if other.id==payment.id: continue
            od=_data(other)
            linked=(str(od.get("ticket_entrada_id",""))==str(ticket.id) or
                    str(od.get("ticket_origen_id",""))==str(ticket.id) or
                    str(od.get("ticket","")).strip().casefold()==ticket_number.casefold())
            if linked: remaining_payments.append(other)
        paid=sum((Decimal(str(other.amount or 0)) for other in remaining_payments),Decimal("0"))
        total=Decimal(str(ticket.amount or td.get("total","0") or 0))
        balance=max(Decimal("0"),total-paid).quantize(Decimal("0.01"))
        td["saldo"]=str(balance); td["pagado_acumulado"]=str(paid.quantize(Decimal("0.01")))
        td["estado"]="Pagado" if balance==0 else "Pago parcial" if paid>0 else "Pendiente"
        ticket.data=json.dumps(td,ensure_ascii=False)
        ticket.status=td["estado"]
    log_action("eliminar pago y reintegrar cuenta","pagos_diarios",payment.id,
        f"Ticket {data.get('ticket','')}; importe devuelto {amount}; cuenta {account.name or account.id}; saldo cuenta {account.balance}")
    db.session.delete(payment)
    db.session.commit()
    flash("Pago eliminado. Se devolvieron Gs. "+str(amount)+" a "+str(account.name or "la cuenta de origen")+". El saldo del ticket fue recalculado.")
    return redirect(url_for("pagos_diarios"))

app.add_url_rule("/pagos/<int:pid>/eliminar", endpoint="eliminar_pago_ticket", view_func=eliminar_pago_ticket, methods=["POST"])

app.view_functions["pagos_diarios"]=pagos_diarios
