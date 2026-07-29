(function () {
  "use strict";

  var DEVICES = [
    {
      id: 1,
      name: "Living Room Fan",
      commands: [
        { label: "☀", cmd: "light", style: "btn-light" },
        { label: "1", cmd: "speed1", style: "btn-speed" },
        { label: "2", cmd: "speed2", style: "btn-speed" },
        { label: "3", cmd: "speed3", style: "btn-speed" },
        { label: "Off", cmd: "off", style: "btn-off" },
      ],
    },
    {
      id: 2,
      name: "Stairs Fan",
      commands: [
        { label: "☀", cmd: "light", style: "btn-light" },
        { label: "1", cmd: "speed1", style: "btn-speed" },
        { label: "2", cmd: "speed2", style: "btn-speed" },
        { label: "3", cmd: "speed3", style: "btn-speed" },
        { label: "Off", cmd: "off", style: "btn-off" },
      ],
    },
  ];

  var toastEl = document.getElementById("toast");
  var toastTimer = null;

  function showToast(msg, isError) {
    toastEl.textContent = msg;
    toastEl.className = "toast visible" + (isError ? " error" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toastEl.className = "toast";
    }, 2000);
  }

  function sendCommand(fanId, cmd, btn) {
    if (btn.classList.contains("sending")) return;
    btn.classList.add("sending");
    btn.classList.remove("sent");

    fetch("/api/fan/" + fanId + "/" + cmd)
      .then(function (res) {
        if (!res.ok) throw new Error(res.status);
        btn.classList.add("sent");
        setTimeout(function () {
          btn.classList.remove("sent");
        }, 1500);
      })
      .catch(function () {
        showToast("Could not reach fan controller", true);
      })
      .finally(function () {
        btn.classList.remove("sending");
      });
  }

  function postTransmit(payload) {
    return fetch("/api/transmit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(function (res) {
      if (!res.ok) throw new Error(res.status);
    });
  }

  function sendLight(light, cmd, btn) {
    if (btn.classList.contains("sending")) return;
    btn.classList.add("sending");
    btn.classList.remove("sent");

    postTransmit(light.commands[cmd])
      .then(function () {
        btn.classList.add("sent");
        setTimeout(function () {
          btn.classList.remove("sent");
        }, 1500);
      })
      .catch(function () {
        showToast("Could not reach light controller", true);
      })
      .finally(function () {
        btn.classList.remove("sending");
      });
  }

  // The ESP8266 busy-waits during a transmit (its HTTP loop is not
  // running), so "All" must send the four commands one at a time —
  // concurrent requests stall against the single-threaded server.
  function sendAll(lights, cmd, btn) {
    if (btn.classList.contains("sending")) return;
    btn.classList.add("sending");
    btn.classList.remove("sent");

    var chain = Promise.resolve();
    lights.forEach(function (light) {
      chain = chain.then(function () {
        return postTransmit(light.commands[cmd]);
      });
    });

    chain
      .then(function () {
        btn.classList.add("sent");
        setTimeout(function () {
          btn.classList.remove("sent");
        }, 1500);
      })
      .catch(function () {
        showToast("Could not reach light controller", true);
      })
      .finally(function () {
        btn.classList.remove("sending");
      });
  }

  function buildLightsCard(lights) {
    var card = document.createElement("div");
    card.className = "remote";

    var title = document.createElement("div");
    title.className = "remote-name";
    title.textContent = "Lights";
    card.appendChild(title);

    var controls = document.createElement("div");
    controls.className = "remote-controls";

    lights.forEach(function (light) {
      var row = document.createElement("div");
      row.className = "btn-row light-row";

      var name = document.createElement("span");
      name.className = "light-name";
      name.textContent = light.label;
      row.appendChild(name);

      [["on", "On", "btn-light"], ["off", "Off", "btn-off"]].forEach(function (spec) {
        var btn = document.createElement("button");
        btn.className = "btn " + spec[2];
        btn.textContent = spec[1];
        btn.setAttribute("aria-label", light.label + " lamp " + spec[0]);
        btn.addEventListener("click", function () {
          sendLight(light, spec[0], btn);
        });
        row.appendChild(btn);
      });

      controls.appendChild(row);
    });

    var allRow = document.createElement("div");
    allRow.className = "btn-row light-row";
    [["on", "All On", "btn-light"], ["off", "All Off", "btn-off"]].forEach(function (spec) {
      var btn = document.createElement("button");
      btn.className = "btn " + spec[2];
      btn.textContent = spec[1];
      btn.setAttribute("aria-label", "all lamps " + spec[0]);
      btn.addEventListener("click", function () {
        sendAll(lights, spec[0], btn);
      });
      allRow.appendChild(btn);
    });
    controls.appendChild(allRow);

    card.appendChild(controls);
    return card;
  }

  function buildRemote(device) {
    var card = document.createElement("div");
    card.className = "remote";

    var title = document.createElement("div");
    title.className = "remote-name";
    title.textContent = device.name;
    card.appendChild(title);

    var controls = document.createElement("div");
    controls.className = "remote-controls";

    var lightRow = document.createElement("div");
    lightRow.className = "btn-row";

    var speedRow = document.createElement("div");
    speedRow.className = "btn-row";

    var offRow = document.createElement("div");
    offRow.className = "btn-row";

    device.commands.forEach(function (c) {
      var btn = document.createElement("button");
      btn.className = "btn " + c.style;
      btn.textContent = c.label;
      btn.setAttribute("aria-label", device.name + " " + c.cmd);
      btn.addEventListener("click", function () {
        sendCommand(device.id, c.cmd, btn);
      });

      if (c.style === "btn-light") lightRow.appendChild(btn);
      else if (c.style === "btn-off") offRow.appendChild(btn);
      else speedRow.appendChild(btn);
    });

    controls.appendChild(lightRow);
    controls.appendChild(speedRow);
    controls.appendChild(offRow);
    card.appendChild(controls);

    return card;
  }

  var main = document.getElementById("remotes");
  DEVICES.forEach(function (d) {
    main.appendChild(buildRemote(d));
  });

  // devices.json is generated by radiofrequency/scripts/export_web_devices.py
  // (never hand-edit); each button's payload is POSTed to /api/transmit as-is.
  fetch("devices.json")
    .then(function (res) {
      if (!res.ok) throw new Error(res.status);
      return res.json();
    })
    .then(function (bundle) {
      if (bundle.lights && bundle.lights.length) {
        main.appendChild(buildLightsCard(bundle.lights));
      }
    })
    .catch(function () {
      showToast("Could not load light definitions", true);
    });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js");
  }
})();
