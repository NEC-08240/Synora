(function () {
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-toggle]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var open = btn.getAttribute('aria-expanded') !== 'true';
        btn.setAttribute('aria-expanded', open);
        document.getElementById(btn.dataset.toggle).hidden = !open;
        btn.querySelector('.chev').textContent = open ? '▲' : '▼';
      });
    });
  });
})();
