// Живой поиск и фильтры каталога: fetch к /api/equipment/, без перезагрузки страницы; «Показать ещё» подгружает следующую страницу.
(function () {
  var form = document.getElementById("eq-form");
  var grid = document.getElementById("eq-grid");
  if (!form || !grid || !window.fetch) return;
  var more = document.getElementById("eq-more");
  var status = document.getElementById("eq-status");
  var pager = document.getElementById("eq-pager");
  var money = new Intl.NumberFormat("ru-RU");
  var page = Number(grid.dataset.page) || 1;
  var timer = null, seq = 0;
  if (pager) pager.hidden = true;
  more.hidden = grid.dataset.hasNext !== "1";

  function card(it) {
    var art = document.createElement("article");
    art.className = "card";
    if (it.image) {
      var img = document.createElement("img");
      img.src = it.image; img.alt = it.name; img.width = 400; img.height = 250; img.loading = "lazy";
      art.appendChild(img);
    } else {
      var ph = document.createElement("div");
      ph.className = "img-placeholder"; ph.textContent = "Нет фото";
      art.appendChild(ph);
    }
    var body = document.createElement("div");
    body.className = "card-body";
    var h = document.createElement("h3"); h.textContent = it.name;
    var p1 = document.createElement("p"); p1.className = "muted"; p1.textContent = it.category + " · " + it.inventory_number;
    var p2 = document.createElement("p");
    var b = document.createElement("span"); b.className = "badge badge-" + it.status; b.textContent = it.status_label;
    var pr = document.createElement("span"); pr.className = "price"; pr.textContent = money.format(Number(it.price)) + " ₽/час";
    p2.appendChild(b); p2.appendChild(document.createTextNode(" ")); p2.appendChild(pr);
    body.appendChild(h); body.appendChild(p1); body.appendChild(p2);
    if (it.edit_url) {
      var p3 = document.createElement("p");
      var a1 = document.createElement("a"); a1.href = it.edit_url; a1.className = "tap"; a1.textContent = "Изменить";
      var a2 = document.createElement("a"); a2.href = it.delete_url; a2.className = "tap"; a2.textContent = "Удалить";
      p3.appendChild(a1); p3.appendChild(document.createTextNode(" · ")); p3.appendChild(a2);
      body.appendChild(p3);
    }
    art.appendChild(body);
    return art;
  }

  function params(p) {
    var qs = new URLSearchParams(new FormData(form));
    Array.from(qs.keys()).forEach(function (k) { if (qs.get(k) === "") qs.delete(k); });
    if (p > 1) qs.set("page", p);
    return qs.toString();
  }

  function load(p, append) {
    var my = ++seq;
    grid.setAttribute("aria-busy", "true");
    grid.classList.add("is-loading");
    status.textContent = "Загрузка…";
    more.disabled = true;
    fetch(grid.dataset.url + "?" + params(p), { headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (data) {
        if (my !== seq) return;
        if (!append) grid.textContent = "";
        data.items.forEach(function (it) { grid.appendChild(card(it)); });
        if (!data.items.length && !append) {
          var empty = document.createElement("p"); empty.textContent = "По вашему запросу ничего не найдено."; grid.appendChild(empty);
        }
        page = data.page;
        more.hidden = !data.has_next;
        status.textContent = "Найдено: " + data.count;
        history.replaceState(null, "", location.pathname + (params(1) ? "?" + params(1) : ""));
      })
      .catch(function () { if (my === seq) status.textContent = "Не удалось обновить список. Проверьте соединение и попробуйте ещё раз."; })
      .finally(function () {
        if (my !== seq) return;
        grid.setAttribute("aria-busy", "false"); grid.classList.remove("is-loading"); more.disabled = false;
      });
  }

  form.addEventListener("submit", function (ev) { ev.preventDefault(); load(1, false); });
  form.addEventListener("input", function (ev) {
    clearTimeout(timer);
    timer = setTimeout(function () { load(1, false); }, ev.target.type === "search" || ev.target.type === "number" ? 350 : 0);
  });
  more.addEventListener("click", function () { load(page + 1, true); });
})();
