/* Report interactivity: hover readout, threshold input, variant toggle. Vanilla, no network, no storage.
   The page is complete without it: the charts are static SVG and every variant is tabulated. */
(function () {
  "use strict";

  var SYMBOLS = { USD: "$", EUR: "€", GBP: "£" };

  // Rounding that mirrors Python's round() / format(): an exact decimal tie goes to the even neighbour.
  // toFixed(100) expands the double exactly, so 0.05 (really 0.05000000000000000277) is not a tie.
  function fixed(x, digits) {
    var exact = x.toFixed(100), dot = exact.indexOf(".");
    if (exact.slice(dot + 1 + digits).replace(/0+$/, "") === "5") {
      var kept = exact.slice(0, dot + 1 + digits).replace(/\.$/, "");
      var even = +kept.charAt(kept.length - 1) % 2 === 0;
      return (even ? +kept : +kept + Math.pow(10, -digits)).toFixed(digits);
    }
    return x.toFixed(digits);
  }
  function roundEven(x) { return +fixed(x, 0); }

  // Same output as rqharness.report.context.fmt_money.
  function fmtMoney(value, currency, short) {
    var sign = value < 0 ? "−" : "", a = Math.abs(value);
    var prefix = SYMBOLS[currency] || currency + " ";
    var num, unit;
    if (a >= 1e9) { num = a / 1e9; unit = "B"; }
    else if (roundEven(a / 1e3) >= 1000) { num = a / 1e6; unit = "M"; }
    else if (roundEven(a) >= 1000) return sign + prefix + roundEven(a / 1e3) + "k";
    else return sign + prefix + roundEven(a);
    var text = fixed(num, short ? 1 : 2);
    if (short && /\.0$/.test(text)) text = text.slice(0, -2);
    return sign + prefix + text + unit;
  }

  // Same output as rqharness.report.context.fmt_pct.
  function fmtPct(p) {
    var a = Math.abs(p) * 100;
    if (a === 0) return "0%";
    if (a < 0.05) return "<0.1%";
    return parseFloat(fixed(a, 1)) < 10 ? fixed(a, 1) + "%" : roundEven(a) + "%";
  }

  // Same interpolation as rqharness.report.svg.exceedance: linear between points, 0 past the last one.
  function exceedance(points, x) {
    if (!points.length) return 0;
    if (x <= points[0][0]) return points[0][1];
    if (x >= points[points.length - 1][0]) return 0;
    var i = 1;
    while (points[i][0] <= x) i++;
    var a = points[i - 1], b = points[i];
    return a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]);
  }

  // "750k", "1.5M", "2000000", "$1M", "1,500,000" -> number, or NaN.
  function parseAmount(text) {
    var m = /^\s*[$€£]?\s*([0-9][0-9,]*\.?[0-9]*|\.[0-9]+)\s*([kKmM]?)\s*$/.exec(text);
    if (!m) return NaN;
    var n = parseFloat(m[1].replace(/,/g, "")), u = m[2].toLowerCase();
    return u === "k" ? n * 1e3 : u === "m" ? n * 1e6 : n;
  }

  function appendBold(doc, parent, text) {
    var b = doc.createElement("b");
    b.textContent = text;
    parent.appendChild(b);
  }

  function initCurve(doc, svg) {
    var points = JSON.parse(svg.getAttribute("data-points"));
    var ids = Object.keys(points);
    var currency = svg.getAttribute("data-currency");
    var ml = +svg.getAttribute("data-ml"), pw = +svg.getAttribute("data-pw");
    var mt = +svg.getAttribute("data-mt"), ph = +svg.getAttribute("data-ph");
    var lo = Math.log(+svg.getAttribute("data-xmin")) / Math.LN10;
    var span = Math.log(+svg.getAttribute("data-xmax")) / Math.LN10 - lo;
    var width = svg.viewBox.baseVal.width;
    var labels = ids.map(function (_, i) {
      return doc.querySelector('.thr-table tr[data-v="' + i + '"] th').textContent;
    });
    function px(x) {
      var f = (Math.log(Math.max(x, 1e-9)) / Math.LN10 - lo) / span;
      return ml + pw * Math.min(Math.max(f, 0), 1);
    }
    function py(p) { return mt + ph * (1 - p); }

    var input = doc.getElementById("thr-in"), help = doc.getElementById("thr-help");
    input.form.addEventListener("submit", function (e) { e.preventDefault(); });
    var helpText = help.textContent;
    var line = doc.querySelector("#lec-thr .thr"), tag = doc.getElementById("lec-thr-l");
    function setThreshold(x) {
      var xp = px(x), flip = xp > ml + pw - 130;
      line.setAttribute("x1", xp); line.setAttribute("x2", xp);
      tag.setAttribute("x", flip ? xp - 5 : xp + 5);
      tag.setAttribute("text-anchor", flip ? "end" : "start");
      tag.textContent = "THRESHOLD " + fmtMoney(x, currency, true).toUpperCase();
      doc.getElementById("thr-lbl").textContent = fmtMoney(x, currency, true);
      ids.forEach(function (id, i) {
        var p = exceedance(points[id], x), c = doc.getElementById("tc" + i);
        c.setAttribute("cx", xp); c.setAttribute("cy", py(p));
        doc.getElementById("tp" + i).textContent = fmtPct(p);
        doc.getElementById("tbar" + i).style.width = (p * 100).toFixed(1) + "%";
      });
    }
    input.addEventListener("input", function () {
      var x = parseAmount(input.value);
      if (!(x > 0)) {
        help.textContent = "Enter an amount such as 750k, 1.5M or 2000000.";
        help.className = "help err";
        return;
      }
      help.textContent = helpText;
      help.className = "help";
      setThreshold(x);
    });

    var hit = doc.getElementById("lec-hit"), cursor = doc.getElementById("lec-hv");
    var readout = doc.getElementById("lec-cursor");
    var idle = readout.textContent;
    hit.style.touchAction = "pan-y";
    function show(ev) {
      var box = svg.getBoundingClientRect();
      var f = ((ev.clientX - box.left) / box.width * width - ml) / pw;
      if (f < 0 || f > 1) return;
      var x = Math.pow(10, lo + f * span), xp = ml + pw * f;
      cursor.setAttribute("x1", xp); cursor.setAttribute("x2", xp);
      cursor.setAttribute("visibility", "visible");
      readout.textContent = "";
      readout.appendChild(doc.createTextNode("At "));
      appendBold(doc, readout, fmtMoney(x, currency, true));
      ids.forEach(function (id, i) {
        readout.appendChild(doc.createTextNode((i ? " / " : ": ") + labels[i] + " "));
        appendBold(doc, readout, fmtPct(exceedance(points[id], x)));
      });
    }
    hit.addEventListener("pointermove", show);
    hit.addEventListener("pointerdown", show);
    hit.addEventListener("pointerleave", function () {
      cursor.setAttribute("visibility", "hidden");
      readout.textContent = idle;
    });
  }

  function initToggle(doc) {
    var radios = doc.querySelectorAll("#hv-toggle input");
    Array.prototype.forEach.call(radios, function (radio) {
      radio.addEventListener("change", function () {
        Array.prototype.forEach.call(doc.querySelectorAll("#hists .hist"), function (h) {
          h.classList.toggle("is-hidden", h.getAttribute("data-variant") !== radio.value);
        });
      });
    });
  }

  function initPrint(doc) {
    var open = [];
    window.addEventListener("beforeprint", function () {
      open = [];
      Array.prototype.forEach.call(doc.querySelectorAll("details"), function (d) { open.push(d.open); d.open = true; });
    });
    window.addEventListener("afterprint", function () {
      Array.prototype.forEach.call(doc.querySelectorAll("details"), function (d, i) { d.open = !!open[i]; });
    });
  }

  if (typeof document !== "undefined") {
    document.documentElement.classList.add("js");
    var chart = document.getElementById("lec");
    if (chart) initCurve(document, chart);
    initToggle(document);
    initPrint(document);
  }
  if (typeof module === "object" && module.exports) {
    module.exports = { fmtMoney: fmtMoney, fmtPct: fmtPct, exceedance: exceedance, parseAmount: parseAmount };
  }
})();
