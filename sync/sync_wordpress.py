"""Sync Leaders Group content from ukreiif.com (WordPress) into pages/.

Reads the public WordPress pages, compares event details (title, date, venue),
guest speakers, guest attendees, member logos and the landing page's event cards
with our pages, and rewrites only the items that changed.
Run from anywhere:

    python sync/sync_wordpress.py              # update pages/ and print a summary
    python sync/sync_wordpress.py --dry-run    # only print what would change
"""
import argparse
import html
import os
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from bs4 import BeautifulSoup

WP = 'https://www.ukreiif.com'
MEMBERS_URL = WP + '/leaders-group-events/'
LANDING_URL = WP + '/leaders-group-2026/'

# Which WordPress event feeds which of our pages
EVENTS = [
    {'name': 'November', 'wp': '/leaders-group-events/leaders-group-november/', 'page': 'leaders-group-november'},
    {'name': 'December', 'wp': '/leaders-group-events/leaders-group-december/', 'page': 'leaders-group-december'},
    {'name': 'February', 'wp': '/leaders-group-events/leaders-group-february-2/', 'page': 'leaders-group-february'},
    {'name': 'Glasgow', 'wp': '/leaders-group-events/leaders-group-february-3/', 'page': 'leaders-group-glasgow'},
]

# Switch parts on (True) or off (False). Anything off is left exactly as it is.
SYNC = {
    'details': True,     # event label, title, date and venue (event pages and main page cards)
    'cards': True,       # which event cards the main page shows, and in what order
    'speakers': True,
    'attendees': True,
    'members': True,
}

MAIN_PAGE = 'leaders-group'
PAGES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pages')


class Stop(Exception):
    """Something looks wrong: change nothing and fail the run."""


# ---------- helpers ----------

