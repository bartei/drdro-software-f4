/* drDRO docs — live GitHub release fetch for the flashing wizard.
   Populates any element:  <div class="release" data-repo="owner/name" data-match=".img.zst">
   with the latest stable (non-prerelease) release's version, date, asset size,
   download link and (best-effort) SHA-256. Fails gracefully to a releases link. */
(function () {
  "use strict";

  function fmtBytes(n) {
    if (!n && n !== 0) return "—";
    var u = ["B", "KB", "MB", "GB"], i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return n.toFixed(i ? 1 : 0) + " " + u[i];
  }
  function fmtDate(s) {
    try { return new Date(s).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }); }
    catch (e) { return s; }
  }
  function set(root, sel, fn) {
    var el = root.querySelector(sel);
    if (el) fn(el);
  }

  function render(root, rel) {
    var repo = root.getAttribute("data-repo");
    var match = root.getAttribute("data-match") || "";
    var asset = (rel.assets || []).filter(function (a) { return a.name.indexOf(match) !== -1; })[0]
             || (rel.assets || [])[0];
    var sums = (rel.assets || []).filter(function (a) { return /sha256|SHA256/i.test(a.name); })[0];

    set(root, ".rel-status", function (el) { el.style.display = "none"; });
    set(root, ".rel-body", function (el) { el.style.display = ""; });
    set(root, ".ver", function (el) { el.textContent = rel.tag_name || rel.name; });
    set(root, ".rel-date", function (el) { el.textContent = fmtDate(rel.published_at); });
    set(root, ".rel-size", function (el) { el.textContent = asset ? fmtBytes(asset.size) : "—"; });
    set(root, ".rel-name", function (el) { el.textContent = asset ? asset.name : "—"; });
    set(root, ".rel-download", function (el) {
      if (asset) { el.href = asset.browser_download_url; el.removeAttribute("aria-disabled"); }
      else { el.href = rel.html_url; }
    });
    set(root, ".rel-notes", function (el) { el.href = rel.html_url; });

    // Best-effort SHA-256 (may be blocked by CORS on the asset host — that's fine).
    if (sums) {
      set(root, ".rel-hash", function (el) {
        el.innerHTML = 'SHA-256: <a href="' + sums.browser_download_url + '">' + sums.name + "</a>";
        fetch(sums.browser_download_url).then(function (r) { return r.ok ? r.text() : null; }).then(function (txt) {
          if (!txt || !asset) return;
          var line = txt.split("\n").filter(function (l) { return l.indexOf(asset.name) !== -1; })[0];
          if (line) el.innerHTML = "SHA-256 &nbsp;<code>" + line.trim().split(/\s+/)[0] + "</code>";
        }).catch(function () {});
      });
    }
  }

  function fail(root) {
    var repo = root.getAttribute("data-repo");
    set(root, ".rel-status", function (el) {
      el.innerHTML =
        "Couldn't reach the GitHub API (offline or rate-limited). " +
        'Grab the latest image from the <a href="https://github.com/' + repo + '/releases/latest">releases page</a>.';
    });
    set(root, ".rel-download", function (el) { el.href = "https://github.com/" + repo + "/releases/latest"; });
    set(root, ".rel-notes", function (el) { el.href = "https://github.com/" + repo + "/releases"; });
  }

  document.querySelectorAll(".release[data-repo]").forEach(function (root) {
    var repo = root.getAttribute("data-repo");
    // /releases/latest returns the newest non-prerelease, non-draft release.
    fetch("https://api.github.com/repos/" + repo + "/releases/latest", {
      headers: { "Accept": "application/vnd.github+json" }
    })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (rel) { render(root, rel); })
      .catch(function () { fail(root); });
  });

  // Inline "latest version" badges: <span class="gh-latest" data-repo="owner/name"></span>
  document.querySelectorAll(".gh-latest[data-repo]").forEach(function (el) {
    var repo = el.getAttribute("data-repo");
    fetch("https://api.github.com/repos/" + repo + "/releases/latest")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (rel) { if (rel && rel.tag_name) el.textContent = rel.tag_name; })
      .catch(function () {});
  });
})();
