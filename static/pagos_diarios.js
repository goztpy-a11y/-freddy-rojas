document.addEventListener("DOMContentLoaded", function () {
  const form = document.getElementById("pago-ticket-form");
  if (!form) return;
  const vendors = JSON.parse(document.getElementById("pago-vendors").textContent || "[]");
  const materials = JSON.parse(document.getElementById("pago-materials").textContent || "[]");
  const tickets = JSON.parse(document.getElementById("pago-tickets").textContent || "{}");
  const person = document.getElementById("persona");
  const ticket = document.getElementById("ticket");
  const rows = document.getElementById("material-lines");
  const template = document.getElementById("material-row");
  const total = document.getElementById("total");
  const paid = document.getElementById("pago");
  const vendor = () => vendors.find(v => v.nombre.toLowerCase() === person.value.trim().toLowerCase());
  const fmt = n => (Number(n) || 0).toFixed(2);
  function recalc() {
    let sum = 0, v = vendor();
    rows.querySelectorAll("tr").forEach(row => {
      const sel = row.querySelector(".material-select"), kg = Number(row.querySelector(".kg-input").value || 0);
      const m = materials.find(x => String(x.id) === sel.value);
      const p = v && m ? Number(v.precios[String(m.id)] || 0) : 0;
      const sub = Math.round(kg * p * 100) / 100;
      row.querySelector(".price-input").value = m ? fmt(p) : "";
      row.querySelector(".subtotal-input").value = fmt(sub);
      sum += sub;
    });
    total.value = fmt(sum);
    if (!paid.dataset.touched) paid.value = fmt(sum);
  }
  function addLine(id, kg) {
    const fragment = template.content.cloneNode(true), row = fragment.querySelector("tr");
    rows.appendChild(fragment);
    if (id) row.querySelector(".material-select").value = id;
    if (kg) row.querySelector(".kg-input").value = kg;
    recalc();
  }
  rows.addEventListener("change", e => { if (e.target.matches(".material-select")) recalc(); });
  rows.addEventListener("input", e => { if (e.target.matches(".kg-input")) { paid.dataset.touched = ""; recalc(); } });
  rows.addEventListener("click", e => { if (e.target.matches(".remove-line") && rows.querySelectorAll("tr").length > 2) { e.target.closest("tr").remove(); recalc(); } });
  document.getElementById("add-material").addEventListener("click", () => addLine("", ""));
  person.addEventListener("change", recalc); person.addEventListener("input", recalc);
  paid.addEventListener("input", () => { paid.dataset.touched = "1"; });
  ticket.addEventListener("change", () => {
    const old = tickets[ticket.value.trim().toLowerCase()];
    if (!old) return;
    person.value = old.persona || person.value;
    while (rows.querySelectorAll("tr").length > 2) rows.lastElementChild.remove();
    const lines = old.materiales || [];
    rows.querySelectorAll("tr").forEach((row, i) => {
      row.querySelector(".material-select").value = lines[i] ? String(lines[i].material_id || "") : "";
      row.querySelector(".kg-input").value = lines[i] ? lines[i].kg : "";
    });
    lines.slice(2).forEach(line => addLine(String(line.material_id || ""), line.kg || ""));
    recalc(); total.value = fmt(old.total);
    if (!paid.dataset.touched) { paid.value = fmt(old.saldo); paid.dataset.touched = ""; }
  });
  form.addEventListener("submit", e => {
    if (!vendor()) { e.preventDefault(); alert("Seleccioná un cliente/proveedor registrado."); return; }
    if (!tickets[ticket.value.trim().toLowerCase()]) {
      let valid = 0, invalid = false;
      rows.querySelectorAll("tr").forEach(row => {
        const id = row.querySelector(".material-select").value, kg = Number(row.querySelector(".kg-input").value || 0);
        if (id || kg) { valid++; if (!id || kg <= 0) invalid = true; }
      });
      if (!valid || invalid) { e.preventDefault(); alert("Seleccioná al menos un material e ingresá sus kg."); }
    }
  });
});