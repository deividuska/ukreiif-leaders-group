# ukreiif-leaders-group

Shared styles and scripts for the UKREiiF Leaders Group pages on Event Maker
(holding page, November, December, February…).

| File | What it does |
|---|---|
| `ukl.css` | All styles. Scoped to `.ukl`, plus the rule that removes Event Maker's container padding. |
| `ukl.js` | Auto-playing carousels (attendees, member organisations) and the HubSpot "Join Leaders Group" form. |

Served by GitHub Pages. Each Event Maker page links to them inside its codeit container:

```html
<link rel="stylesheet" href="https://deividuska.github.io/ukreiif-leaders-group/ukl.css">
...
<script src="https://deividuska.github.io/ukreiif-leaders-group/ukl.js" defer></script>
```

Edit a file, commit and push: every page picks up the change within a few minutes
(GitHub Pages caches for about 10 minutes).

## Hosting whole pages (loader)

Page HTML can also live here in `pages/`. Event Maker then only needs this, pasted once:

```html
<div class='container ukl-full {{ settings.spacing }}' data-section-id='{{ section.id }}' data-section-type='codeit'>
  <div id="ukl-page" data-page="leaders-group"></div>
  <script src="https://deividuska.github.io/ukreiif-leaders-group/loader.js"></script>
</div>
```

`data-page` is the file name in `pages/` without `.html`. `loader.js` fetches that page and loads `ukl.css` and `ukl.js`.
