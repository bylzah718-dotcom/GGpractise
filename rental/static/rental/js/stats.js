// Графики на странице показателей. Данные приходят с сервера (/api/stats/) в JSON, рисуем SVG без библиотек.
(function () {
  var NS = "http://www.w3.org/2000/svg";
  var money = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });

  function el(name, attrs, text) {
    var node = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function frame(w, h) {
    var svg = el("svg", { viewBox: "0 0 " + w + " " + h, role: "presentation" });
    return svg;
  }

  function bars(container, rows) {
    var W = 560, H = 300, L = 56, B = 54, T = 16, R = 12;
    var svg = frame(W, H);
    var max = Math.max.apply(null, rows.map(function (r) { return r.value; }).concat([1]));
    var slot = (W - L - R) / rows.length, bw = Math.min(54, slot * 0.6);
    [0, 0.5, 1].forEach(function (t) {
      var y = T + (H - T - B) * (1 - t);
      svg.appendChild(el("line", { x1: L, x2: W - R, y1: y, y2: y, stroke: "#e2ddd5" }));
      svg.appendChild(el("text", { x: L - 6, y: y + 4, "text-anchor": "end", "font-size": 11, fill: "#6b665e" }, money.format(max * t)));
    });
    rows.forEach(function (r, i) {
      var h = (H - T - B) * r.value / max, x = L + slot * i + (slot - bw) / 2, y = H - B - h;
      var rect = el("rect", { x: x, y: y, width: bw, height: h, rx: 4, fill: "#b4532a" });
      rect.appendChild(el("title", {}, r.label + ": " + money.format(r.value) + " ₽, броней: " + r.count));
      svg.appendChild(rect);
      svg.appendChild(el("text", { x: x + bw / 2, y: H - B + 16, "text-anchor": "middle", "font-size": 11, fill: "#1f1d1a" },
        r.label.length > 10 ? r.label.slice(0, 9) + "…" : r.label));
    });
    container.textContent = ""; container.appendChild(svg);
  }

  function line(container, rows) {
    var W = 560, H = 300, L = 56, B = 40, T = 16, R = 20;
    var svg = frame(W, H);
    var max = Math.max.apply(null, rows.map(function (r) { return r.value; }).concat([1]));
    var step = rows.length > 1 ? (W - L - R) / (rows.length - 1) : 0;
    [0, 0.5, 1].forEach(function (t) {
      var y = T + (H - T - B) * (1 - t);
      svg.appendChild(el("line", { x1: L, x2: W - R, y1: y, y2: y, stroke: "#e2ddd5" }));
      svg.appendChild(el("text", { x: L - 6, y: y + 4, "text-anchor": "end", "font-size": 11, fill: "#6b665e" }, money.format(max * t)));
    });
    var pts = rows.map(function (r, i) {
      return { x: rows.length > 1 ? L + step * i : (W + L - R) / 2, y: T + (H - T - B) * (1 - r.value / max), r: r };
    });
    svg.appendChild(el("polyline", { points: pts.map(function (p) { return p.x + "," + p.y; }).join(" "), fill: "none", stroke: "#b4532a", "stroke-width": 3 }));
    pts.forEach(function (p) {
      var c = el("circle", { cx: p.x, cy: p.y, r: 5, fill: "#b4532a" });
      c.appendChild(el("title", {}, p.r.label + ": " + money.format(p.r.value) + " ₽, броней: " + p.r.count));
      svg.appendChild(c);
      svg.appendChild(el("text", { x: p.x, y: H - B + 18, "text-anchor": "middle", "font-size": 11, fill: "#1f1d1a" }, p.r.label));
    });
    container.textContent = ""; container.appendChild(svg);
  }

  var charts = document.querySelectorAll(".chart[data-url]");
  if (!charts.length) return;
  fetch(charts[0].dataset.url, { headers: { Accept: "application/json" } })
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (data) {
      charts.forEach(function (c) {
        var rows = data[c.dataset.key] || [];
        if (!rows.length) { c.textContent = "Нет данных для графика."; return; }
        (c.dataset.key === "by_month" ? line : bars)(c, rows);
      });
    })
    .catch(function () { charts.forEach(function (c) { c.textContent = "Не удалось загрузить данные графика."; }); });
})();
