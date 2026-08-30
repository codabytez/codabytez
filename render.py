"""
Draws the profile card.

Both SVGs are generated from the same row definitions, so a change to
`config.py` lands in dark and light mode at once and the dot leaders stay
aligned without anyone counting periods by hand.

Everything is laid out in character cells: the panel is `PANEL_COLS` columns
wide, and a FILL segment expands to whatever space is left over on its row.
That is the whole trick - because the font is monospaced, character counts are
pixel positions.
"""

import os
from typing import List, Optional, Tuple
from xml.sax.saxutils import escape

import config

# A row is a list of (text, css class) segments; the class is None for text
# that inherits the panel colour. Spelled out so the checker does not infer a
# narrower type from whichever row happens to be built first.
Segment = Tuple[str, Optional[str]]
Row = List[Segment]

# A segment that stretches to fill the leftover columns on its row.
FILL: Segment = ('\x00FILL', 'cc')

KEY, VALUE, DIM = 'key', 'value', 'cc'
ADD, DEL = 'addColor', 'delColor'


# ---------------------------------------------------------------------------
# Row construction
# ---------------------------------------------------------------------------

def _leaders(budget):
    """The dotted run that justifies a value to the right edge of the panel."""
    if budget <= 0:
        return ''
    if budget == 1:
        return ' '
    if budget == 2:
        # a lone dot next to the colon reads as a typo rather than a leader
        return '  '
    return ' ' + '.' * (budget - 2) + ' '


def _label(label) -> Row:
    """`Stack.Web` -> an orange `Stack`, a dim `.`, an orange `Web`."""
    parts = label.split('.')
    segs: Row = []
    for i, part in enumerate(parts):
        if i:
            segs.append(('.', KEY))
        segs.append((part, KEY))
    return segs


def rule(title, dashes='—', cols=None) -> Row:
    """A section divider: `- Contact -————————————-—-`."""
    cols = config.PANEL_COLS if cols is None else cols
    body = cols - len(title) - 5
    return [(title, None), (' -' + dashes * max(0, body) + '-—-', None)]


def kv(label, value, value_class=VALUE) -> Row:
    """A `. Label: ....... value` row justified across the panel."""
    return [('. ', DIM)] + _label(label) + [(':', None), FILL,
                                            (str(value), value_class)]


def blank() -> Row:
    """
    A section separator: an empty row that still occupies its line.

    Upstream drew a lone '. ' here as a gutter mark, but with nothing beside it
    the dot reads as a rendering artefact rather than structure.
    """
    return []


def cont(value, value_class=VALUE) -> Row:
    """
    A wrapped value's continuation line, right-aligned under the first.

    Note the bare '.' rather than the usual '. ': the leader that follows
    already opens with a space, and both together read as a stray gap.
    """
    return [('.', DIM), FILL, (str(value), value_class)]


def value_budget(label, cols=None):
    """
    How many columns a value may use on a `. Label: ..... value` row before it
    runs past the edge of its column. Callers building variable-length values
    (the language and music rows) size themselves against this. `cols` selects
    the column: the stats panel by default, MUSIC_COLS for the narrower block
    under the portrait.
    """
    cols = config.PANEL_COLS if cols is None else cols
    return cols - len('. ') - len(label) - len(':') - 2


def _row_width(segments):
    return sum(len(s[0]) for s in segments if s != FILL)


def _resolve(segments: Row, cols=None) -> Row:
    """Replace FILL markers with dot leaders sized to the leftover columns."""
    cols = config.PANEL_COLS if cols is None else cols
    fills = [i for i, s in enumerate(segments) if s == FILL]
    if not fills:
        return segments
    budget = cols - _row_width(segments)
    share, extra = divmod(max(0, budget), len(fills))
    out = list(segments)
    for n, i in enumerate(fills):
        # the last leader absorbs the rounding remainder
        out[i] = (_leaders(share + (extra if n == len(fills) - 1 else 0)), DIM)
    return out


