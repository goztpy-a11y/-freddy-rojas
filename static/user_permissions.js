(() => {
  'use strict';
  for (const form of document.querySelectorAll('[data-user-permissions]')) {
    const role = form.querySelector('[name=role]');
    const extra = form.querySelector('[data-extra-areas]');
    if (!role || !extra) continue;
    const refresh = () => {
      const bankOnly = role.value === 'banco';
      extra.hidden = bankOnly;
      for (const input of extra.querySelectorAll('input')) input.disabled = bankOnly;
    };
    role.addEventListener('change', refresh);
    refresh();
  }
})();