def fetch(url):
    # The query string skips the site's page cache, so we always see the latest version
    req = urllib.request.Request(f'{url}?sync={int(time.time())}',
                                 headers={'User-Agent': 'ukreiif-leaders-group-sync'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        by = 'Cloudflare' if 'cloudflare' in (e.headers.get('Server') or '').lower() else e.headers.get('Server') or 'the site'
        raise Stop(f'{url} answered {e.code} ({e.reason}), blocked by {by}'
                   + (f', ray id {e.headers["cf-ray"]}' if e.headers.get('cf-ray') else ''))
    except urllib.error.URLError as e:
        raise Stop(f'{url} could not be reached: {e.reason}')


def text(s):
    """Decoded text with single spaces."""
    return ' '.join(html.unescape(s).split())


def words(el):
    """Visible text of a WordPress element with single spaces ('' if it's missing)."""
    return ' '.join(el.get_text(' ').split()) if el else ''


def key(s):
    """Text for comparing: ignores case, spacing, curly vs straight quotes."""
    s = text(s).translate(str.maketrans({'‘': "'", '’': "'", '“': '"', '”': '"'}))
    return s.lower()


def esc(s):
    """Text to HTML the way our pages write it: escaped, non-ASCII as entities."""
    return html.escape(s).encode('ascii', 'xmlcharrefreplace').decode()


def img_key(url):
    """Same picture on both sites: file name without folder, size, extension or Event Maker id."""
    f = url.rsplit('/', 1)[-1].lower()
    f = re.sub(r'_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '', f)
    while re.search(r'\.(png|jpe?g|webp|svg|gif)$', f):
        f = re.sub(r'\.(png|jpe?g|webp|svg|gif)$', '', f)
    f = re.sub(r'-\d+x\d+$', '', f)
    return re.sub(r'[^a-z0-9]', '', f).replace('resized', '')


def logo_name(url):
    """A readable name for a member logo that has no alt text on WordPress."""
    f = re.sub(r'(?i)\.(png|jpe?g|webp|svg|gif)$', '', url.rsplit('/', 1)[-1])
    f = re.sub(r'-\d+x\d+$', '', f)
    f = re.sub(r'(?i)[-_]?(resized|logo)', '', f)
    return ' '.join(re.split(r'[-_]+', f)).strip()


def pick(ours, wp, field):
    """Keep our copy of an image when WordPress still shows the same file."""
    if ours and ours[field] and wp[field] and img_key(ours[field]) == img_key(wp[field]):
        return ours[field]
    return wp[field]


# ---------- read WordPress ----------

def first_img(box, skip_cls=None):
    """The first real image in box. Lazy loading adds a copy in <noscript> and a blank
    placeholder pointing at data-src, so one picture can show up as several <img> tags."""
    if not box:
        return ''
    for img in box.find_all('img'):
        if skip_cls and img.find_parent(class_=skip_cls):
            continue
        src = img.get('data-src') or img.get('src', '')
        if src and not src.startswith('data:'):
            return src
    return ''


def wp_person(box, details, logo_cls):
    # Search the whole card: WordPress markup sometimes nests the text inside the photo tag
    ps = [' '.join(p.get_text(' ').split()) for p in details.find_all('p')
          if not p.find_parent(class_=logo_cls)]
    return {
        'name': ps[0] if ps else '',
        'title': ps[1] if len(ps) > 1 else '',
        'org': ps[2] if len(ps) > 2 else '',
        'photo': first_img(box, logo_cls),
        'logo': first_img(box.select_one(f'.{logo_cls}')),
        'bio': '',
    }


def check_names(url, label, people):
    """People are matched by name, so every card needs one and no name may appear twice."""
    names = [key(p['name']) for p in people]
    if '' in names:
        raise Stop(f'{url}: a {label} card has no name')
    twice = sorted({p['name'] for p in people if names.count(key(p['name'])) > 1})
    if twice:
        raise Stop(f'{url}: {label} listed twice: {", ".join(twice)}')


def read_wp_event(url):
    soup = BeautifulSoup(fetch(url), 'html.parser')
    if not soup.select_one('.leaders-group-event-info-block'):
        raise Stop(f'{url} no longer looks like a Leaders Group event page')
    speakers = []
    for card in soup.select('.leaders-group-speaker-card'):
        left = card.select_one('.leaders-group-speaker-left')
        p = wp_person(left, left, 'speaker-company-logo')
        quote = card.select_one('.leaders-group-speaker-quote')
        if quote:
            p['bio'] = ' '.join(' '.join(x.get_text(' ').split()) for x in quote.find_all('p'))
        speakers.append(p)
    attendees = [wp_person(c, c.select_one('.guest-attendee-details'), 'guest-attendee-company-logo')
                 for c in soup.select('.leaders-group-guest-attendee-card')]
    check_names(url, 'speaker', speakers)
    check_names(url, 'attendee', attendees)
    info = soup.select_one('.leaders-group-event-info-block')
    where = info.select('.leaders-group-event-details p')
    details = {
        'label': words(info.select_one('.leaders-group-event-header')),
        'title': words(info.select_one('.leaders-group-event-subheader')),
        'date': words(where[0]) if where else '',
        'venue': words(where[1]) if len(where) > 1 else '',
    }
    if not details['label']:
        raise Stop(f'{url}: the event has no heading')
    return speakers, attendees, details


def read_wp_landing():
    """The landing page's event cards, in order: the Next event first, then the others."""
    soup = BeautifulSoup(fetch(LANDING_URL), 'html.parser')
    nxt = soup.select_one('.leaders-group-next-event-card')
    if not nxt:
        raise Stop(f'{LANDING_URL} no longer shows a Next event card')
    cards = [(nxt, '.next-event-cta a')] + [(c, '.featured-event-cta a') for c in soup.select('.featured-event-card')]
    out = []
    for card, cta in cards:
        d = {
            'label': words(card.find('h3')),
            'title': words(card.select_one('.event-subheader')),
            'date': words(card.select_one('.event-datetime')),
            'venue': words(card.select_one('.event-venue')),
        }
        a = card.select_one(cta)
        href = a.get('href', '') if a else ''
        if not href:
            raise Stop(f'{LANDING_URL}: the card "{d["label"]}" has no Details button link')
        path = urlparse(href).path.rstrip('/')
        ev = next((e for e in EVENTS if e['wp'].rstrip('/') == path), None)
        if ev is None:
            raise Stop(f'WordPress shows a new event: {d["label"]} ({href}). There is no 2027 page for it yet. '
                       f'Create the 2027 page and add it to EVENTS at the top of this script, then run again')
        if any(e is ev for e, _ in out):
            raise Stop(f'{LANDING_URL}: the event {ev["name"]} has two cards')
        out.append((ev, d))
    return out


def read_wp_members():
    soup = BeautifulSoup(fetch(MEMBERS_URL), 'html.parser')
    carousel = soup.select_one('.lg-member-orgs-carousel')
    if not carousel:
        raise Stop(f'{MEMBERS_URL} no longer shows a Member Organisations carousel')
    out = []
    for item in carousel.select('.lg-org-item'):
        src = first_img(item)
        if not src:
            continue
        span = item.find('span')
        alt = next((i.get('alt') for i in item.find_all('img') if i.get('alt')), '')
        name = (alt or (span.get('title') if span else '') or '').strip() or logo_name(src)
        out.append({'src': src, 'alt': name})
    if len(out) < 10:
        raise Stop(f'WordPress shows only {len(out)} member logos, expected many more')
    return out


# ---------- read and write our pages ----------

def parse_ours(raw):
    spans = re.findall(r'<span>(.*?)</span>', raw)
    bio = re.search(r'<p class="ukl-bio">(.*?)</p>', raw, re.S)
    photo = re.search(r'<img class="ukl-photo" src="([^"]*)"', raw)
    logo = re.search(r'<img class="ukl-logo" src="([^"]*)"', raw)
    name = re.search(r'<strong>(.*?)</strong>', raw)
    return {
        'raw': raw,
        'name': text(name.group(1)) if name else '',
        'title': text(spans[0]) if spans else '',
        'org': text(spans[1]) if len(spans) > 1 else '',
        'photo': html.unescape(photo.group(1)) if photo else '',
        'logo': html.unescape(logo.group(1)) if logo else '',
        'bio': text(bio.group(1)) if bio else '',
    }


def render_speaker(w, o):
    lines = ['            <div class="ukl-speaker">',
             '              <div>',
             f'                <img class="ukl-photo" src="{esc(pick(o, w, "photo"))}" alt="{esc(w["name"])}">',
             '                <div class="ukl-speaker-info">',
             f'                  <strong>{esc(w["name"])}</strong>']
    lines += [f'                  <span>{esc(t)}</span>' for t in (w['title'], w['org']) if t]
    if w['logo']:
        lines.append(f'                  <img class="ukl-logo" src="{esc(pick(o, w, "logo"))}" alt="{esc(w["org"])}">')
    lines += ['                </div>',
              '              </div>',
              '              <div>',
              '                <div class="ukl-quote" aria-hidden="true">&ldquo;</div>']
    if w['bio']:
        lines.append(f'                <p class="ukl-bio">{esc(w["bio"])}</p>')
    lines += ['              </div>',
              '            </div>']
    return '\n'.join(lines)


def render_attendee(w, o):
    lines = ['            <div class="ukl-attendee">',
             f'              <img class="ukl-photo" src="{esc(pick(o, w, "photo"))}" alt="{esc(w["name"])}">',
             f'              <strong>{esc(w["name"])}</strong>']
    lines += [f'              <span>{esc(t)}</span>' for t in (w['title'], w['org']) if t]
    if w['logo']:
        lines.append(f'              <img class="ukl-logo" src="{esc(pick(o, w, "logo"))}" alt="{esc(w["org"])}">')
    lines.append('            </div>')
    return '\n'.join(lines)


def render_card_person(indent):
    """Main page card: title and organisation share one line."""
    def render(w, o):
        info = ', '.join(t for t in (w['title'], w['org']) if t)
        s = (f'{indent}<div class="ukl-person"><img class="ukl-photo" src="{esc(pick(o, w, "photo"))}" alt="{esc(w["name"])}">'
             f'<strong>{esc(w["name"])}</strong><span>{esc(info)}</span>')
        if w['logo']:
            s += f'<img class="ukl-logo" src="{esc(pick(o, w, "logo"))}" alt="{esc(w["org"])}">'
        return s + '</div>'
    return render


def changes(o, w, bio, combined):
    out = []
    if combined:
        if key(o['title']) != key(', '.join(t for t in (w['title'], w['org']) if t)):
            out.append('title')
    else:
        if key(o['title']) != key(w['title']):
            out.append('title')
        if key(o['org']) != key(w['org']):
            out.append('organisation')
    if img_key(o['photo']) != img_key(w['photo']):
        out.append('photo')
    if img_key(o['logo']) != img_key(w['logo']):
        out.append('logo')
    if bio and key(o['bio']) != key(w['bio']):
        out.append('bio')
    return out


def merge_people(label, ours, theirs, render, bio=False, combined=False):
    """Rebuild a list in WordPress order, keeping our HTML for anyone unchanged."""
    if ours and not theirs:
        raise Stop(f'{label}: WordPress shows nobody, but we list {len(ours)}. Not emptying the list')
    by_name = {key(o['name']): o for o in ours}
    if len(by_name) != len(ours):
        raise Stop(f'{label}: our page lists someone twice, so names cannot be matched safely')
    out, notes = [], []
    for w in theirs:
        o = by_name.get(key(w['name']))
        if o is None:
            notes.append(f'{label}: added **{w["name"]}**')
            out.append(render(w, None))
            continue
        diff = changes(o, w, bio, combined)
        if diff:
            notes.append(f'{label}: changed **{w["name"]}** ({", ".join(diff)})')
            out.append(render(w, o))
        else:
            out.append(o['raw'])
    wp_names = {key(w['name']) for w in theirs}
    notes += [f'{label}: removed **{o["name"]}**' for o in ours if key(o['name']) not in wp_names]
    both_ours = [key(o['name']) for o in ours if key(o['name']) in wp_names]
    both_wp = [key(w['name']) for w in theirs if key(w['name']) in by_name]
    if both_ours != both_wp:
        notes.append(f'{label}: order changed')
    if notes and len(ours) != len(theirs):
        notes.append(f'{label}: {len(ours)} -> {len(theirs)}')
    return out, notes


def merge_members(ours, theirs):
    """Members are matched by logo file (WordPress has no names), falling back to our alt text."""
    out, notes, kept = [], [], []
    for w in theirs:
        k = img_key(w['src'])
        o = next((o for o in ours if id(o) not in kept and
                  k in (img_key(o['src']), re.sub(r'[^a-z0-9]', '', o['alt'].lower()).replace('resized', ''))), None)
        if o:
            kept.append(id(o))
            out.append(o['raw'])
        else:
            notes.append(f'added **{w["alt"]}**')
            out.append(f'              <div class="ukl-member"><img src="{esc(w["src"])}" alt="{esc(w["alt"])}"></div>')
    notes += [f'removed **{o["alt"]}**' for o in ours if id(o) not in kept]
    if [id(o) for o in ours if id(o) in kept] != kept:
        notes.append('order changed')
    if notes and len(ours) != len(theirs):
        notes.append(f'{len(ours)} -> {len(theirs)} logos')
    return out, notes


def replace_items(page, where, start, item, end, merge, pos=0, endpos=None):
    """Find a list in our page, check we understand its layout, then swap its items."""
    m = re.compile(start + r'(.*?)' + end, re.S).search(page, pos, len(page) if endpos is None else endpos)
    if not m:
        return page, None
    region = m.group(1)
    items = re.findall(item, region, re.S)
    if '\n'.join(items) != region:
        raise Stop(f'{where}: layout not recognised, so it was left alone')
    try:
        new, notes = merge(items)
    except Stop as e:
        raise Stop(f'{where}: {e}')
    return page[:m.start(1)] + '\n'.join(new) + page[m.end(1):], notes


END_LIST = r'\n {6}</div>\n {4}</div>\n {2}</section>'
END_TRACK = r'\n {12}</div>\n {12}<button class="ukl-arrow ukl-next"'


def field(name, ours, wp, notes):
    """Keep our HTML when the text is the same, otherwise take WordPress's and note it."""
    if key(ours) == key(wp):
        return ours
    if ours:
        notes.append(f'{name}: "{text(ours)}" -> "{wp}"' if wp else f'{name}: removed "{text(ours)}"')
    else:
        notes.append(f'{name}: added "{wp}"')
    return esc(wp)


EVENT_HEAD = re.compile(r'(<section class="ukl-event-head">\n {4}<div class="ukl-wrap">\n)(.*?)(\n {4}</div>\n {2}</section>)', re.S)
EVENT_HEAD_IN = re.compile(r' {6}<h4>(?P<label>.*)</h4>\n(?: {6}<h1>(?P<title>.*)</h1>\n)?'
                           r' {6}<p>(?P<date>.*)</p>\n {6}<p>(?P<venue>.*)</p>')
DETAILS = ('label', 'title', 'date', 'venue')


def sync_event_head(page, ev, d):
    m = EVENT_HEAD.search(page)
    o = EVENT_HEAD_IN.fullmatch(m.group(2)) if m else None
    if not o:
        raise Stop(f'{ev["name"]} page header: layout not recognised, so it was left alone')
    notes = []
    v = {f: field(f'Event {f}', o.group(f) or '', d[f], notes) for f in DETAILS}
    lines = [f'      <h4>{v["label"]}</h4>']
    if v['title']:
        lines.append(f'      <h1>{v["title"]}</h1>')
    lines += [f'      <p>{v["date"]}</p>', f'      <p>{v["venue"]}</p>']
    return page[:m.start(2)] + '\n'.join(lines) + page[m.end(2):], notes


def sync_event_page(page, ev, speakers, attendees, details):
    notes = []
    if SYNC['details']:
        page, n = sync_event_head(page, ev, details)
        notes += n
    if SYNC['speakers']:
        page, n = replace_items(page, f'{ev["name"]} page speakers', r'<div class="ukl-speakers">\n',
                                r' {12}<div class="ukl-speaker">\n.*?\n {12}</div>', END_LIST,
                                lambda items: merge_people('Guest speakers', [parse_ours(i) for i in items],
                                                           speakers, render_speaker, bio=True))
        notes += n or []
    if SYNC['attendees']:
        page, n = replace_items(page, f'{ev["name"]} page attendees', r'<div class="ukl-attendees">\n',
                                r' {12}<div class="ukl-attendee">\n.*?\n {12}</div>', END_LIST,
                                lambda items: merge_people('Guest attendees', [parse_ours(i) for i in items],
                                                           attendees, render_attendee))
        notes += n or []
    return page, notes


# ---------- main page event cards ----------

NEXT_SECTION = re.compile(r'(<h2 class="ukl-title">The Next UKREiiF Leaders Group</h2>\n)(.*?)'
                          r'(\n {6}</div>\n {4}</div>\n {2}</section>)', re.S)
MORE_SECTION = re.compile(r'(<div class="ukl-panel ukl-two">\n)(.*?)(\n {6}</div>\n {4}</div>\n {2}</section>)', re.S)
CARD = re.compile(r' {8}<div class="ukl-card">\n.*?\n {8}</div>(?=\n|$)', re.S)
CARD_IN = re.compile(
    r' {8}<div class="ukl-card">\n'
    r' {10}<h4>(?P<label>.*)</h4>\n'
    r'(?: {10}<h3>(?P<title>.*)</h3>\n)?'
    r' {10}<p class="ukl-date">(?P<date>.*)</p>\n'
    r' {10}<p class="ukl-venue">(?P<venue>.*)</p>\n'
    r'(?: {10}<p class="ukl-label">Guest Speakers</p>\n {10}<div class="ukl-people">\n'
    r'(?P<speakers>(?: {12}<div class="ukl-person">.*\n)*) {10}</div>\n)?'
    r'(?: {10}<p class="ukl-label">Guest Attendees</p>\n {10}<div class="ukl-carousel">\n'
    r' {12}<button class="ukl-arrow ukl-prev" type="button" aria-label="Previous">&#8249;</button>\n'
    r' {12}<div class="ukl-track">\n(?P<attendees>(?: {14}<div class="ukl-person">.*\n)*) {12}</div>\n'
    r' {12}<button class="ukl-arrow ukl-next" type="button" aria-label="Next">&#8250;</button>\n {10}</div>\n)?'
    r' {10}<div class="ukl-center"><a class="ukl-btn" href="/(?P<page>[^"]*)">Details &amp; Attendee List &gt;</a></div>\n'
    r' {8}</div>')


def read_main_cards(page):
    """Our main page's event cards: the Next card, then the others, each checked against the known layout."""
    nxt, more = NEXT_SECTION.search(page), MORE_SECTION.search(page)
    if not nxt or not more:
        raise Stop('Main page: event card sections not found, so they were left alone')
    cards = []
    for m, joiner, edge in ((nxt, '\n', ''), (more, '\n\n', '\n')):
        raws = CARD.findall(m.group(2))
        if edge + joiner.join(raws) + edge != m.group(2):
            raise Stop('Main page: event card layout not recognised, so it was left alone')
        for raw in raws:
            c = CARD_IN.fullmatch(raw)
            if not c:
                raise Stop('Main page: an event card layout is not recognised, so it was left alone')
            card = {f: c.group(f) or '' for f in DETAILS + ('page',)}
            for f in ('speakers', 'attendees'):
                card[f] = [parse_ours(l) for l in (c.group(f) or '').split('\n') if l]
            cards.append(card)
    if len(cards) != len({c['page'] for c in cards}):
        raise Stop('Main page: two event cards link to the same page')
    return nxt, more, cards


def render_main_card(c, is_next):
    lines = ['        <div class="ukl-card">', f'          <h4>{c["label"]}</h4>']
    if c['title']:
        lines.append(f'          <h3>{c["title"]}</h3>')
    lines += [f'          <p class="ukl-date">{c["date"]}</p>', f'          <p class="ukl-venue">{c["venue"]}</p>']
    if c['speakers']:
        lines += ['          <p class="ukl-label">Guest Speakers</p>', '          <div class="ukl-people">']
        lines += c['speakers'] + ['          </div>']
    if is_next and c['attendees']:
        lines += ['          <p class="ukl-label">Guest Attendees</p>',
                  '          <div class="ukl-carousel">',
                  '            <button class="ukl-arrow ukl-prev" type="button" aria-label="Previous">&#8249;</button>',
                  '            <div class="ukl-track">']
        lines += c['attendees']
        lines += ['            </div>',
                  '            <button class="ukl-arrow ukl-next" type="button" aria-label="Next">&#8250;</button>',
                  '          </div>']
    lines += [f'          <div class="ukl-center"><a class="ukl-btn" href="/{c["page"]}">Details &amp; Attendee List &gt;</a></div>',
              '        </div>']
    return '\n'.join(lines)


def sync_main_page(page, landing, data):
    """Rebuild the main page's event cards to follow the WordPress landing page:
    which events, their order (first = The Next Leaders Group), details, people and buttons."""
    nxt, more, cards = read_main_cards(page)
    ours = {c['page']: c for c in cards}
    wp = {ev['page']: (ev, d) for ev, d in landing}
    if SYNC['cards']:
        order = list(landing)
    else:
        order = []
        for c in cards:
            ev = next((e for e in EVENTS if e['page'] == c['page']), None)
            if ev is None:
                raise Stop(f'Main page: the card linking to /{c["page"]} is not in EVENTS')
            order.append((ev, wp[c['page']][1] if c['page'] in wp else None))
    report, out = {}, []
    for i, (ev, d) in enumerate(order):
        notes = report.setdefault(f'Main page, {ev["name"]} card', [])
        is_next = i == 0
        o = ours.get(ev['page'])
        new = o is None
        o = o or {'label': '', 'title': '', 'date': '', 'venue': '', 'speakers': [], 'attendees': []}
        speakers, attendees = data[ev['page']]
        c = {'page': ev['page']}
        for f in DETAILS:
            c[f] = field(f, o[f], d[f], [] if new else notes) if d and (SYNC['details'] or new) else o[f]
        if SYNC['speakers'] or new:
            c['speakers'], n = merge_people('Guest speakers', o['speakers'], speakers,
                                            render_card_person(' ' * 12), combined=True)
            notes += [] if new else n
        else:
            c['speakers'] = [p['raw'] for p in o['speakers']]
        if is_next and (SYNC['attendees'] or not o['attendees']):
            c['attendees'], n = merge_people('Guest attendees', o['attendees'], attendees,
                                             render_card_person(' ' * 14), combined=True)
            if o['attendees']:
                notes += n
            elif c['attendees'] and not new:
                notes.append(f'now The Next Leaders Group: Guest Attendees carousel added ({len(c["attendees"])})')
        else:
            c['attendees'] = [p['raw'] for p in o['attendees']] if is_next else []
            if o['attendees'] and not is_next:
                notes.append('no longer The Next Leaders Group: Guest Attendees carousel removed')
        if new:
            notes.append(f'new card, {len(c["speakers"])} speakers'
                         + (f', {len(c["attendees"])} attendees' if is_next else '')
                         + f', button links to /{ev["page"]}')
        out.append(render_main_card(c, is_next))
    if not out:
        raise Stop('Main page: WordPress shows no event cards. Not emptying the main page')
    shown = [ev['page'] for ev, _ in order]
    for c in cards:
        if c['page'] not in shown:
            name = next((e['name'] for e in EVENTS if e['page'] == c['page']), c['page'])
            report.setdefault(f'Main page, {name} card', []).append('card removed (not on the WordPress landing page)')
    if [p for p in shown if p in ours] != [c['page'] for c in cards if c['page'] in shown]:
        report.setdefault('Main page', []).append('card order changed: ' + ', '.join(ev['name'] for ev, _ in order))
    page = (page[:nxt.start(2)] + out[0] + page[nxt.end(2):more.start(2)]
            + '\n' + '\n\n'.join(out[1:]) + '\n' + page[more.end(2):])
    return page, report


def sync_members(page, name, members):
    start = page.find('id="ukl-members"')
    if start < 0:
        return page, []

    def merge(items):
        ours = [{'raw': i,
                 'src': html.unescape(re.search(r'src="([^"]*)"', i).group(1)),
                 'alt': text(re.search(r'alt="([^"]*)"', i).group(1))} for i in items]
        return merge_members(ours, members)

    page, n = replace_items(page, f'{name} members', r'<div class="ukl-track">\n',
                            r' {14}<div class="ukl-member">[^\n]*', END_TRACK, merge, start)
    return page, n or []


# ---------- run ----------

def write_summary(path, summary):
    """Save the summary for the pull request, and show it on the GitHub run page."""
    if path:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(summary + '\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(summary + '\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--dry-run', action='store_true', help='show changes without writing files')
    ap.add_argument('--summary', help='also write the summary (Markdown) to this file')
    args = ap.parse_args()
    sys.stdout.reconfigure(errors='replace')  # Windows consoles can't show every character
    sys.stderr.reconfigure(errors='replace')

    def path(name):
        return os.path.join(PAGES, name + '.html')

    # Work with \n line endings and put each file's own style back when writing
    files, crlf = {}, {}
    for name in sorted(os.listdir(PAGES)):
        if name.endswith('.html'):
            with open(path(name[:-5]), encoding='utf-8', newline='') as f:
                raw = f.read()
            crlf[name[:-5]] = '\r\n' in raw
            files[name[:-5]] = raw.replace('\r\n', '\n')
    original = dict(files)
    report = {}

    try:
        landing = read_wp_landing()
        data = {}
        for ev in EVENTS:
            if ev['page'] not in files:
                raise Stop(f'pages/{ev["page"]}.html is missing (listed in EVENTS as {ev["name"]})')
            speakers, attendees, details = read_wp_event(WP + ev['wp'])
            data[ev['page']] = (speakers, attendees)
            files[ev['page']], notes = sync_event_page(files[ev['page']], ev, speakers, attendees, details)
            report.setdefault(ev['name'], []).extend(notes)
        files[MAIN_PAGE], notes = sync_main_page(files[MAIN_PAGE], landing, data)
        for section, n in notes.items():
            report.setdefault(section, []).extend(n)

        if SYNC['members']:
            members = read_wp_members()
            for name in files:
                files[name], notes = sync_members(files[name], name, members)
                section = report.setdefault('Member Organisations (all pages)', [])
                section.extend(n for n in notes if n not in section)
    except Stop as e:
        msg = f'STOPPED, nothing was changed: {e}'
        print(msg, file=sys.stderr)
        write_summary(args.summary, msg)
        sys.exit(1)

    changed = [name for name in files if files[name] != original[name]]
    lines = ['## Changes from WordPress', '']
    for section, notes in report.items():
        if notes:
            lines += [f'### {section}'] + [f'- {html.unescape(n)}' for n in notes] + ['']
    if changed:
        lines += ['Files: ' + ', '.join(f'`pages/{n}.html`' for n in changed)]
    else:
        lines = ['No changes: our pages match WordPress.']
    summary = '\n'.join(lines)
    print(summary)
    write_summary(args.summary, summary)

    if not args.dry_run:
        for name in changed:
            with open(path(name), 'w', encoding='utf-8', newline='') as f:
                f.write(files[name].replace('\n', '\r\n') if crlf[name] else files[name])


if __name__ == '__main__':
    main()