def build_panel(data):
    """The full right-hand panel, as a list of rows."""
    rows: List[Row] = [rule(config.PROMPT)]

    for label, value in config.SYSTEM:
        rows.append(kv(label, value))
        if label == 'OS':   # Uptime sits directly under OS, like real neofetch
            rows.append(kv(config.UPTIME_LABEL, data['age']))
            if data.get('wakatime'):   # the other elapsed-time row, beside it
                rows.append(kv(config.WAKATIME_LABEL, data['wakatime']))

    rows.append(blank())
    for label, value in config.LANGUAGES:
        rows.append(kv(label, data['language_names'] if value == 'LIVE' else value))

    rows.append(blank())
    for label, value in config.STACK:
        rows.append(kv(label, value))

    rows.append(blank())
    rows.append(rule('- Contact'))
    for label, value in config.CONTACT:
        rows.append(kv(label, value))

    rows.append(blank())
    rows.append(rule('- GitHub Stats'))
    rows.append([
        ('. ', DIM), ('Repos', KEY), (':', None), FILL, (data['repos'], VALUE),
        (' {', None), ('Contributed', KEY), (': ', None), (data['contrib'], VALUE),
        ('} | ', None), ('Stars', KEY), (':', None), FILL, (data['stars'], VALUE),
    ])
    rows.append([
        ('. ', DIM), ('Commits', KEY), (':', None), FILL, (data['commits'], VALUE),
        (' | ', None), ('Followers', KEY), (':', None), FILL, (data['followers'], VALUE),
    ])
    rows.append([
        ('. ', DIM), ('Lines of Code', KEY), (':', None), FILL,
        (data['loc_net'], VALUE), (' ( ', None),
        (data['loc_add'], ADD), ('++', ADD), (', ', None),
        (data['loc_del'], DEL), ('--', DEL), (' )', None),
    ])
    rows.append(kv('Top Languages', data['language_bar']))
    return rows


def build_music(music):
    """
    The Music block under the sparkline. Same dotted-leader grammar as the
    stats panel, justified to MUSIC_COLS because the left column is narrower.
    Returns [] when Spotify is not configured, and the block disappears.
    """
    if not music:
        return []
    cols = config.MUSIC_COLS
    rows = [rule('{} ({})'.format(config.MUSIC_LABEL, config.MUSIC_TIME_LABEL), cols=cols)]
    for label, key in (('On repeat', 'tracks'), ('Top track', 'track'), ('Top artists', 'artists')):
        value = music.get(key)
        if not value:
            continue
        if isinstance(value, str):
            rows.append(kv(label, value))
            continue
        # a wrapped value: first line carries the label, the rest are indented
        # continuations, and every line but the last ends in a comma so the
        # list reads as one run
        for i, line in enumerate(value):
            text = line + (',' if i < len(value) - 1 else '')
            rows.append(kv(label, text) if i == 0 else cont(text))
    return rows


# ---------------------------------------------------------------------------
# SVG emission
# ---------------------------------------------------------------------------

def _tspans(row, cols=None):
    out = []
    for text, cls in _resolve(row, cols):
        if not text:
            continue
        if cls:
            out.append('<tspan class="{}">{}</tspan>'.format(cls, escape(text)))
        else:
            out.append(escape(text))
    return ''.join(out)


def _text_block(lines, x, y, leading, cls, font_size=None, anchor=None,
                text_length=None):
    """A block of pre-positioned lines sharing one <text> element."""
    if not lines:
        return ''
    size = ' font-size="{}px"'.format(font_size) if font_size else ''
    # text-anchor centres a block without knowing the reader's font metrics,
    # which is the only way to centre reliably across Consolas and its
    # wider fallbacks.
    align = ' text-anchor="{}"'.format(anchor) if anchor else ''
    # textLength squeezes glyphs horizontally without touching their height -
    # how the sparkline gets tall bars in a narrow column.
    fit = (' textLength="{}" lengthAdjust="spacingAndGlyphs"'.format(text_length)
           if text_length else '')
    parts = ['<text x="{}" y="{}" class="{}"{}{}>'.format(x, y, cls, size, align)]
    for i, line in enumerate(lines):
        ly = y + i * leading
        ly = int(ly) if float(ly).is_integer() else round(ly, 2)
        parts.append('<tspan x="{}" y="{}"{}>{}</tspan>'.format(x, ly, fit, line))
    parts.append('</text>')
    return '\n'.join(parts)


