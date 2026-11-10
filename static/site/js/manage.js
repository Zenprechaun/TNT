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
})();
