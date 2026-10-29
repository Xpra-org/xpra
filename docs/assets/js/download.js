// Download pages: pre-select the visitor's platform and only show the files matching their selection.
// Without javascript, every option is shown.
(function () {
  "use strict";

  const ua = navigator.userAgent || "";
  const uad = navigator.userAgentData;

  function detect_os() {
    const platform = (uad && uad.platform) || navigator.platform || "";
    if (/android|iphone|ipad|ipod|cros/i.test(ua + " " + platform)) {
      return "other";
    }
    if (/win/i.test(platform) || /windows/i.test(ua)) {
      return "windows";
    }
    if (/mac/i.test(platform) || /mac os x/i.test(ua)) {
      // iPads also claim to be a Mac:
      return navigator.maxTouchPoints > 1 ? "other" : "macos";
    }
    if (/linux|x11/i.test(platform + " " + ua) && !/bsd/i.test(ua)) {
      return "linux";
    }
    return "other";
  }

  // landing page: highlight and focus the detected platform, so that "Enter" follows the link
  function select_platform() {
    const os = detect_os();
    const button = document.querySelector('.dl-platforms a[data-os="' + os + '"]');
    if (!button) {
      return;
    }
    button.classList.add("dl-recommended");
    const badge = document.createElement("span");
    badge.className = "dl-badge";
    badge.textContent = "detected";
    button.appendChild(badge);
    button.focus({ preventScroll: true });
  }

  // platform pages: radio groups and selects with a `data-key` drive the selection,
  // `.dl-cond` elements are only shown when all their matching `data-*` attributes agree with it
  const controls = {};

  function get_value(key) {
    const el = controls[key];
    if (el.tagName === "SELECT") {
      return el.value;
    }
    const checked = el.querySelector("input:checked");
    return checked ? checked.value : "";
  }

  function set_value(key, value) {
    const el = controls[key];
    if (el.tagName === "SELECT") {
      if (el.querySelector('option[value="' + value + '"]')) {
        el.value = value;
      }
      return;
    }
    const input = el.querySelector('input[value="' + value + '"]');
    if (input) {
      input.checked = true;
    }
  }

  function update(save) {
    const selection = {};
    Object.keys(controls).forEach(function (key) {
      selection[key] = get_value(key);
    });
    document.querySelectorAll(".dl-cond").forEach(function (el) {
      el.hidden = !Object.keys(selection).every(function (key) {
        const wanted = el.dataset[key];
        return wanted === undefined || wanted.split(" ").indexOf(selection[key]) >= 0;
      });
    });
    if (save) {
      // so the link can be shared or bookmarked:
      const params = new URLSearchParams(location.search);
      Object.keys(selection).forEach(function (key) {
        params.set(key, selection[key]);
      });
      history.replaceState(null, "", "?" + params.toString() + location.hash);
    }
  }

  function guess_arch() {
    if (!uad || !uad.getHighEntropyValues || !controls.arch) {
      return Promise.resolve("");
    }
    return uad.getHighEntropyValues(["architecture"]).then(function (values) {
      if (values.architecture === "arm") {
        return "arm64";
      }
      if (values.architecture === "x86") {
        return "x86_64";
      }
      return "";
    }).catch(function () {
      return "";
    });
  }

  function guess_linux() {
    if (!controls.method) {
      return;
    }
    if (/ubuntu|debian/i.test(ua)) {
      set_value("method", "deb");
      if (/ubuntu/i.test(ua)) {
        // we can't tell which version, so pick the most recent one:
        const option = Array.from(controls.deb.options).find(function (o) {
          return /ubuntu/i.test(o.text);
        });
        if (option) {
          set_value("deb", option.value);
        }
      }
    }
    else if (/fedora/i.test(ua)) {
      set_value("method", "rpm");
      set_value("rpm", "fedora");
    }
  }

  function init_selection() {
    document.querySelectorAll("[data-key]").forEach(function (el) {
      controls[el.dataset.key] = el;
      el.addEventListener("change", function () {
        update(true);
      });
    });
    if (!Object.keys(controls).length) {
      return;
    }
    const params = new URLSearchParams(location.search);
    guess_linux();
    Object.keys(controls).forEach(function (key) {
      if (params.has(key)) {
        set_value(key, params.get(key));
      }
    });
    update(false);
    if (!params.has("arch")) {
      guess_arch().then(function (arch) {
        if (arch) {
          set_value("arch", arch);
          update(false);
        }
      });
    }
  }

  select_platform();
  init_selection();
})();
