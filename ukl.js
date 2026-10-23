/* ===== UKREiiF Leaders Group – shared scripts for all Leaders Group pages =====
   Hosted on GitHub Pages and linked from each Event Maker page (with defer). */

(function () {
  // Simple carousel: arrows scroll the track by one item, auto-advances every 5s
  // (pauses while hovered). Swipe/drag works natively.
  document.querySelectorAll('.ukl-carousel').forEach(function (carousel) {
    var track = carousel.querySelector('.ukl-track');
    var paused = false;
    function step() {
      var item = track.children[0];
      return item ? item.offsetWidth + 20 : track.clientWidth;
    }
    function prev() {
      if (track.scrollLeft <= 0) track.scrollLeft = track.scrollWidth; // loop to end
      else track.scrollBy({ left: -step() });
    }
    function next() {
      if (track.scrollLeft + track.clientWidth >= track.scrollWidth - 5) track.scrollLeft = 0; // loop to start
      else track.scrollBy({ left: step() });
    }
    carousel.querySelector('.ukl-prev').addEventListener('click', prev);
    carousel.querySelector('.ukl-next').addEventListener('click', next);
    carousel.addEventListener('mouseenter', function () { paused = true; });
    carousel.addEventListener('mouseleave', function () { paused = false; });
    setInterval(function () { if (!paused) next(); }, 5000);
  });

  // HubSpot "Join Leaders Group" form – only on pages that have <div id="ukl-form">
  if (document.getElementById('ukl-form')) {
    var hs = document.createElement('script');
    hs.src = 'https://js.hsforms.net/forms/embed/v2.js';
    hs.charset = 'utf-8';
    hs.onload = function () {
      hbspt.forms.create({
        portalId: "20215586",
        formId: "b98e3ac1-d35f-482f-ac5c-ea13f1288830",
        region: "na1",
        target: "#ukl-form",
        css: ".hs-form { display: grid !important; grid-template-columns: 1fr 1fr !important; gap: 20px 30px !important; max-width: 100% !important; } .hs_submit { grid-column: 1 / -1 !important; text-align: center !important; } .hs-input { border: 2px solid #1a1a1a !important; border-radius: 15px !important; padding: 18px 15px !important; font-size: 16px !important; width: 100% !important; box-sizing: border-box !important; background: #fff !important; } label { font-weight: 600 !important; font-size: 14px !important; margin-bottom: 8px !important; display: block !important; } .hs-button { background-color: #DC1915 !important; color: #fff !important; border: none !important; border-radius: 0px !important; padding: 18px 50px !important; font-size: 16px !important; font-weight: bold !important; text-transform: uppercase !important; cursor: pointer !important; } @media (max-width: 600px) { .hs-form { grid-template-columns: 1fr !important; } }"
      });
    };
    document.body.appendChild(hs);
  }
})();
