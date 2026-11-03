"""Sync Leaders Group content from ukreiif.com (WordPress) into pages/.

Reads the public WordPress pages, compares guest speakers, guest attendees and
member logos with our pages, and rewrites only the items that changed.
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
import urllib.request

from bs4 import BeautifulSoup

WP = 'https://www.ukreiif.com'
MEMBERS_URL = WP + '/leaders-group-events/'

# Which WordPress event feeds which of our pages
EVENTS = [
    {'name': 'November', 'wp': '/leaders-group-events/leaders-group-november/', 'page': 'leaders-group-november'},
    {'name': 'December', 'wp': '/leaders-group-events/leaders-group-december/', 'page': 'leaders-group-december'},
    {'name': 'February', 'wp': '/leaders-group-events/leaders-group-february-2/', 'page': 'leaders-group-february'},
]

# Switch parts on (True) or off (False). Anything off is left exactly as it is.
SYNC = {
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
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8')


def text(s):
    """Decoded text with single spaces."""
    return ' '.join(html.unescape(s).split())


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

def wp_person(box, details, logo_cls):
    # Search the whole card: WordPress markup sometimes nests the text inside the photo tag
    ps = [' '.join(p.get_text(' ').split()) for p in details.find_all('p')
          if not p.find_parent(class_=logo_cls)]
    photo = box.find('img')
    logo = box.select_one(f'.{logo_cls} img')
    return {
        'name': ps[0] if ps else '',
        'title': ps[1] if len(ps) > 1 else '',
        'org': ps[2] if len(ps) > 2 else '',
        'photo': (photo.get('data-src') or photo.get('src', '')) if photo else '',
        'logo': (logo.get('data-src') or logo.get('src', '')) if logo else '',
        'bio': '',
    }


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
    return speakers, attendees


def read_wp_members():
    soup = BeautifulSoup(fetch(MEMBERS_URL), 'html.parser')
    carousel = soup.select_one('.lg-member-orgs-carousel')
    if not carousel:
        raise Stop(f'{MEMBERS_URL} no longer shows a Member Organisations carousel')
    out = []
    for img in carousel.select('.lg-org-item img'):
        src = img.get('data-src') or img.get('src', '')
        span = img.find_parent('span')
        name = (img.get('alt') or (span.get('title') if span else '') or '').strip() or logo_name(src)
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
        notes.append(f'{label}: {len(ours)} &#8594; {len(theirs)}')
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
        notes.append(f'{len(ours)} &#8594; {len(theirs)} logos')
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


def sync_event_page(page, ev, speakers, attendees):
    notes = []
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


def sync_main_card(page, ev, speakers, attendees):
    start = page.find(f'href="/{ev["page"]}"')
    if start < 0:
        return page, []
    start = page.rfind('<div class="ukl-card">', 0, start)
    notes = []

    def card_end(p):
        ends = [i for i in (p.find('<div class="ukl-card', start + 1), p.find('</section>', start)) if i > 0]
        return min(ends)

    if SYNC['speakers']:
        page, n = replace_items(page, f'Main page {ev["name"]} speakers', r'<div class="ukl-people">\n',
                                r' {12}<div class="ukl-person">[^\n]*', r'\n {10}</div>',
                                lambda items: merge_people('Guest speakers', [parse_ours(i) for i in items], speakers,
                                                           render_card_person(' ' * 12), combined=True),
                                start, card_end(page))
        notes += n or []
    if SYNC['attendees']:
        page, n = replace_items(page, f'Main page {ev["name"]} attendees', r'<div class="ukl-track">\n',
                                r' {14}<div class="ukl-person">[^\n]*', END_TRACK,
                                lambda items: merge_people('Guest attendees', [parse_ours(i) for i in items], attendees,
                                                           render_card_person(' ' * 14), combined=True),
                                start, card_end(page))
        notes += n or []
    return page, notes


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

def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--dry-run', action='store_true', help='show changes without writing files')
    ap.add_argument('--summary', help='also write the summary (Markdown) to this file')
    args = ap.parse_args()

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
        for ev in EVENTS:
            speakers, attendees = read_wp_event(WP + ev['wp'])
            files[ev['page']], notes = sync_event_page(files[ev['page']], ev, speakers, attendees)
            report.setdefault(ev['name'], []).extend(notes)
            files[MAIN_PAGE], notes = sync_main_card(files[MAIN_PAGE], ev, speakers, attendees)
            report.setdefault(f'Main page, {ev["name"]} card', []).extend(notes)

        if SYNC['members']:
            members = read_wp_members()
            for name in files:
                files[name], notes = sync_members(files[name], name, members)
                section = report.setdefault('Member Organisations (all pages)', [])
                section.extend(n for n in notes if n not in section)
    except Stop as e:
        msg = f'STOPPED, nothing was changed: {e}'
        print(msg, file=sys.stderr)
        if args.summary:
            with open(args.summary, 'w', encoding='utf-8') as f:
                f.write(msg + '\n')
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
    if args.summary:
        with open(args.summary, 'w', encoding='utf-8') as f:
            f.write(summary + '\n')

    if not args.dry_run:
        for name in changed:
            with open(path(name), 'w', encoding='utf-8', newline='') as f:
                f.write(files[name].replace('\n', '\r\n') if crlf[name] else files[name])


if __name__ == '__main__':
    main()
