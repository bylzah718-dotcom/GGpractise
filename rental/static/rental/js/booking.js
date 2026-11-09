// Форма брони: живой расчёт стоимости и блокировка занятого оборудования.
// Все цены и проверки считает сервер (/api/quote/) — здесь только отображение результата.
(function () {
  var form = document.getElementById("booking-form");
  if (!form) return;
  var body = document.getElementById("quote-body");
  var money = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });
  var timer = null, seq = 0;

  function field(name) { return form.elements[name]; }
  function boxes(name) { return Array.prototype.slice.call(form.querySelectorAll('input[name="' + name + '"]')); }
  function m(v) { return money.format(Number(v)) + " ₽"; }

  function params() {
    var p = new URLSearchParams();
    p.set("hall", field("hall").value);
    p.set("date", field("date").value);
    p.set("start", field("start_hour").value);
    p.set("hours", field("hours").value);
    p.set("people", field("people").value || "1");
    boxes("equipment").forEach(function (b) { if (b.checked) p.append("equipment", b.value); });
    boxes("makeup_seats").forEach(function (b) { if (b.checked) p.append("seats", b.value); });
    if (form.dataset.booking) p.set("booking", form.dataset.booking);
    return p;
  }

  function row(table, left, right, cls) {
    var tr = document.createElement("tr");
    if (cls) tr.className = cls;
    var a = document.createElement("td"), b = document.createElement("td");
    a.textContent = left; b.textContent = right;
    tr.appendChild(a); tr.appendChild(b); table.appendChild(tr);
  }

  function renderQuote(data) {
    body.textContent = "";
    if (data.quote) {
      var q = data.quote, table = document.createElement("table");
      table.className = "quote-table";
      q.segments.forEach(function (s) {
        row(table, s.label + ", " + s.day_label.toLowerCase() + ": " + s.hours + " ч × " + m(s.price), m(s.amount));
      });
      if (q.discount_percent) row(table, "Скидка " + q.discount_percent + "%", "−" + m(q.discount_amount));
      q.equipment.forEach(function (e) { row(table, e.name, m(e.cost)); });
      q.seats.forEach(function (s) { row(table, s.name, m(s.cost)); });
      body.appendChild(table);
      var total = document.createElement("p");
      total.className = "quote-total";
      total.textContent = "Итого: " + m(q.total);
      body.appendChild(total);
    }
    if (data.errors && data.errors.length) {
      var ul = document.createElement("ul");
      ul.className = "quote-errors";
      data.errors.forEach(function (e) { var li = document.createElement("li"); li.textContent = e; ul.appendChild(li); });
      body.appendChild(ul);
    } else if (!data.quote) {
      body.textContent = "Выберите зал, дату, время и длительность.";
    }
  }

  function applyAvailability(data) {
    var changed = false;
    boxes("equipment").forEach(function (box) {
      var label = box.closest("label"), note = label.querySelector(".busy-note");
      var reason = data.busy_equipment[box.value];
      if (reason) {
        if (box.checked) { box.checked = false; changed = true; }
        box.disabled = true; label.classList.add("is-busy"); note.textContent = reason;
      } else {
        box.disabled = false; label.classList.remove("is-busy"); note.textContent = "";
      }
    });
    var hallId = field("hall").value;
    boxes("makeup_seats").forEach(function (box) {
      var label = box.closest("label");
      var otherHall = box.dataset.hall !== hallId;
      label.hidden = otherHall;
      if (otherHall && box.checked) { box.checked = false; changed = true; }
      var busy = !!data.busy_seats[box.value];
      if (busy && box.checked) { box.checked = false; changed = true; }
      box.disabled = busy;
      label.classList.toggle("is-busy", busy);
    });
    return changed;
  }

  function refresh(isRepeat) {
    var my = ++seq;
    fetch(form.dataset.quoteUrl + "?" + params().toString(), { headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (data) {
        if (my !== seq) return; // пришёл устаревший ответ
        var changed = applyAvailability(data);
        if (changed && !isRepeat) { refresh(true); return; } // пересчитать без снятых позиций
        renderQuote(data);
      })
      .catch(function () { body.textContent = "Не удалось рассчитать стоимость. Проверьте соединение."; });
  }

  function schedule() { clearTimeout(timer); timer = setTimeout(function () { refresh(false); }, 200); }

  form.addEventListener("change", schedule);
  form.addEventListener("input", function (e) { if (e.target.name === "people") schedule(); });
  refresh(false);
})();
