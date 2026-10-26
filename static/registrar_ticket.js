document.addEventListener("DOMContentLoaded", function () {
  const form = document.getElementById("ticket-form");
  if (!form) return;
  const vendors = JSON.parse(document.getElementById("pago-vendors").textContent || "[]");
  const materials = JSON.parse(document.getElementById("pago-materials")?.textContent || "[]");
  const person = form.querySelector('[name="persona"]');
  const paymentOption = document.getElementById("payment-option");
  const paymentCheckbox = form.querySelector('[name="en_pagos"]');
  const rows = document.getElementById("material-lines");
  const template = document.getElementById("material-row");
  const total = document.getElementById("total");
  const vendor = () => vendors.find(v => v.nombre.toLowerCase() === person.value.trim().toLowerCase());
  const fmt = n => (Number(n) || 0).toFixed(2);
  function updatePaymentOption() {
    const v = vendor();
    const eligible = Boolean(v && v.en_pagos);
    paymentOption.style.display = eligible ? "" : "none";
    if (!eligible) paymentCheckbox.checked = false;
  }
  function recalc() {
    let sum = 0, v = vendor();
    rows.querySelectorAll("tr").forEach(row => {
      const sel = row.querySelector(".material-select");
      const kg = Number(row.querySelector(".kg-input").value || 0);
      const m = materials.find(x => String(x.id) === sel.value);
      const p = v && m ? Number(v.precios[String(m.id)] || 0) : 0;
      const sub = Math.round(kg * p * 100) / 100;
      row.querySelector(".price-input").value = m ? fmt(p) : "";
      row.querySelector(".subtotal-input").value = fmt(sub);
      sum += sub;
    });
    total.value = fmt(sum);
  }
  function addLine() { rows.appendChild(template.content.cloneNode(true)); recalc(); }
  rows.addEventListener("change", e => { if (e.target.matches(".material-select")) recalc(); });
  rows.addEventListener("input", e => { if (e.target.matches(".kg-input")) recalc(); });
  rows.addEventListener("click", e => {
    if (e.target.matches(".remove-line") && rows.querySelectorAll("tr").length > 1) {
      e.target.closest("tr").remove(); recalc();
    }
  });
  document.getElementById("add-material").addEventListener("click", addLine);
  person.addEventListener("change", () => { updatePaymentOption(); recalc(); });
  person.addEventListener("input", () => { updatePaymentOption(); recalc(); });
  form.addEventListener("submit", e => {
    if (!vendor()) { e.preventDefault(); alert("Seleccioná un cliente/proveedor registrado."); return; }
    let valid = 0, invalid = false;
    rows.querySelectorAll("tr").forEach(row => {
      const id = row.querySelector(".material-select").value;
      const raw = row.querySelector(".kg-input").value.trim();
      const kg = Number(raw || 0);
      if (id || raw) { valid++; if (!id || kg <= 0) invalid = true; }
    });
    if (!valid || invalid) { e.preventDefault(); alert("Seleccioná al menos un material e ingresá sus kg."); }
  });
  updatePaymentOption();
  recalc();
});