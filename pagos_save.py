import json
from decimal import Decimal, InvalidOperation
from flask import request, redirect, url_for, flash
from app import app, db, Record, Material, current_user, log_action
from features import _rows, _data, _can_caja

def crear_pago_diario_materiales():
    _can_caja()
    ticket=request.form.get("ticket","").strip()
    comp=request.form.get("comprobante","").strip()
    persona=request.form.get("persona","").strip()
    fecha=request.form.get("fecha","").strip()
    medio=request.form.get("medio","").strip()
    if not ticket or not persona or not fecha or not medio:
        flash("Completá el número de ticket, cliente/proveedor, fecha y medio de pago.")
        return redirect(url_for("pagos_diarios"))
    previous=[r for r in _rows("pagos_diarios") if _data(r).get("ticket","").casefold()==ticket.casefold()]
    first=_data(previous[0]) if previous else {}
    existing=bool(previous)
    if existing and first.get("persona","").strip().casefold()!=persona.casefold():
        flash("Ese ticket ya pertenece a otro cliente/proveedor.")
        return redirect(url_for("pagos_diarios"))
    try:
        if existing:
            lines=first.get("materiales",[])
            total=Decimal(str(first.get("total","0")))
        else:
            ids=request.form.getlist("material_id[]")
            quantities=request.form.getlist("kg[]")
            vendor=next((_data(r) for r in _rows("proveedores") if _data(r).get("nombre","").strip().casefold()==persona.casefold()),None)
            if not vendor or len(ids)!=len(quantities): raise InvalidOperation()
            lines=[]; total=Decimal("0")
            for mid,raw in zip(ids,quantities):
                mid=mid.strip(); raw=raw.strip().replace(",",".")
                if not mid and not raw: continue
                if not mid or not raw: raise InvalidOperation()
                mat=db.session.get(Material,int(mid)); kg=Decimal(raw)
                if not mat or kg<=0: raise InvalidOperation()
                price=vendor.get("precios_materiales",{}).get(str(mat.id))
                if price in (None,""):
                    price=mat.wholesale_price if mat.wholesale_price is not None else mat.price
                price=Decimal(str(price or 0))
                if price<=0:
                    flash("Configurá primero el precio de "+mat.name+" para ese proveedor.")
                    return redirect(url_for("pagos_diarios"))
                subtotal=(kg*price).quantize(Decimal("0.01"))
                lines.append({"material_id":mat.id,"material":mat.name,"kg":str(kg),"precio_unitario":str(price),"importe":str(subtotal)})
                total+=subtotal
            total=total.quantize(Decimal("0.01"))
            if not lines or total<=0: raise InvalidOperation()
        if comp and any(_data(r).get("comprobante","").casefold()==comp.casefold() for r in _rows("pagos_diarios")):
            flash("Ese comprobante ya está registrado. Usá otro o dejalo vacío.")
            return redirect(url_for("pagos_diarios"))
        amount=Decimal(request.form.get("pago","").replace(",","."))
        paid=sum((Decimal(str(r.amount or 0)) for r in previous),Decimal("0"))
        if amount<=0 or paid+amount>total: raise InvalidOperation()
        balance=(total-paid-amount).quantize(Decimal("0.01"))
        data={"ticket":ticket,"comprobante":comp,"persona":persona,"materiales":lines,"total":str(total),"fecha":fecha,
              "medio":medio,"cuenta":request.form.get("cuenta","").strip(),"detalle":request.form.get("detalle","").strip(),
              "pagado_acumulado":str(paid+amount),"saldo":str(balance)}
        payment=Record(module="pagos_diarios",title="Pago ticket "+ticket,data=json.dumps(data,ensure_ascii=False),
            amount=amount,status="Pagado" if balance==0 else "Pago parcial",created_by=current_user().id)
        db.session.add(payment); db.session.flush()
        log_action("registrar pago diario","pagos_diarios",payment.id,"Ticket "+ticket+"; "+persona+"; pago "+str(amount))
        if not existing:
            for line in lines:
                mat=db.session.get(Material,int(line["material_id"]))
                kg=Decimal(str(line["kg"]))
                mat.stock+=kg
                invdata={"material":mat.name,"material_id":mat.id,"cantidad_ingresada":str(kg),
                    "cantidad_disponible":str(mat.stock),"origen":"pago_diario","ticket":ticket,"proveedor":persona,
                    "precio_unitario":line["precio_unitario"],"importe":line["importe"],"fecha":fecha,"registro_pago_id":payment.id}
                inv=Record(module="inventario",title="Entrada de material · "+mat.name+" · Ticket "+ticket,
                    data=json.dumps(invdata,ensure_ascii=False),amount=Decimal(str(line["importe"])),
                    status="Entrada de pago diario",created_by=current_user().id)
                db.session.add(inv); db.session.flush()
                log_action("entrada de material por pago diario","inventario",inv.id,
                    "Ticket "+ticket+"; "+mat.name+": +"+str(kg)+" kg; stock "+str(mat.stock))
        db.session.commit()
        flash("Pago registrado. Total: Gs. "+str(total)+"; saldo pendiente: Gs. "+str(balance)+
              (". Materiales agregados al inventario." if not existing else ". No se duplicó la entrada de materiales."))
    except (InvalidOperation,ValueError,TypeError):
        db.session.rollback()
        flash("Revisá los materiales, los kg y el importe. El pago no puede superar el saldo del ticket.")
    return redirect(url_for("pagos_diarios"))

app.view_functions["crear_pago_diario"]=crear_pago_diario_materiales
