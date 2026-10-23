from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from flask import request
from app import app, Material
from features import _rows, _data, _can_caja, _page

def pagos_diarios_materiales():
    _can_caja()
    records=_rows("pagos_diarios")
    q=request.args.get("q","").strip().casefold()
    month=request.args.get("mes",datetime.now(ZoneInfo("America/Asuncion")).strftime("%Y-%m"))
    today=datetime.now(ZoneInfo("America/Asuncion")).strftime("%Y-%m-%d")
    if q: records=[r for r in records if q in (r.title+" "+r.data).casefold()]
    today_rows=[r for r in records if _data(r).get("fecha",r.created_at.strftime("%Y-%m-%d"))==today]
    history=[r for r in records if _data(r).get("fecha",r.created_at.strftime("%Y-%m-%d"))[:7]==month and _data(r).get("fecha",r.created_at.strftime("%Y-%m-%d"))!=today]
    mats=Material.query.order_by(Material.name).all()
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
    for ticket_data in tickets.values():
        saldo=max(Decimal("0"),Decimal(str(ticket_data["total"]))-ticket_data["pagado"]).quantize(Decimal("0.01"))
        ticket_data["saldo"]=str(saldo)
        ticket_data["pagado"]=str(ticket_data["pagado"].quantize(Decimal("0.01")))
    return _page("Pagos diarios", """
    <section class="card"><h2>Registrar pago diario por ticket</h2><form method="post" action="{{url_for('crear_pago_diario')}}" id="pago-ticket-form">
    <div class="grid"><div><label>N.º de ticket</label><input name="ticket" id="ticket" required></div><div><label>Cliente / proveedor</label><input name="persona" id="persona" list="proveedores-lista" required><datalist id="proveedores-lista">{% for v in vendors %}<option value="{{v.nombre}}">{{v.codigo}}</option>{% endfor %}</datalist></div></div>
    <h3>Materiales</h3><table><tr><th>Material</th><th>Kg</th><th>Precio</th><th>Importe</th><th></th></tr><tbody id="material-lines">
    {% for n in range(2) %}<tr><td><select name="material_id[]" class="material-select"><option value="">Elegir</option>{% for m in mats %}<option value="{{m.id}}">{{m.name}}</option>{% endfor %}</select></td><td><input name="kg[]" class="kg-input" type="number" min="0.001" step="0.001"></td><td><input class="price-input" readonly></td><td><input class="subtotal-input" readonly value="0"></td><td><button type="button" class="remove-line">Quitar</button></td></tr>{% endfor %}</tbody></table>
    <template id="material-row"><tr><td><select name="material_id[]" class="material-select"><option value="">Elegir</option>{% for m in mats %}<option value="{{m.id}}">{{m.name}}</option>{% endfor %}</select></td><td><input name="kg[]" class="kg-input" type="number" min="0.001" step="0.001"></td><td><input class="price-input" readonly></td><td><input class="subtotal-input" readonly value="0"></td><td><button type="button" class="remove-line">Quitar</button></td></tr></template>
    <p><button type="button" id="add-material">Agregar material</button></p><div class="grid"><div><label>Total materiales (Gs.)</label><input name="total" id="total" type="number" step="0.01" readonly value="0"></div><div><label>Pago ahora (Gs.)</label><input name="pago" id="pago" type="number" min="0.01" step="0.01" required></div><div><label>Fecha</label><input name="fecha" type="date" value="{{today}}" required></div><div><label>Medio de pago</label><select name="medio" required><option value="">Elegir</option><option>Efectivo</option><option>Transferencia</option><option>Cheque</option><option>Otro</option></select></div><div><label>Cuenta / referencia</label><input name="cuenta"></div><div><label>Detalle</label><input name="detalle"></div><div><label>N.º de comprobante (opcional)</label><input name="comprobante"></div></div><p><button>Guardar pago</button></p></form></section>
    <section class="card"><h2>Pagos de hoy</h2><table><tr><th>Ticket</th><th>Comprobante</th><th>Cliente</th><th>Total</th><th>Pago</th><th>Saldo</th></tr>{% for r in today_rows %}{% set d=decode(r) %}<tr><td>{{d.get('ticket','')}}</td><td>{{d.get('comprobante','') or '—'}}</td><td>{{d.get('persona','')}}</td><td>{{d.get('total','')}}</td><td>{{r.amount}}</td><td>{{d.get('saldo','')}}</td></tr>{% endfor %}</table></section>
    <section class="card"><h2>Historial de pagos</h2><form class="grid"><div><label>Mes</label><input name="mes" type="month" value="{{month}}"></div><div><label>Buscar</label><input name="q" value="{{q}}"></div><div style="align-self:end"><button>Consultar</button></div></form><table><tr><th>Fecha</th><th>Ticket</th><th>Comprobante</th><th>Cliente</th><th>Total</th><th>Pago</th><th>Saldo</th></tr>{% for r in history %}{% set d=decode(r) %}<tr><td>{{d.get('fecha','')}}</td><td>{{d.get('ticket','')}}</td><td>{{d.get('comprobante','') or '—'}}</td><td>{{d.get('persona','')}}</td><td>{{d.get('total','')}}</td><td>{{r.amount}}</td><td>{{d.get('saldo','')}}</td></tr>{% endfor %}</table></section>
    <script type="application/json" id="pago-vendors">{{vendors|tojson}}</script><script type="application/json" id="pago-materials">{{material_data|tojson}}</script><script type="application/json" id="pago-tickets">{{tickets|tojson}}</script><script src="{{url_for('static',filename='pagos_diarios.js')}}" defer></script>
    """,today_rows=today_rows,history=history,today=today,month=month,q=q,decode=_data,vendors=vendors,mats=mats,material_data=[{"id":m.id,"name":m.name} for m in mats],tickets={k.casefold():v for k,v in tickets.items()})

app.view_functions["pagos_diarios"]=pagos_diarios_materiales
