// Модальное окно подтверждения: формы с data-confirm не отправляются, пока пользователь не нажмёт «Да».
(function () {
  var forms = document.querySelectorAll("form[data-confirm]");
  var dlg = document.getElementById("confirm-dialog");
  if (!forms.length || !dlg || typeof dlg.showModal !== "function") return;
  var text = dlg.querySelector("[data-dialog-text]");
  var yes = dlg.querySelector("[data-dialog-yes]");
  var no = dlg.querySelector("[data-dialog-no]");
  var pending = null, opener = null;
  forms.forEach(function (f) {
    f.addEventListener("submit", function (ev) {
      if (f.dataset.confirmed === "1") return;
      ev.preventDefault();
      pending = f; opener = document.activeElement;
      text.textContent = f.dataset.confirm;
      dlg.showModal();
      no.focus();
    });
  });
  yes.addEventListener("click", function () {
    if (!pending) return;
    pending.dataset.confirmed = "1"; dlg.close(); pending.submit();
  });
  no.addEventListener("click", function () { dlg.close(); });
  dlg.addEventListener("close", function () { if (opener) opener.focus(); pending = null; });
})();
