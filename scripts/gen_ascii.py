#!/usr/bin/env python3
"""
Generates the ASCII art the card draws in its left column.

    # portrait, from any image or straight from your GitHub avatar
    python scripts/gen_ascii.py portrait --user codabytez
    python scripts/gen_ascii.py portrait me.jpg --out art/avatar.txt

    # block-letter wordmark
    python scripts/gen_ascii.py wordmark CODABYTEZ

The portrait mode needs Pillow (`pip install -r scripts/requirements.txt`);
the wordmark mode is pure stdlib. Neither runs in CI - the art is committed,
so the daily build stays dependency-light and fast.

Why the output looks the way it does: the card renders light glyphs on a dark
background, so *bright* pixels become *dense* characters. The flat backdrop
behind most avatars is detected and dropped, otherwise it fills the frame with
mid-density noise and the subject reads as a hole punched out of it.
"""

import argparse
import io
import os
import sys

# sparse -> dense; ASCII only, so it survives any monospace fallback font
RAMP = " .,:;*/(#%@"

# 4 columns x 5 rows per glyph, joined with a single blank column
FONT_ROWS = 5
FONT = {
    ' ': ('    ', '    ', '    ', '    ', '    '),
    '-': ('    ', '    ', '####', '    ', '    '),
    '_': ('    ', '    ', '    ', '    ', '####'),
    '.': ('    ', '    ', '    ', '    ', ' ## '),
    'A': ('####', '#  #', '####', '#  #', '#  #'),
    'B': ('### ', '#  #', '### ', '#  #', '### '),
    'C': ('####', '#   ', '#   ', '#   ', '####'),
    'D': ('### ', '#  #', '#  #', '#  #', '### '),
    'E': ('####', '#   ', '### ', '#   ', '####'),
    'F': ('####', '#   ', '### ', '#   ', '#   '),
    'G': ('####', '#   ', '# ##', '#  #', '####'),
    'H': ('#  #', '#  #', '####', '#  #', '#  #'),
    'I': ('####', ' ## ', ' ## ', ' ## ', '####'),
    'J': ('####', '  # ', '  # ', '#  #', '### '),
    'K': ('#  #', '# # ', '##  ', '# # ', '#  #'),
    'L': ('#   ', '#   ', '#   ', '#   ', '####'),
    'M': ('#  #', '####', '####', '#  #', '#  #'),
    'N': ('#  #', '## #', '# ##', '#  #', '#  #'),
    'O': ('####', '#  #', '#  #', '#  #', '####'),
    'P': ('####', '#  #', '####', '#   ', '#   '),
    'Q': ('####', '#  #', '#  #', '# # ', '## #'),
    'R': ('####', '#  #', '### ', '# # ', '#  #'),
    'S': ('####', '#   ', '####', '   #', '####'),
    'T': ('####', ' ## ', ' ## ', ' ## ', ' ## '),
    'U': ('#  #', '#  #', '#  #', '#  #', '####'),
    'V': ('#  #', '#  #', '#  #', ' ## ', ' ## '),
    'W': ('#  #', '#  #', '####', '####', '#  #'),
    'X': ('#  #', ' ## ', ' ## ', ' ## ', '#  #'),
    'Y': ('#  #', '#  #', ' ## ', ' ## ', ' ## '),
    'Z': ('####', '  # ', ' ## ', '#   ', '####'),
    '0': ('####', '#  #', '#  #', '#  #', '####'),
    '1': (' ## ', '### ', ' ## ', ' ## ', '####'),
    '2': ('####', '   #', '####', '#   ', '####'),
    '3': ('####', '   #', ' ###', '   #', '####'),
    '4': ('#  #', '#  #', '####', '   #', '   #'),
    '5': ('####', '#   ', '####', '   #', '####'),
    '6': ('####', '#   ', '####', '#  #', '####'),
    '7': ('####', '   #', '  # ', ' #  ', ' #  '),
    '8': ('####', '#  #', '####', '#  #', '####'),
    '9': ('####', '#  #', '####', '   #', '####'),
}


