import json
from decimal import Decimal, InvalidOperation
from flask import request, abort, render_template_string
from app import app, Record, Material, allowed, BASE
from features import _rows, _data, _record_date

def materials_report():
    if not allowed("informe_materiales"):
        abort(403)
    q=request.args.get("q","").strip().casefold()
    since=request.args.get("desde","")
    until=request.args.get("hasta","")
    materials=Material.query.order_by(Material.name).all()
    entries=[]
    exits=[]
    totals={}
    ticket_inventory_ids=set()
    for rec in _rows("inventario"):
        d=_data(rec)
        if d.get("registro_ticket_id") not in (None,""):
            ticket_inventory_ids.add(str(d.get("registro_ticket_id")))
        name=str(d.get("material") or d.get("nombre_material") or rec.title).strip()
        try: qty=Decimal(str(d.get("cantidad_ingresada",d.get("cantidad",0)) or 0))
        except InvalidOperation: qty=Decimal("0")
        if qty<=0: continue
        date=str(d.get("fecha") or rec.created_at.strftime("%Y-%m-%d"))[:10]
        entries.append({"fecha":date,"tipo":"Entrada","material":name,"cantidad":qty,"ref":d.get("ticket","Inventario manual"),"persona":d.get("proveedor",""),"record":rec})
        mat=next((m for m in materials if m.name.casefold()==name.casefold()),None)
        key=str(mat.id) if mat else name.casefold()
        totals.setdefault(key,{"name":name,"entrada":Decimal("0"),"salida":Decimal("0")})
        totals[key]["entrada"]+=qty
    # Respaldo para tickets de entrada históricos que no tengan movimiento de inventario asociado.
    # Los tickets que ya generaron sus movimientos no se duplican en este informe.
    for ticket_rec in _rows("tickets_entrada"):
        if str(ticket_rec.id) in ticket_inventory_ids:
            continue
        td=_data(ticket_rec)
        ticket_number=str(td.get("ticket") or ("CARGA-"+str(ticket_rec.id)))
        provider=str(td.get("persona") or td.get("proveedor") or "")
        date=str(td.get("fecha") or ticket_rec.created_at.strftime("%Y-%m-%d"))[:10]
        for line in td.get("materiales",[]) or []:
            name=str(line.get("material") or line.get("nombre_material") or "").strip()
            try: qty=Decimal(str(line.get("kg",line.get("cantidad",0)) or 0))
            except (InvalidOperation,ValueError,TypeError): qty=Decimal("0")
            if not name or qty<=0:
                continue
            fallback_row={"fecha":date,"tipo":"Entrada","material":name,"cantidad":qty,"ref":ticket_number,"persona":provider,"record":ticket_rec}
            entries.append(fallback_row)
            mat=next((item for item in materials if item.name.casefold()==name.casefold()),None)
            key=str(mat.id) if mat else name.casefold()
            totals.setdefault(key,{"name":name,"entrada":Decimal("0"),"salida":Decimal("0")})
            totals[key]["entrada"]+=qty
    for rec in _rows("ventas"):
        d=_data(rec)
        name=str(d.get("material") or d.get("nombre_material") or "").strip()
        try: qty=Decimal(str(d.get("cantidad",d.get("kg",0)) or 0))
        except InvalidOperation: qty=Decimal("0")
        if not name or qty<=0: continue
        date=str(d.get("fecha") or rec.created_at.strftime("%Y-%m-%d"))[:10]
        exits.append({"fecha":date,"tipo":"Salida","material":name,"cantidad":qty,"ref":d.get("destino","Venta"),"persona":d.get("chofer",""),"record":rec})
        mat=next((m for m in materials if m.name.casefold()==name.casefold()),None)
        key=str(mat.id) if mat else name.casefold()
        totals.setdefault(key,{"name":name,"entrada":Decimal("0"),"salida":Decimal("0")})
        totals[key]["salida"]+=qty
    for m in materials:
        totals.setdefault(str(m.id),{"name":m.name,"entrada":Decimal("0"),"salida":Decimal("0")})
        totals[str(m.id)]["stock"]=Decimal(str(m.stock or 0))
    rows=sorted(entries+exits,key=lambda x:(x["fecha"],x["record"].created_at),reverse=True)
    if since: rows=[x for x in rows if x["fecha"]>=since]
    if until: rows=[x for x in rows if x["fecha"]<=until]
    if q: rows=[x for x in rows if q in (x["material"]+" "+x["tipo"]+" "+str(x["ref"])+" "+str(x["persona"])).casefold()]
    summary=[]
    for x in totals.values():
        x["neto"]=x["entrada"]-x["salida"]
        if not q or q in x["name"].casefold(): summary.append(x)
    summary.sort(key=lambda x:x["name"].casefold())
    return render_template_string(BASE+"""
    <section class="card"><h2>Informe de materiales · Entradas y salidas</h2>
    <p>Las entradas se suman desde el historial de inventario y los pagos por ticket. Las salidas de ventas se descuentan automáticamente del saldo calculado.</p>
    <form method="get" class="grid"><div><label>Buscar material, ticket, destino o proveedor</label><input name="q" value="{{q}}"></div><div><label>Desde</label><input type="date" name="desde" value="{{since}}"></div><div><label>Hasta</label><input type="date" name="hasta" value="{{until}}"></div><div style="align-self:end"><button>Consultar</button></div></form>
    <p><button type="button" onclick="window.print()">Imprimir informe</button></p>
    <h3>Saldo acumulado por material</h3><div style="overflow-x:auto"><table><tr><th>Material</th><th>Entradas kg</th><th>Salidas kg</th><th>Saldo calculado kg</th><th>Stock actual</th></tr>
    {% for x in summary %}<tr><td>{{x.name}}</td><td>{{x.entrada}}</td><td>{{x.salida}}</td><td><b>{{x.neto}}</b></td><td>{{x.get('stock','—')}}</td></tr>{% else %}<tr><td colspan="5">Todavía no hay movimientos.</td></tr>{% endfor %}</table></div>
    <h3 style="margin-top:24px">Historial de movimientos</h3><div style="overflow-x:auto"><table><tr><th>Fecha</th><th>Tipo</th><th>Material</th><th>Cantidad kg</th><th>Ticket / destino</th><th>Proveedor / responsable</th><th>Registro</th></tr>
    {% for x in rows %}<tr><td>{{x.fecha}}</td><td>{{x.tipo}}</td><td>{{x.material}}</td><td>{{x.cantidad}}</td><td>{{x.ref}}</td><td>{{x.persona}}</td><td>{{x.record.title}}</td></tr>{% else %}<tr><td colspan="7">No hay movimientos para estos filtros.</td></tr>{% endfor %}</table></div></section></main><footer>Freddy Rojas · Informe de materiales</footer></body></html>
    """,title="Informe de materiales",q=q,since=since,until=until,summary=summary,rows=rows)

_original_report=app.view_functions["report_module"]
def report_module_materials(module):
    if module=="informe_materiales":
        return materials_report()
    return _original_report(module)
app.view_functions["report_module"]=report_module_materials
