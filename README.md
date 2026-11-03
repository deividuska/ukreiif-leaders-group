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

## Sync from WordPress

`sync/sync_wordpress.py` reads the public Leaders Group pages on ukreiif.com and updates
`pages/` to match: guest speakers, guest attendees and member logos. Event titles, dates,
the Join form and the video are not touched.

Run it on your PC from the repo folder (ukreiif.com's firewall blocks GitHub's servers):

```bash
python sync/sync_wordpress.py --dry-run
```

shows what would change without touching anything. Then

```bash
python sync/sync_wordpress.py
```

updates the files in `pages/`. Commit and push as usual to publish.

- **Which events / which parts:** `EVENTS` and `SYNC` at the top of the script.
- **Safety:** if WordPress shows an empty list, fails to load, or our page layout isn't recognised,
  the script stops and changes nothing.
- **People added only here** (not on WordPress) are removed by the next sync. Add them on WordPress.
- **First time only:** `pip install -r sync/requirements.txt`
