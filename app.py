import os
from datetime import datetime
from flask import Flask, render_template_string

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "cambiar-en-produccion")

PAGE = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Freddy Rojas | Gestión</title>
  <style>
    :root { font-family: system-ui, Arial, sans-serif; color: #17202a; background: #f4f6f8; }
    body { margin: 0; }
    header { background: #173b57; color: white; padding: 22px 18px; }
    main { max-width: 980px; margin: 24px auto; padding: 0 16px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(210px,1fr)); gap: 14px; }
    .card { background: white; padding: 18px; border-radius: 12px; box-shadow: 0 2px 9px #0000000c; }
    h1 { margin: 0 0 5px; font-size: 1.45rem; } h2 { font-size: 1.05rem; margin-top: 0; }
    .muted { color: #596773; } .status { display: inline-block; padding: 5px 9px; border-radius: 20px; background: #e5f4e8; color: #216e39; font-size: .85rem; }
    footer { text-align:center; color:#667; padding:24px; font-size:.85rem; }
  </style>
</head>
<body>
<header><h1>Freddy Rojas</h1><div>Gestión del negocio · Sistema independiente</div></header>
<main>
  <section class="card" style="margin-bottom:16px">
    <span class="status">Aplicación inicial activa</span>
    <p class="muted">Base de trabajo creada. Los módulos operativos y los permisos se implementarán antes de usar datos reales.</p>
    <small>Hora del servidor: {{ now }}</small>
  </section>
  <section class="grid">
    <article class="card"><h2>Administración</h2><p class="muted">Usuarios, áreas, permisos y precios.</p></article>
    <article class="card"><h2>Caja</h2><p class="muted">Tickets de entrada y solicitudes de pago.</p></article>
    <article class="card"><h2>Tesorería</h2><p class="muted">Cuentas, movimientos y pagos ejecutados.</p></article>
    <article class="card"><h2>Inventario y ventas</h2><p class="muted">Compras, ventas, stock y salidas.</p></article>
    <article class="card"><h2>Combustible y gomería</h2><p class="muted">Cargas por camión y repuestos.</p></article>
    <article class="card"><h2>Auditoría</h2><p class="muted">Revisión de comprobantes y trazabilidad.</p></article>
  </section>
</main>
<footer>Freddy Rojas · Entorno inicial · No ingresar información financiera real todavía</footer>
</body>
</html>
"""

@app.get("/")
def index():
    return render_template_string(PAGE, now=datetime.now().strftime("%d/%m/%Y %H:%M"))

@app.get("/health")
def health():
    return {"status": "ok", "app": "freddy-rojas"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
