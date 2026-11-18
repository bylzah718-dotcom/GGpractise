// Клиентская проверка форм до отправки. Серверная проверка остаётся главной: это только подсказка пользователю.
(function () {
  var EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  var PHONE = /^(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}$/;

  function labelOf(el) {
    var l = el.id && document.querySelector('label[for="' + el.id + '"]');
    return l ? l.textContent.replace(/[*:]/g, "").trim() : "это поле";
  }

  function check(el) {
    var v = (el.value || "").trim();
    if (el.type === "file" || el.type === "checkbox" || el.type === "radio" || el.type === "hidden" || el.disabled) return "";
    if (el.required && v === "") return "Заполните поле «" + labelOf(el) + "».";
    if (v === "") return "";
    if (el.type === "email" && !EMAIL.test(v)) return "Введите почту в формате name@example.ru.";
    if (el.hasAttribute("data-phone") && !PHONE.test(v)) return "Введите телефон в формате +7 900 000-00-00.";
    var min = el.getAttribute("minlength"), max = el.getAttribute("maxlength");
    if (min && v.length < Number(min)) return "Не короче " + min + " символов (сейчас " + v.length + ").";
    if (max && v.length > Number(max)) return "Не длиннее " + max + " символов (сейчас " + v.length + ").";
    if (el.type === "number") {
      var n = Number(v.replace(",", "."));
      if (isNaN(n)) return "Введите число.";
      if (el.min !== "" && n < Number(el.min)) return "Число не может быть меньше " + el.min + ".";
      if (el.max !== "" && n > Number(el.max)) return "Число не может быть больше " + el.max + ".";
    }
    return "";
  }

  function show(el, text) {
    var holder = el.closest(".field") || el.parentNode;
    var box = holder.querySelector(".client-error[data-for='" + (el.id || el.name) + "']");
    if (!text) {
      if (box) box.remove();
      el.removeAttribute("aria-invalid");
      return;
    }
    if (!box) {
      box = document.createElement("div");
      box.className = "client-error";
      box.setAttribute("role", "alert");
      box.setAttribute("data-for", el.id || el.name);
      box.id = "err-" + (el.id || el.name);
      el.insertAdjacentElement("afterend", box);
    }
    box.textContent = text;
    el.setAttribute("aria-invalid", "true");
    el.setAttribute("aria-describedby", box.id);
  }

  document.querySelectorAll("form.form[novalidate]").forEach(function (form) {
    var fields = form.querySelectorAll("input, select, textarea");
    fields.forEach(function (el) {
      el.addEventListener("blur", function () { if (el.value !== "") show(el, check(el)); });
      el.addEventListener("input", function () { if (el.hasAttribute("aria-invalid")) show(el, check(el)); });
    });
    form.addEventListener("submit", function (ev) {
      var first = null;
      fields.forEach(function (el) {
        var msg = check(el);
        show(el, msg);
        if (msg && !first) first = el;
      });
      if (first) { ev.preventDefault(); first.focus(); }
    });
  });
})();
