import json
from decimal import Decimal, InvalidOperation
from flask import request, redirect, url_for, flash
from app import app, db, Record, Material, CompanyAccount, current_user, log_action
from features import _rows, _data, _can_caja

def crear_pago_diario_materiales():
    _can_caja()
    source_ticket_id=request.form.get("source_ticket_id","").strip()
    ticket=request.form.get("ticket","").strip()
    source_record=None
    source_data={}
    if source_ticket_id:
        try:
            source_record=db.session.get(Record,int(source_ticket_id))
        except (ValueError,TypeError):
            source_record=None
    elif ticket.casefold().startswith("carga-"):
        try:
            source_record=db.session.get(Record,int(ticket.split("-",1)[1]))
        except (ValueError,TypeError):
            source_record=None
    else:
        # Permite vincular también por el número de ticket que figure en una carga,
        # si ese número fue guardado en el registro de origen.
        for candidate in Record.query.filter_by(module="tickets").all():
            candidate_data=_data(candidate)
            candidate_number=str(candidate_data.get("numero_ticket",candidate_data.get("nro_ticket",""))).strip()
            if candidate_number and candidate_number.casefold()==ticket.casefold():
                source_record=candidate
                break
    if source_ticket_id or ticket.casefold().startswith("carga-") or source_record:
        if not source_record or source_record.module!="tickets":
            flash("No se encontró la carga registrada con ese número de ticket. No se guardó el pago.")
            return redirect(url_for("pagos_diarios"))
        source_data=_data(source_record)
        ticket=str(source_data.get("numero_ticket") or source_data.get("nro_ticket") or ("CARGA-"+str(source_record.id))).strip()
        persona=str(source_data.get("cliente","")).strip()
    else:
        persona=request.form.get("persona","").strip()
    comp=request.form.get("comprobante","").strip()
    fecha=request.form.get("fecha","").strip()
    medio=request.form.get("medio","").strip()
    if not ticket or not persona or not fecha or not medio:
        flash("Completá el ticket, cliente/proveedor, fecha y medio de pago.")
        return redirect(url_for("pagos_diarios"))
    previous=[r for r in _rows("pagos_diarios") if _data(r).get("ticket","").casefold()==ticket.casefold()]
    first=_data(previous[0]) if previous else {}
    existing=bool(previous)
    if existing and first.get("persona","").strip().casefold()!=persona.casefold():
        flash("Ese ticket ya pertenece a otro cliente/proveedor.")
        return redirect(url_for("pagos_diarios"))
    try:
        if source_record:
            lines=source_data.get("materiales",[])
            total=Decimal(str(source_record.amount or source_data.get("total","0") or 0))
        elif existing:
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
        account=None
        account_id=request.form.get("account_id","").strip()
        if medio in ("Transferencia","Cheque") and not account_id:
            flash("Seleccioná la cuenta bancaria desde la que se realiza la transferencia o el cheque.")
            return redirect(url_for("pagos_diarios"))
        if account_id:
            try: account=db.session.get(CompanyAccount,int(account_id))
            except (ValueError,TypeError): account=None
            if not account or not account.active:
                raise InvalidOperation()
        data={"ticket":ticket,"comprobante":comp,"persona":persona,"materiales":lines,"total":str(total),"fecha":fecha,
              "medio":medio,"cuenta":request.form.get("cuenta","").strip(),"cuenta_empresa":account.name if account else "",
              "company_account_id":account.id if account else None,"detalle":request.form.get("detalle","").strip(),
              "pagado_acumulado":str(paid+amount),"saldo":str(balance)}
        if source_record:
            data["ticket_origen_id"]=source_record.id
        payment=Record(module="pagos_diarios",title="Pago ticket "+ticket,data=json.dumps(data,ensure_ascii=False),
            amount=amount,status="Pagado" if balance==0 else "Pago parcial",company_account_id=account.id if account else None,created_by=current_user().id)
        db.session.add(payment)
        if account: account.balance-=amount
        db.session.flush()
        if account:
            log_action("descontar pago de cuenta bancaria","pagos_diarios",payment.id,
                "Cuenta "+account.name+"; ticket "+ticket+"; importe descontado "+str(amount)+"; saldo bancario "+str(account.balance))
        log_action("registrar pago diario","pagos_diarios",payment.id,"Ticket "+ticket+"; "+persona+"; pago "+str(amount))
        if not existing and not source_record:
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
