/* Tahoe Neighborhood Table: the login popup.
   "Log in" opens the popup. Without JavaScript, the same link opens the full login page. */
(function () {
  var dialog = document.getElementById('login-dialog');

  if (dialog && typeof dialog.showModal === 'function') {
    var opener = null;
    var firstField = dialog.querySelector('input[name="username"]');
    document.querySelectorAll('[data-login-open]').forEach(function (link) {
      link.addEventListener('click', function (event) {
        event.preventDefault();
        opener = link;
        dialog.showModal();
        if (firstField) { firstField.focus(); }
      });
    });
    dialog.querySelector('[data-login-close]').addEventListener('click', function () { dialog.close(); });
    dialog.addEventListener('click', function (event) {
      if (event.target === dialog) { dialog.close(); }  // a click on the dimmed area outside the popup
    });
    dialog.addEventListener('close', function () { if (opener) { opener.focus(); } });
  }

  // Sign in without leaving the page, so a mistake can be fixed in place.
  document.querySelectorAll('[data-login-form]').forEach(function (form) {
    var error = form.querySelector('[data-login-error]');
    var submit = form.querySelector('[data-login-submit]');
    var password = form.querySelector('input[name="password"]');
    var label = submit.textContent;

    function showError(message) {
      error.textContent = message;
      error.hidden = false;
      submit.disabled = false;
      submit.textContent = label;
      password.value = '';
      password.focus();
    }

    form.addEventListener('submit', function (event) {
      if (!window.fetch || !window.FormData) { return; }
      event.preventDefault();
      error.hidden = true;
      submit.disabled = true;
      submit.textContent = 'Logging in…';
      fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        headers: { 'Accept': 'application/json' },
        credentials: 'same-origin'
      }).then(function (response) {
        if (response.status === 403) {
          return { ok: false, message: 'This form has expired. Reload the page and try again.' };
        }
        if (response.status === 429) {  // the live server limits repeated login attempts
          return { ok: false, message: 'Too many tries. Wait a minute, then try again.' };
        }
        return response.json().catch(function () { return { ok: false }; });
      }).then(function (data) {
        if (data && data.ok && data.redirect) {
          window.location.assign(data.redirect);
          return;
        }
        showError((data && data.message) || 'Something went wrong. Try again.');
      }).catch(function () {
        showError("Couldn't reach the website. Check your connection and try again.");
      });
    });
  });
})();