# ---------------------------------------------------------------------------
# Wordmark
# ---------------------------------------------------------------------------

def wordmark(text, width, fill='█'):
    """
    Renders `text` as 5 rows of block letters, centred in `width` columns.

    The default fill is U+2588 FULL BLOCK rather than '#': at the size the card
    draws this, '#' leaves visible gaps between cells and the letters read as
    scattered hashes instead of solid strokes. Every monospace font that
    matters ships the block glyph at a single cell wide.
    """
    glyphs = [FONT[ch] for ch in text.upper() if ch in FONT]
    if not glyphs:
        raise SystemExit('nothing renderable in {!r}'.format(text))
    rows = [' '.join(g[r] for g in glyphs).replace('#', fill) for r in range(FONT_ROWS)]
    span = max(len(r) for r in rows)
    if span > width:
        raise SystemExit(
            '{!r} needs {} columns but only {} are available - shorten it or '
            'raise --width'.format(text, span, width))
    pad = ' ' * ((width - span) // 2)
    # Deliberately not stripped: the card centres these rows as a block, so
    # every row must stay the same width or the letters drift out of column.
    return [(pad + r).ljust(width) for r in rows]


# ---------------------------------------------------------------------------
# Portrait
# ---------------------------------------------------------------------------

def _load(source):
    from PIL import Image
    if source.startswith(('http://', 'https://')):
        import requests
        raw = requests.get(source, timeout=30)
        raw.raise_for_status()
        img = Image.open(io.BytesIO(raw.content))
    else:
        img = Image.open(source)
    # composite onto white so transparent PNGs do not read as solid black
    img = img.convert('RGBA')
    flat = Image.new('RGBA', img.size, (255, 255, 255, 255))
    flat.alpha_composite(img)
    return flat.convert('RGB')


def _background(rgb):
    """The flat colour behind the subject, sampled from the top edge."""
    w, _ = rgb.size
    points = [(2, 2), (w // 2, 2), (w - 3, 2)]
    return tuple(sum(rgb.getpixel(p)[i] for p in points) // len(points) for i in range(3))


def _subject_mask(rgb, tolerance):
    """0 where a pixel matches the backdrop, 255 where it clearly does not."""
    from PIL import Image
    mask = Image.new('L', rgb.size)
    bg = _background(rgb)
    src, dst = rgb.load(), mask.load()
    assert src is not None and dst is not None  # .load() is only None for unopened images
    for y in range(rgb.size[1]):
        for x in range(rgb.size[0]):
            r, g, b = src[x, y]
            distance = abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2])
            dst[x, y] = min(255, int(distance * 255 / tolerance))
    return mask


def _level(pixels, x, y):
    """
    One greyscale pixel as a float. Single-band 'L' images hand back a plain
    int, but the type stubs allow a tuple for multiband images, so unwrap
    defensively rather than sprinkle casts through the loop.
    """
    value = pixels[x, y]
    return float(value[0] if isinstance(value, tuple) else value)


def _fractional_crop(rgb, spec):
    """`--crop 0,0,1,0.6` keeps the top 60% of the frame."""
    try:
        left, top, right, bottom = (float(v) for v in spec.split(','))
    except ValueError:
        raise SystemExit('--crop wants four fractions: left,top,right,bottom')
    w, h = rgb.size
    return rgb.crop((int(left * w), int(top * h), int(right * w), int(bottom * h)))


def portrait(source, cols, rows, gamma, tolerance, keep_background, no_crop, crop=None,
             invert=False):
    from PIL import Image, ImageOps

    rgb = _load(source)
    if crop:
        rgb = _fractional_crop(rgb, crop)
    # work at a modest size - the mask is a per-pixel Python loop
    rgb.thumbnail((320, 320), Image.Resampling.LANCZOS)
    mask = _subject_mask(rgb, tolerance)

    if not no_crop:
        box = mask.point([0] * 111 + [255] * 145).getbbox()
        if box:
            pad_x, pad_y = int(rgb.size[0] * 0.03), int(rgb.size[1] * 0.03)
            box = (max(0, box[0] - pad_x), max(0, box[1] - pad_y),
                   min(rgb.size[0], box[2] + pad_x), min(rgb.size[1], box[3] + pad_y))
            rgb, mask = rgb.crop(box), mask.crop(box)

    luma = ImageOps.autocontrast(rgb.convert('L'), cutoff=1).resize((cols, rows), Image.Resampling.LANCZOS)
    mask = mask.resize((cols, rows), Image.Resampling.LANCZOS)
    lp, mp = luma.load(), mask.load()
    assert lp is not None and mp is not None

    lines = []
    for y in range(rows):
        line = []
        for x in range(cols):
            value = _level(lp, x, y) / 255
            if invert:
                # Dark mode paints light glyphs on a dark ground, so a dense
                # glyph reads as BRIGHT and luminance maps straight through.
                # Light mode is dark ink on a light ground, so density reads as
                # DARK and the mapping has to flip or the portrait comes out as
                # a photographic negative.
                value = 1.0 - value
            if not keep_background:
                value *= (_level(mp, x, y) / 255) ** 0.6
            value **= gamma
            line.append(RAMP[min(len(RAMP) - 1, int(value * len(RAMP)))])
        lines.append(''.join(line).rstrip())
    return lines


# ---------------------------------------------------------------------------

def write(lines, path):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    print('\n-> {} ({} lines, {} cols)'.format(path, len(lines), max(map(len, lines))))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='mode', required=True)

    p = sub.add_parser('portrait', help='image -> ASCII portrait')
    p.add_argument('source', nargs='?', help='image path or URL')
    p.add_argument('--user', help='fetch this GitHub user\'s avatar instead')
    p.add_argument('--out', default='art/avatar.txt')
    p.add_argument('--cols', type=int, default=52)
    p.add_argument('--rows', type=int, default=30)
    p.add_argument('--gamma', type=float, default=1.0,
                   help='<1 brightens the midtones, >1 darkens them')
    p.add_argument('--tolerance', type=int, default=90,
                   help='how far a pixel may stray from the backdrop and still '
                        'count as background; raise it for busy photos')
    p.add_argument('--keep-background', action='store_true',
                   help='render the backdrop instead of dropping it')
    p.add_argument('--crop', metavar='L,T,R,B',
                   help='pre-crop to these fractions of the frame, e.g. '
                        '"0,0,1,0.6" to keep only the top 60%%')
    p.add_argument('--no-crop', action='store_true',
                   help='skip the automatic crop to the subject')
    p.add_argument('--invert', action='store_true',
                   help='flip light and dark: needed for the light-mode art, '
                        'where a dense glyph reads as dark rather than bright')

    w = sub.add_parser('wordmark', help='text -> block letters')
    w.add_argument('text')
    w.add_argument('--out', default='art/wordmark.txt')
    w.add_argument('--width', type=int, default=52)
    w.add_argument('--fill', default='█',
                   help="character the letters are drawn with (default: full block)")

    args = parser.parse_args(argv)

    if args.mode == 'wordmark':
        write(wordmark(args.text, args.width, args.fill), args.out)
        return

    source = args.source
    if args.user:
        source = 'https://github.com/{}.png?size=460'.format(args.user)
    if not source:
        parser.error('portrait needs an image path/URL or --user')
    try:
        lines = portrait(source, args.cols, args.rows, args.gamma,
                         args.tolerance, args.keep_background, args.no_crop,
                         args.crop, invert=args.invert)
    except ImportError:
        sys.exit('portrait mode needs Pillow: pip install -r scripts/requirements.txt')
    write(lines, args.out)


if __name__ == '__main__':
    main()
