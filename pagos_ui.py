from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from flask import request
from app import app, db, Record, Material, CompanyAccount, local_time
from features import _rows, _data, _can_caja, _page

def pagos_diarios_materiales():
    _can_caja()
    records=_rows("pagos_diarios")
    q=request.args.get("q","").strip().casefold()
    month=request.args.get("mes",datetime.now(ZoneInfo("America/Asuncion")).strftime("%Y-%m"))
    today=datetime.now(ZoneInfo("America/Asuncion")).strftime("%Y-%m-%d")
    if q: records=[r for r in records if q in (r.title+" "+r.data).casefold()]
    today_rows=[r for r in records if _data(r).get("fecha",local_time(r.created_at).strftime("%Y-%m-%d"))==today]
    history=[r for r in records if _data(r).get("fecha",local_time(r.created_at).strftime("%Y-%m-%d"))[:7]==month and _data(r).get("fecha",local_time(r.created_at).strftime("%Y-%m-%d"))!=today]
    source_tickets=Record.query.filter_by(module="tickets").order_by(Record.created_at.desc()).all()
    source_rows=[]
    payment_rows=_rows("pagos_diarios")
    for source in source_tickets:
        sd=_data(source)
        source_number=str(sd.get("numero_ticket") or sd.get("nro_ticket") or ("CARGA-"+str(source.id))).strip()
        # Vincular pagos tanto por ID de carga como por número de ticket.
        # Se recorre cada pago una sola vez para evitar duplicar importes.
        paid=Decimal("0")
        for payment_row in payment_rows:
            pd=_data(payment_row)
            linked_by_id=str(pd.get("ticket_origen_id",""))==str(source.id)
            linked_by_number=str(pd.get("ticket","")).strip().casefold()==source_number.casefold()
            if linked_by_id or linked_by_number:
                paid+=Decimal(str(pd.get("importe",payment_row.amount or 0) or payment_row.amount or 0))
        total=Decimal(str(source.amount or sd.get("total","0") or 0))
        remaining=max(Decimal("0"),total-paid).quantize(Decimal("0.01"))
        # Mostrar todas las cargas registradas; las pagadas quedan visibles sin permitir otro pago.
        source_rows.append({"record":source,"data":sd,"paid":paid.quantize(Decimal("0.01")),"remaining":remaining})
    mats=Material.query.order_by(Material.name).all()
    accounts=CompanyAccount.query.filter_by(active=True).order_by(CompanyAccount.name).all()
    vendors=[]
    for row in _rows("proveedores"):
        d=_data(row)
        if d.get("nombre"):
            prices={}
            for m in mats:
                p=d.get("precios_materiales",{}).get(str(m.id))
                if p in (None,""): p=m.wholesale_price if m.wholesale_price is not None else m.price
                prices[str(m.id)]=str(p or 0)
            vendors.append({"nombre":d["nombre"],"codigo":d.get("codigo",""),"precios":prices})
    tickets={}
    for r in _rows("pagos_diarios"):
        d=_data(r); t=str(d.get("ticket","")).strip()
        if not t: continue
        key=t.casefold()
        if key not in tickets:
            try: total_ticket=Decimal(str(d.get("total","0") or 0))
            except Exception: total_ticket=Decimal("0")
            tickets[key]={"persona":d.get("persona",""),"total":str(total_ticket),"materiales":d.get("materiales",[]),"pagado":Decimal("0"),"saldo":str(total_ticket)}
        tickets[key]["pagado"] += Decimal(str(r.amount or 0))
    # Cargas ya registradas: permitir seleccionarlas por su número de ticket en Caja.
    for source in source_tickets:
        sd=_data(source)
        t=str(sd.get("numero_ticket",sd.get("nro_ticket","CARGA-"+str(source.id))).strip() or "CARGA-"+str(source.id))
        key=t.casefold()
        if key not in tickets:
            lines=[]
            for line in (sd.get("materiales",[]) or []):
                material_name=str(line.get("material","")).strip()
                mat=next((m for m in mats if m.name.casefold()==material_name.casefold()),None)
                lines.append({"material_id":mat.id if mat else "", "kg":str(line.get("cantidad",line.get("kg",""))), "material":material_name})
            paid=sum((Decimal(str(_data(p).get("importe",p.amount or 0) or p.amount or 0)) for p in _rows("pagos_diarios") if str(_data(p).get("ticket_origen_id",""))==str(source.id)),Decimal("0"))
            total=Decimal(str(source.amount or sd.get("total","0") or 0))
            tickets[key]={"persona":sd.get("cliente",""),"total":str(total),"materiales":lines,"pagado":paid,"saldo":str(max(Decimal("0"),total-paid))}
        tickets.setdefault(("CARGA-"+str(source.id)).casefold(),tickets[key])
    for ticket_data in tickets.values():
        saldo=max(Decimal("0"),Decimal(str(ticket_data["total"]))-ticket_data["pagado"]).quantize(Decimal("0.01"))
        ticket_data["saldo"]=str(saldo)
        ticket_data["pagado"]=str(ticket_data["pagado"].quantize(Decimal("0.01")))
    return _page("Pagos diarios", """
    <section class="card"><h2>Cargas registradas pendientes de pago</h2>
    <p>Estas son las cargas que ya guardaste en Registrar carga. Podés registrar un pago total o parcial sin volver a cargar los materiales.</p>
    <div style="overflow-x:auto"><table><tr><th>Fecha de carga</th><th>N.º de carga</th><th>Proveedor</th><th>Materiales</th><th>Total</th><th>Pagado</th><th>Saldo pendiente</th><th>Agregar pago</th></tr>
    {% for item in source_rows %}{% set source=item.record %}{% set sd=item.data %}<tr><td>{{local_time(source.created_at).strftime('%d/%m/%Y %H:%M')}}</td><td>{{sd.get("numero_ticket",sd.get("nro_ticket","CARGA-" ~ source.id))}}</td><td>{{sd.get('cliente','')}}</td><td>{% for line in sd.get('materiales',[]) %}{{line.get('material','')}} · {{line.get('cantidad','')}} kg<br>{% endfor %}</td><td>{{source.amount}}</td><td>{{item.paid}}</td><td>{{item.remaining}}</td><td>{% if item.remaining > 0 %}<form method="post" action="{{url_for('crear_pago_diario')}}" class="grid">
    <input type="hidden" name="source_ticket_id" value="{{source.id}}"><input type="hidden" name="ticket" value="{{sd.get("numero_ticket") or sd.get("nro_ticket") or ("CARGA-" ~ source.id)}}"><input type="hidden" name="persona" value="{{sd.get('cliente','')}}"><input type="hidden" name="total" value="{{source.amount or sd.get('total','0')}}">
    <div><label>Importe a pagar (Gs.)</label><input name="pago" type="number" min="0.01" max="{{item.remaining}}" step="0.01" value="{{item.remaining}}" required></div>
    <div><label>Comprobante (opcional)</label><input name="comprobante" placeholder="N.º de comprobante"></div>
    <div><label>Fecha</label><input name="fecha" type="date" value="{{today}}" required></div>
    <div><label>Medio</label><select name="medio" required><option value="">Elegir</option><option>Efectivo</option><option>Transferencia</option><option>Cheque</option><option>Otro</option></select></div>
    <div><label>Cuenta bancaria (si corresponde)</label><select name="account_id"><option value="">Sin cuenta bancaria</option>{% for a in accounts %}<option value="{{a.id}}">{{a.name}} · {{a.currency}}</option>{% endfor %}</select></div>
    <div style="align-self:end"><button>Agregar pago</button></div></form>{% else %}<strong>Pagado</strong>{% endif %}</td></tr>{% else %}<tr><td colspan="8">No hay cargas pendientes de pago.</td></tr>{% endfor %}</table></div></section>
    <section class="card"><h2>Registrar pago diario por ticket</h2><form method="post" action="{{url_for('crear_pago_diario')}}" id="pago-ticket-form">
    <div class="grid"><div><label>N.º de ticket</label><input name="ticket" id="ticket" list="cargas-ticket-list" placeholder="Ingresá el N.º exacto del ticket" autocomplete="off" required><datalist id="cargas-ticket-list">{% for item in source_rows %}<option value="{{item.data.get("numero_ticket",item.data.get("nro_ticket","CARGA-" ~ item.record.id))}}">{{item.data.get("cliente","")}} · Saldo Gs. {{item.remaining}}</option>{% endfor %}</datalist><small>Si es una carga ya registrada, elegila de la lista para asociar el pago.</small></div><div><label>Proveedor</label><input name="persona" id="persona" list="proveedores-lista" required><datalist id="proveedores-lista">{% for v in vendors %}<option value="{{v.nombre}}">{{v.codigo}}</option>{% endfor %}</datalist></div></div>
    <h3>Materiales</h3><table><tr><th>Material</th><th>Kg</th><th>Precio</th><th>Importe</th><th></th></tr><tbody id="material-lines">
    {% for n in range(2) %}<tr><td><select name="material_id[]" class="material-select"><option value="">Elegir</option>{% for m in mats %}<option value="{{m.id}}">{{m.name}}</option>{% endfor %}</select></td><td><input name="kg[]" class="kg-input" type="number" min="0.001" step="0.001"></td><td><input class="price-input" readonly></td><td><input class="subtotal-input" readonly value="0"></td><td><button type="button" class="remove-line">Quitar</button></td></tr>{% endfor %}</tbody></table>
    <template id="material-row"><tr><td><select name="material_id[]" class="material-select"><option value="">Elegir</option>{% for m in mats %}<option value="{{m.id}}">{{m.name}}</option>{% endfor %}</select></td><td><input name="kg[]" class="kg-input" type="number" min="0.001" step="0.001"></td><td><input class="price-input" readonly></td><td><input class="subtotal-input" readonly value="0"></td><td><button type="button" class="remove-line">Quitar</button></td></tr></template>
    <p><button type="button" id="add-material">Agregar material</button></p><div class="grid"><div><label>Total materiales (Gs.)</label><input name="total" id="total" type="number" step="0.01" readonly value="0"></div><div><label>Pago ahora (Gs.)</label><input name="pago" id="pago" type="number" min="0.01" step="0.01" required></div><div><label>Fecha</label><input name="fecha" type="date" value="{{today}}" required></div><div><label>Medio de pago</label><select name="medio" required><option value="">Elegir</option><option>Efectivo</option><option>Transferencia</option><option>Cheque</option><option>Otro</option></select></div><div><label>Cuenta bancaria (si corresponde)</label><select name="account_id"><option value="">Sin cuenta bancaria</option>{% for a in accounts %}<option value="{{a.id}}">{{a.name}} · {{a.currency}} · saldo {{a.balance}}</option>{% endfor %}</select></div><div><label>Cuenta / referencia</label><input name="cuenta"></div><div><label>Detalle</label><input name="detalle"></div><div><label>N.º de comprobante (opcional)</label><input name="comprobante"></div></div><p><button>Guardar pago</button></p></form></section>

    <section class="card"><h2>Pagos de hoy</h2><table><tr><th>Fecha y hora de registro</th><th>Ticket</th><th>Comprobante</th><th>Proveedor</th><th>Total</th><th>Pago</th><th>Saldo</th></tr>{% for r in today_rows %}{% set d=decode(r) %}<tr><td>{{local_time(r.created_at).strftime('%d/%m/%Y %H:%M:%S')}}</td><td>{{d.get('ticket','')}}</td><td>{{d.get('comprobante','') or '—'}}</td><td>{{d.get('persona','')}}</td><td>{{d.get('total','')}}</td><td>{{r.amount}}</td><td>{{d.get('saldo','')}}</td></tr>{% endfor %}</table></section>
    <section class="card"><h2>Historial de pagos</h2><form class="grid"><div><label>Mes</label><input name="mes" type="month" value="{{month}}"></div><div><label>Buscar</label><input name="q" value="{{q}}"></div><div style="align-self:end"><button>Consultar</button></div></form><table><tr><th>Fecha y hora de registro</th><th>Fecha del pago</th><th>Ticket</th><th>Comprobante</th><th>Proveedor</th><th>Total</th><th>Pago</th><th>Saldo</th></tr>{% for r in history %}{% set d=decode(r) %}<tr><td>{{local_time(r.created_at).strftime('%d/%m/%Y %H:%M:%S')}}</td><td>{{d.get('fecha','')}}</td><td>{{d.get('ticket','')}}</td><td>{{d.get('comprobante','') or '—'}}</td><td>{{d.get('persona','')}}</td><td>{{d.get('total','')}}</td><td>{{r.amount}}</td><td>{{d.get('saldo','')}}</td></tr>{% endfor %}</table></section>
    <script type="application/json" id="pago-vendors">{{vendors|tojson}}</script><script type="application/json" id="pago-materials">{{material_data|tojson}}</script><script type="application/json" id="pago-tickets">{{tickets|tojson}}</script><script src="{{url_for('static',filename='pagos_diarios.js')}}" defer></script>
    """,today_rows=today_rows,history=history,today=today,month=month,q=q,decode=_data,local_time=local_time,vendors=vendors,mats=mats,material_data=[{"id":m.id,"name":m.name} for m in mats],tickets={k.casefold():v for k,v in tickets.items()},accounts=accounts,source_rows=source_rows)

app.view_functions["pagos_diarios"]=pagos_diarios_materiales
