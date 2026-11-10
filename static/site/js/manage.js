/* Tahoe Neighborhood Table: the Management page.
   In the email service form, shows only the fields and notes the chosen service needs.
   Without JavaScript every field shows, and the site ignores the ones the service doesn't use. */
(function () {
  document.querySelectorAll('[data-email-service]').forEach(function (form) {
    function update() {
      var chosen = form.querySelector('input[name="service"]:checked');
      var service = chosen ? chosen.value : '';
      form.querySelectorAll('[data-services]').forEach(function (part) {
        part.hidden = part.getAttribute('data-services').split(' ').indexOf(service) === -1;
      });
    }
    form.querySelectorAll('input[name="service"]').forEach(function (radio) {
      radio.addEventListener('change', update);
    });
    update();
  });

  // Copy buttons: the temporary password and the OAuth redirect address.
  document.querySelectorAll('[data-copy]').forEach(function (button) {
    button.addEventListener('click', function () {
      var source = button.parentElement.querySelector('[data-copy-text]');
      if (!source) return;
      var text = source.textContent.trim();
      var label = button.textContent;
      var copied = function () {
        button.textContent = button.getAttribute('data-copied') || label;
        setTimeout(function () { button.textContent = label; }, 2000);
      };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(copied, function () {});
      } else {
        var range = document.createRange();
        range.selectNodeContents(source);
        var selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
      }
    });
  });
})();
