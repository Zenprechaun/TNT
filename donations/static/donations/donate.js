/* The Donate page: keeps the button and the fee offer in step with the chosen amount.
   The form works without this script; it only adds the live updates. */
(() => {
  'use strict';

  // Translations come from /jsi18n/ (Django's JavaScript catalog), loaded before this script.
  const gettext = window.gettext || ((text) => text);
  const fmt = (text, values) => text.replace(/%\((\w+)\)s/g, (m, key) => String(values[key]));
  const money = (cents) => {
    const whole = Math.floor(cents / 100).toLocaleString('en-US');
    const rest = cents % 100;
    return rest ? `$${whole}.${String(rest).padStart(2, '0')}` : `$${whole}`;
  };

  document.querySelectorAll('[data-print]').forEach((button) => {
    button.addEventListener('click', () => window.print());
  });

  const root = document.querySelector('[data-donate]');
  const form = root && root.querySelector('[data-donate-form]');
  if (!form) return;

  const rate = parseFloat(root.dataset.feePercent) / 100;
  const fixed = parseInt(root.dataset.feeCents, 10);
  const MIN = 500;
  const MAX = 1000000;
  const DEFAULTS = { once: '50', monthly: '25' };
  const otherBox = form.querySelector('[data-other]');
  const otherInput = form.querySelector('#don-other');
  const otherChoice = form.querySelector('input[name="amount"][value="other"]');
  const coverFee = form.querySelector('[data-cover-fee]');
  const feeText = form.querySelector('[data-fee-text]');
  const submit = form.querySelector('[data-submit]');
  const submitText = form.querySelector('[data-submit-text]');
  let picked = root.hasAttribute('data-keep');

  const checked = (name) => form.querySelector(`input[name="${name}"]:checked`);

  function cents() {
    const choice = checked('amount');
    if (!choice) return null;
    if (choice.value !== 'other') return parseInt(choice.value, 10) * 100;
    const text = otherInput.value.replace(/[$,\s]/g, '');
    if (!/^\d+(\.\d{1,2})?$/.test(text)) return null;
    return Math.round(parseFloat(text) * 100);
  }

  const feeFor = (amount) => Math.ceil((amount + fixed) / (1 - rate)) - amount;

  function refresh() {
    otherBox.hidden = !otherChoice.checked;
    const amount = cents();
    const monthly = (checked('frequency') || {}).value === 'monthly';
    if (amount && amount >= MIN && amount <= MAX) {
      const fee = feeFor(amount);
      feeText.textContent = fmt(gettext('Add %(fee)s to cover the card fee, so your whole donation reaches our neighbors.'), { fee: money(fee) });
      const total = money(amount + (coverFee.checked ? fee : 0));
      submitText.textContent = fmt(monthly ? gettext('Donate %(amount)s a month') : gettext('Donate %(amount)s'), { amount: total });
    } else {
      feeText.textContent = gettext('Add a little to cover the card fee, so your whole donation reaches our neighbors.');
      submitText.textContent = gettext('Donate');
    }
  }

  form.addEventListener('change', (event) => {
    const { name, value } = event.target;
    if (name === 'amount') picked = true;
    if (name === 'frequency' && !picked) {
      // Until someone picks an amount, suggest the usual one for one-time or monthly giving.
      const suggestion = form.querySelector(`input[name="amount"][value="${DEFAULTS[value]}"]`);
      if (suggestion) suggestion.checked = true;
    }
    refresh();
    if (name === 'amount' && value === 'other') otherInput.focus();
  });
  otherInput.addEventListener('input', () => {
    otherChoice.checked = true;
    picked = true;
    refresh();
  });

  form.addEventListener('submit', () => {
    submit.disabled = true;
    submitText.textContent = gettext('Opening secure payment…');
  });
  // Coming back with the browser's Back button shows the page as it was left: make the button usable again.
  window.addEventListener('pageshow', () => {
    submit.disabled = false;
    refresh();
  });

  refresh();
})();