def _read_art(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        # only the newline is stripped - trailing spaces keep a centred block
        # in column
        return [escape(line.rstrip('\n')) for line in f if line.strip('\n')]


STYLE = """@font-face {{
src: local('Consolas'), local('Consolas Bold');
font-family: 'ConsolasFallback';
font-display: swap;
-webkit-size-adjust: 109%;
size-adjust: 109%;
}}
.key {{fill: {key};}}
.value {{fill: {value};}}
.addColor {{fill: {add};}}
.delColor {{fill: {del_};}}
.cc {{fill: {dim};}}
.ascii, .panel {{fill: {fg};}}
.wordmark {{fill: {accent};}}
.tagline {{fill: {muted}; letter-spacing: 2px;}}
.spark {{fill: {add};}}
.sparklabel {{fill: {muted};}}
.divider {{stroke: {muted}; stroke-width: 1; opacity: 0.45;}}
text, tspan {{white-space: pre;}}"""


def render(filename, theme, data):
    rows = build_panel(data)
    panel = [_tspans(row) for row in rows]
    art = _read_art(theme.get('art', config.ART_FILE))
    wordmark = _read_art(config.WORDMARK_FILE)

    w = config.WIDTH
    centre = w // 2

    # Everything below the two columns is measured from whichever column ends
    # lower, so adding a row to config.py pushes the wordmark down instead of
    # colliding with it.
    art_bottom = config.ART_Y + (len(art) - 1) * config.ART_LEADING if art else 0
    spark_y = art_bottom + config.SPARK_GAP
    spark_bottom = spark_y + 60 if data.get('spark') else art_bottom

    music_rows = build_music(data.get('music'))
    music_y = spark_bottom + config.MUSIC_GAP
    music_bottom = music_y + (len(music_rows) - 1) * config.MUSIC_LEADING if music_rows else 0

    columns_bottom = max(
        spark_bottom,
        music_bottom,
        config.PANEL_Y + (len(rows) - 1) * config.PANEL_LEADING,
    )
    divider_y = columns_bottom + config.WORDMARK_GAP
    wordmark_y = divider_y + config.WORDMARK_GAP
    bottom = wordmark_y + max(0, len(wordmark) - 1) * config.WORDMARK_LEADING

    tagline_y = bottom + config.TAGLINE_GAP if config.TAGLINE else bottom
    h = max(config.MIN_HEIGHT, int(tagline_y + config.BOTTOM_MARGIN))

    music = [_text_block([_tspans(r, config.MUSIC_COLS) for r in music_rows],
                         config.ART_X, music_y, config.MUSIC_LEADING,
                         'panel', config.MUSIC_FONT_SIZE)] if music_rows else []

    spark = [
        _text_block([escape(config.SPARK_LABEL)], config.ART_X, spark_y, 0,
                    'sparklabel', config.SPARK_CAPTION_SIZE),
        _text_block([escape(data['spark'])], config.ART_X, spark_y + 40, 0,
                    'spark', config.SPARK_FONT_SIZE,
                    text_length=config.SPARK_WIDTH),
        _text_block([escape(data['spark_caption'])], config.ART_X, spark_y + 60,
                    0, 'sparklabel', config.SPARK_CAPTION_SIZE),
    ] if data.get('spark') else []

    blocks = [
        _text_block(art, config.ART_X, config.ART_Y,
                    config.ART_LEADING, 'ascii', config.ART_FONT_SIZE),
        _text_block(panel, config.PANEL_X, config.PANEL_Y,
                    config.PANEL_LEADING, 'panel'),
    ] + spark + music + [
        '<line x1="{}" y1="{}" x2="{}" y2="{}" class="divider"/>'.format(
            config.ART_X, round(divider_y, 2), w - config.ART_X, round(divider_y, 2)),
        _text_block(wordmark, centre, round(wordmark_y, 2),
                    config.WORDMARK_LEADING, 'wordmark',
                    config.WORDMARK_FONT_SIZE, anchor='middle'),
        _text_block([escape(config.TAGLINE)] if config.TAGLINE else [],
                    centre, round(tagline_y, 2), 0, 'tagline',
                    config.TAGLINE_FONT_SIZE, anchor='middle'),
    ]

    svg = (
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'font-family="ConsolasFallback,Consolas,Menlo,monospace" '
        'width="{w}px" height="{h}px" font-size="16px">\n'
        '<style>\n{style}\n</style>\n'
        '<rect width="{w}px" height="{h}px" fill="{bg}" rx="15"/>\n'
        '{body}\n</svg>\n'
    ).format(
        w=w, h=h, bg=theme['bg'],
        style=STYLE.format(key=theme['key'], value=theme['value'],
                           add=theme['add'], del_=theme['del'], dim=theme['dim'],
                           muted=theme['muted'], fg=theme['fg'],
                           accent=theme['accent']),
        body='\n'.join(b for b in blocks if b),
    )
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(svg)
    return filename


def render_all(data):
    return [render(name, theme, data) for name, theme in config.THEMES.items()]
