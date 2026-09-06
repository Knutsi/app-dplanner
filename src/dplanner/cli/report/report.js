// The report's script — inlined into every page by page.py. No framework, no fetches.
// One selection: every element with data-step answers a pick, and the drawer shows the card.
(function () {
  "use strict";
  var cards = {};
  var keys = {};
  var template = document.getElementById("cards");
  if (template) {
    template.content.querySelectorAll("article.card").forEach(function (card) {
      cards[card.dataset.step] = card;
      keys[card.dataset.key] = card.dataset.step;
    });
  }
  var drawer = document.getElementById("drawer");
  var body = drawer ? drawer.querySelector(".drawer-body") : null;
  var selected = null;

  function everyone(id) {
    return document.querySelectorAll('[data-step="' + id + '"]');
  }

  function select(id, opts) {
    opts = opts || {};
    if (selected) {
      everyone(selected).forEach(function (el) { el.classList.remove("selected"); });
      document.querySelectorAll("svg.graph .node.dimmed").forEach(function (el) { el.classList.remove("dimmed"); });
    }
    selected = id;
    if (!id || !cards[id]) {
      if (drawer) drawer.hidden = true;
      if (!opts.keepHash) history.replaceState(null, "", location.pathname + location.search);
      return;
    }
    everyone(id).forEach(function (el) { el.classList.add("selected"); });
    dimGraphAround(id);
    if (drawer && body) {
      body.innerHTML = "";
      body.appendChild(cards[id].cloneNode(true));
      drawer.hidden = false;
    }
    if (!opts.keepHash) history.replaceState(null, "", "#step=" + encodeURIComponent(cards[id].dataset.key));
    if (opts.reveal) {
      var node = document.querySelector('svg.graph .node[data-step="' + id + '"]');
      if (node) node.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }

  // Picking a card lights its neighbours and dims the rest — the coverage lanes' rule.
  function dimGraphAround(id) {
    var svg = document.querySelector("svg.graph");
    if (!svg) return;
    var near = { };
    near[id] = true;
    svg.querySelectorAll(".edge").forEach(function (edge) {
      if (edge.dataset.from === id) near[edge.dataset.to] = true;
      if (edge.dataset.to === id) near[edge.dataset.from] = true;
    });
    svg.querySelectorAll(".node").forEach(function (node) {
      if (!near[node.dataset.step]) node.classList.add("dimmed");
    });
  }

  document.addEventListener("click", function (event) {
    var target = event.target.closest("[data-step]");
    if (target && target.dataset.step && !target.closest("#drawer") && !target.closest("template")) {
      if (target.closest("a")) return;
      select(target.dataset.step, { reveal: !target.closest("svg.graph") });
      event.preventDefault();
    } else if (event.target.closest("#drawer .close")) {
      select(null);
    }
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") select(null);
  });

  function fromHash() {
    var match = /#step=([^&]+)/.exec(location.hash);
    if (!match) return;
    var key = decodeURIComponent(match[1]);
    var id = keys[key] || (cards[key] ? key : null);
    if (id) select(id, { keepHash: true, reveal: true });
  }
  window.addEventListener("hashchange", fromHash);

  // The steps table: a filter box and a status pick.
  var filter = document.getElementById("step-filter");
  var status = document.getElementById("status-filter");
  function applyFilter() {
    var words = (filter ? filter.value : "").trim().toLowerCase();
    var want = status ? status.value : "";
    document.querySelectorAll("#table-steps tbody tr").forEach(function (row) {
      var text = row.textContent.toLowerCase();
      var word = row.querySelector(".status");
      var has = word ? word.className.replace("status ", "").replace("status-", "") : "";
      var hidden = (words && text.indexOf(words) < 0) || (want && has !== want);
      row.classList.toggle("hidden", !!hidden);
    });
  }
  if (filter) filter.addEventListener("input", applyFilter);
  if (status) status.addEventListener("change", applyFilter);

  // The graph: pan by dragging, zoom by wheel or buttons, fit on load.
  document.querySelectorAll("figure.graph-frame").forEach(function (frame) {
    var viewport = frame.querySelector(".viewport");
    var svg = frame.querySelector("svg.graph");
    if (!viewport || !svg) return;
    var width = parseFloat(svg.getAttribute("width")) || 1;
    var height = parseFloat(svg.getAttribute("height")) || 1;
    var scale = 1, tx = 0, ty = 0;
    function apply() {
      svg.style.transform = "translate(" + tx + "px," + ty + "px) scale(" + scale + ")";
    }
    function fit() {
      // Readable first: never below 0.6, so a wide plan starts at its left edge and pans,
      // and a shallow plan gets a viewport its own height rather than a dark field.
      var box = viewport.getBoundingClientRect();
      var wanted = Math.min(box.width / width, 1.25);
      scale = Math.max(0.6, Math.min(wanted, 1.25));
      if (!isFinite(scale) || scale <= 0) scale = 1;
      var shown = Math.min(window.innerHeight * 0.7, Math.max(260, height * scale + 32));
      viewport.style.height = shown + "px";
      box = viewport.getBoundingClientRect();
      tx = width * scale < box.width ? (box.width - width * scale) / 2 : 16;
      ty = (box.height - height * scale) / 2;
      apply();
    }
    function zoomAt(factor, cx, cy) {
      var next = Math.min(4, Math.max(0.15, scale * factor));
      tx = cx - (cx - tx) * (next / scale);
      ty = cy - (cy - ty) * (next / scale);
      scale = next;
      apply();
    }
    frame.querySelectorAll("[data-zoom]").forEach(function (button) {
      button.addEventListener("click", function () {
        var box = viewport.getBoundingClientRect();
        if (button.dataset.zoom === "fit") fit();
        else zoomAt(button.dataset.zoom === "in" ? 1.25 : 0.8, box.width / 2, box.height / 2);
      });
    });
    viewport.addEventListener("wheel", function (event) {
      event.preventDefault();
      var box = viewport.getBoundingClientRect();
      zoomAt(event.deltaY < 0 ? 1.1 : 0.9, event.clientX - box.left, event.clientY - box.top);
    }, { passive: false });
    var drag = null;
    viewport.addEventListener("pointerdown", function (event) {
      if (event.button !== 0) return;
      drag = { x: event.clientX, y: event.clientY, tx: tx, ty: ty, moved: false };
      viewport.setPointerCapture(event.pointerId);
    });
    viewport.addEventListener("pointermove", function (event) {
      if (!drag) return;
      var dx = event.clientX - drag.x, dy = event.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      tx = drag.tx + dx; ty = drag.ty + dy;
      apply();
    });
    viewport.addEventListener("pointerup", function (event) {
      if (drag && drag.moved) {
        // A drag is not a click: swallow the click that follows it.
        var swallow = function (e) { e.stopPropagation(); e.preventDefault(); viewport.removeEventListener("click", swallow, true); };
        viewport.addEventListener("click", swallow, true);
      }
      drag = null;
    });
    viewport.addEventListener("pointercancel", function () { drag = null; });
    fit();
    window.addEventListener("resize", fit);
  });

  // The chart: one crosshair down every plot, and a tooltip reading the plot under the
  // pointer — the plots share an axis, so the date is one date, but each answers its own
  // question and reporting all of them at once is what the stacked plots undid.
  document.querySelectorAll("figure.chart").forEach(function (figure) {
    var svg = figure.querySelector("svg.chart");
    var tip = figure.querySelector(".tooltip");
    if (!svg || !tip) return;
    var first = new Date(svg.dataset.first + "T00:00:00Z");
    var last = new Date(svg.dataset.last + "T00:00:00Z");
    var left = parseFloat(svg.dataset.left), right = parseFloat(svg.dataset.right);
    var top = parseFloat(svg.dataset.top), bottom = parseFloat(svg.dataset.bottom);
    var days = Math.max(1, Math.round((last - first) / 86400000));
    var plots = [];
    svg.querySelectorAll("g.plot").forEach(function (group) {
      var series = [];
      group.querySelectorAll("polyline.series").forEach(function (line) {
        var points = (line.dataset.points || "").split(";").filter(Boolean).map(function (pair) {
          var bits = pair.split(":");
          return { day: new Date(bits[0] + "T00:00:00Z"), share: parseFloat(bits[1]) };
        });
        series.push({ label: line.dataset.label, points: points });
      });
      var rows = [];
      group.querySelectorAll("g.shift").forEach(function (row) {
        rows.push(row.dataset.words || "");
      });
      plots.push({
        kind: group.dataset.kind,
        top: parseFloat(group.dataset.top),
        bottom: parseFloat(group.dataset.bottom),
        series: series,
        rows: rows,
      });
    });
    var cross = document.createElementNS("http://www.w3.org/2000/svg", "line");
    cross.setAttribute("class", "crosshair");
    cross.setAttribute("y1", top); cross.setAttribute("y2", bottom);
    cross.setAttribute("stroke", "currentColor"); cross.setAttribute("stroke-opacity", "0.4");
    cross.setAttribute("stroke-width", "1"); cross.style.display = "none";
    svg.appendChild(cross);
    function shareAt(points, day) {
      var found = null;
      for (var i = 0; i < points.length; i++) {
        if (points[i].day > day) break;
        found = points[i].share;
      }
      return found;
    }
    function fmt(day) {
      return day.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
    }
    function hide() { tip.hidden = true; cross.style.display = "none"; }
    svg.addEventListener("pointermove", function (event) {
      var box = svg.getBoundingClientRect();
      var scale = svg.viewBox.baseVal.width / box.width;
      var viewX = (event.clientX - box.left) * scale;
      var viewY = (event.clientY - box.top) * (svg.viewBox.baseVal.height / box.height);
      if (viewX < left || viewX > right) { hide(); return; }
      var plot = null;
      for (var i = 0; i < plots.length; i++) {
        if (viewY >= plots[i].top && viewY <= plots[i].bottom) { plot = plots[i]; break; }
      }
      if (!plot) { hide(); return; }
      var offset = Math.round((viewX - left) / (right - left) * days);
      var day = new Date(first.getTime() + offset * 86400000);
      var snapped = left + offset / days * (right - left);
      cross.setAttribute("x1", snapped); cross.setAttribute("x2", snapped);
      cross.style.display = "";
      var lines = [];
      if (plot.kind === "shift") {
        var row = Math.floor((viewY - plot.top) / ((plot.bottom - plot.top) / plot.rows.length));
        if (row < 0 || row >= plot.rows.length) { hide(); return; }
        lines.push(plot.rows[row]);
      } else {
        lines.push("<b>" + fmt(day) + "</b>");
        plot.series.forEach(function (entry) {
          var share = shareAt(entry.points, day);
          if (share !== null) lines.push(entry.label + ": " + Math.round(share * 100) + "%");
        });
      }
      tip.innerHTML = lines.join("<br>");
      tip.hidden = false;
      var x = event.clientX - box.left + 12, y = event.clientY - box.top + 12;
      if (x + tip.offsetWidth > box.width) x = event.clientX - box.left - tip.offsetWidth - 12;
      tip.style.left = x + "px"; tip.style.top = y + "px";
    });
    svg.addEventListener("pointerleave", hide);
  });

  fromHash();
})();
