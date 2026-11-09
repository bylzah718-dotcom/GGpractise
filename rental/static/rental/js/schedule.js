// Сетка свободных часов зала: fetch к /api/schedule/, страница не перезагружается.
(function () {
  var form = document.getElementById("schedule-form");
  if (!form) return;
  var dateInput = document.getElementById("schedule-date");
  var grid = document.getElementById("schedule-grid");
  var dayType = document.getElementById("schedule-daytype");
  var money = new Intl.NumberFormat("ru-RU");

  function render(data) {
    grid.textContent = "";
    dayType.textContent = data.day_type;
    data.slots.forEach(function (slot) {
      var el;
      if (slot.state === "free") {
        el = document.createElement("a");
        el.href = form.action + "?hall=" + encodeURIComponent(form.dataset.slug) +
          "&date=" + encodeURIComponent(data.date) + "&start=" + slot.hour;
      } else {
        el = document.createElement("span");
      }
      el.className = "slot " + slot.state;
      el.appendChild(document.createTextNode(slot.label));
      var price = document.createElement("small");
      price.textContent = slot.price ? money.format(Number(slot.price)) + " ₽" : "—";
      el.appendChild(price);
      grid.appendChild(el);
    });
  }

  function load() {
    var url = form.dataset.url + "?hall=" + encodeURIComponent(form.dataset.hall) + "&date=" + encodeURIComponent(dateInput.value);
    grid.textContent = "Загрузка…";
    fetch(url, { headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(render)
      .catch(function () { grid.textContent = "Не удалось загрузить расписание. Попробуйте позже."; });
  }

  dateInput.addEventListener("change", load);
  load();
})();
