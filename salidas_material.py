import json
from decimal import Decimal, InvalidOperation
from datetime import datetime
from flask import request, redirect, url_for, flash
from app import app, db, Record, Material, MODULES, current_user, log_action, paraguay_now
from features import _rows, _data, _can_caja, _page

MODULES["salidas_material"] = ("Salida de material", "caja", [])

@app.route("/salidas-material", methods=["GET", "POST"])
def salida_material():
    from app import login_required
    return _salida_material_impl()

@login_required
def _salida_material_impl():
    _can_caja()
    materials=Material.query.order_by(Material.name).all()
    today=paraguay_now().strftime("%Y-%m-%d")
    if request.method=="POST":
        camion=request.form.get("camion","").strip()
        chofer=request.form.get("chofer","").strip()
        fecha=request.form.get("fecha","").strip() or today
        try:
            material_id=int(request.form.get("material_id","0"))
            mat=db.session.get(Material,material_id)
            qty=Decimal(request.form.get("kg","").strip().replace(",","."))
            if not camion or not chofer or not fecha or not mat or not qty.is_finite() or qty<=0:
                raise InvalidOperation()
            stock=Decimal(str(mat.stock or 0))
            if qty>stock:
                flash(f"Stock insuficiente de {mat.name}. Disponible: {stock} kg. No se registró la salida.")
                return redirect(url_for("salida_material"))
            mat.stock=stock-qty
            data={"camion":camion,"chofer":chofer,"fecha":fecha,"material":mat.name,"material_id":mat.id,
                  "kg":str(qty),"cantidad":str(qty),"tipo_movimiento":"salida","origen":"salida_material",
                  "cantidad_disponible":str(mat.stock)}
            rec=Record(module="salidas_material",title=f"Salida de material · {mat.name} · {camion}",
                       data=json.dumps(data,ensure_ascii=False),amount=0,status="Registrado",
                       created_by=current_user().id)
            db.session.add(rec); db.session.flush()
            inv=Record(module="inventario",title=f"Salida de material · {mat.name} · {camion}",
                       data=json.dumps(data,ensure_ascii=False),amount=0,status="Salida de Caja",
                       created_by=current_user().id)
            db.session.add(inv); db.session.flush()
            log_action("salida de material desde Caja","salidas_material",rec.id,
                       f"Camión {camion}; chofer {chofer}; fecha {fecha}; {mat.name}: -{qty} kg; stock {mat.stock}")
            db.session.commit()
            flash(f"Salida registrada. Se descontaron {qty} kg de {mat.name}.")
            return redirect(url_for("salida_material"))
        except (InvalidOperation,ValueError,TypeError):
            db.session.rollback()
            flash("Completá camión, chofer, fecha, material y una cantidad válida en kg.")
            return redirect(url_for("salida_material"))
    rows=[]
    for rec in _rows("salidas_material"):
        rows.append((rec,_data(rec)))
    return _page("Salida de material", """
    <section class="card"><h2>Registrar salida de material</h2>
    <form method="post" class="grid">
      <div><label>Camión</label><input name="camion" required></div>
      <div><label>Chofer</label><input name="chofer" required></div>
      <div><label>Fecha</label><input type="date" name="fecha" value="{{today}}" required></div>
      <div><label>Material</label><select name="material_id" required><option value="">Seleccionar material</option>{% for m in materials %}<option value="{{m.id}}">{{m.name}} · stock {{m.stock}} kg</option>{% endfor %}</select></div>
      <div><label>Cantidad (kg)</label><input name="kg" type="number" min="0.001" step="0.001" required></div>
      <div style="align-self:end"><button type="submit">Registrar salida</button></div>
    </form></section>
    <section class="card"><h2>Historial de salidas de material</h2><button type="button" onclick="window.print()">Imprimir historial</button>
    <div style="overflow-x:auto"><table><tr><th>Fecha y hora de registro</th><th>Fecha de salida</th><th>Camión</th><th>Chofer</th><th>Material</th><th>Kg</th><th>Stock resultante</th></tr>
    {% for r,d in rows %}<tr><td>{{r.created_at.strftime('%d/%m/%Y %H:%M')}}</td><td>{{d.get('fecha','')}}</td><td>{{d.get('camion','')}}</td><td>{{d.get('chofer','')}}</td><td>{{d.get('material','')}}</td><td>{{d.get('kg','')}}</td><td>{{d.get('cantidad_disponible','')}}</td></tr>{% else %}<tr><td colspan="7">Todavía no hay salidas registradas.</td></tr>{% endfor %}</table></div></section>
    """,today=today,materials=materials,rows=rows)

# Aplicar login_required explícitamente a la vista registrada.
app.view_functions["salida_material"] = login_required(_salida_material_impl)
