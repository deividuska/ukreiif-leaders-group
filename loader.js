/* ===== UKREiiF Leaders Group – page loader =====
   Event Maker only holds a placeholder:
     <div id="ukl-page" data-page="leaders-group"></div>
     <script src="https://deividuska.github.io/ukreiif-leaders-group/loader.js"></script>
   This fetches pages/<data-page>.html from this repo, puts it into the placeholder,
   then loads ukl.css and ukl.js (carousels + HubSpot form). */

(function () {
  // Bump this whenever ukl.css changes, so browsers fetch the new file instead of a cached one
  var CSS_VERSION = '1.0.2';

  var root = document.getElementById('ukl-page');
  if (!root) return;

  // Load everything from wherever this script lives (GitHub Pages, or a local copy when testing)
  var base = document.currentScript.src.replace(/loader\.js.*$/, '');

  var css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = base + 'ukl.css?v=' + CSS_VERSION;
  document.head.appendChild(css);

  // no-cache: the browser re-checks GitHub each visit, so a push shows up as soon as Pages republishes
  fetch(base + 'pages/' + root.getAttribute('data-page') + '.html', { cache: 'no-cache' })
    .then(function (res) {
      if (!res.ok) throw new Error(res.status);
      return res.text();
    })
    .then(function (html) {
      root.innerHTML = html;
      var js = document.createElement('script');
      js.src = base + 'ukl.js';
      document.body.appendChild(js);
    })
    .catch(function (err) {
      console.error('UKREiiF Leaders Group: could not load page', err);
    });
})();
