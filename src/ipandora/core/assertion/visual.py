# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : visual.py
@Time  : 2026-11-05

Image verdicts: does this screenshot still look like its golden image?

    that(page.screenshot(), '结算页').matches_golden('checkout', mask=[(0, 0, 200, 40)])
    that(page.locator('#price').screenshot(), '价格区').matches_golden('price')

Python Playwright has no screenshot comparison (to_have_screenshot exists only
in its JS runner), so this fills that gap -- deterministically, and as a Check
like any other: one claim, one verdict, recorded in the inventory.

**What it can and cannot see.** Measured on Chromium screenshots (docs/design/decisions/14
§4): a button changing colour differs in ~1,000-13,000 pixels; a price changing
from 100.50 to 100.60 differs in 7 -- pixelmatch reads glyph edges as
anti-aliasing. Anti-aliasing noise between two renderings of the same shapes
differs in 150-290. No pixel count separates a small text change from noise,
so images are for what things look like -- colours, blocks, icons, layout --
and text is judged as text, with expect(...).to_have_text or that().

**How it decides.** pixelmatch (anti-aliasing detection, YIQ colour distance)
marks differing pixels. With `noise='edges'`, the default, only pixels inside a
solid 3x3 block of difference count: anti-aliasing and sub-pixel shifts leave
lines one or two pixels thin, and a real change of colour or content fills an
area. `noise='strict'` counts every pixel pixelmatch marks, for pixel-exact
icons, at the cost of failing on rendering noise. The case fails when the
counted pixels exceed `tolerance` (a fraction of the image, default 0).

pixelmatch is pure Python and takes ~0.7s on a 1280x720 page. It only runs on
the bounding box of the bytes that differ, padded by the 2 pixels its
anti-aliasing check looks at, which gives the same count (verified) in
milliseconds for a localised change.

**Goldens** live beside the test, in `__goldens__/<name>-<browser>-<platform>.png`.
The same page renders differently on macOS and Linux, so one platform's golden
would fail on the other by construction; make them where CI runs. A missing
golden is a failure that says how to make one -- never a quiet pass on a
freshly saved image. `ipandora run --update-baseline` writes the goldens and
the judgement baseline together; the golden's hash is in the claim, so a
replaced golden shows up as a changed judgement and `--fail-on-weakened`
stops it.
"""
import hashlib
import io
import os
import re
import sys
import tempfile
from typing import Any, Iterable, Optional, Sequence, Tuple

from ipandora.core.assertion.check import Check, Source

UPDATE_VAR = 'IPANDORA_UPDATE_GOLDENS'
"""Set by run(update_goldens=True), i.e. `ipandora run --update-baseline`."""

ARTIFACTS_VAR = 'IPANDORA_ARTIFACTS_DIR'
"""This run's artifact folder; run() sets it for every process."""

GOLDENS = '__goldens__'
NOISE = ('edges', 'strict')
MASK_FILL = (255, 0, 255, 255)
_PAD = 3          # pixelmatch's anti-aliasing check looks two pixels out


class ImageUnavailable(Exception):
    """Pillow or pixelmatch is not installed."""


def _require():
    try:
        import PIL.Image  # noqa: F401
        import pixelmatch  # noqa: F401
    except ImportError as exc:
        raise ImageUnavailable(
            'image verdicts need the `visual` extra: pip install intellipandora[visual] '
            '({})'.format(exc))


def _image(value):
    """bytes (PNG), a path, or a PIL image -> an RGBA PIL image."""
    from PIL import Image
    if isinstance(value, Image.Image):
        return value.convert('RGBA')
    if isinstance(value, (bytes, bytearray)):
        return Image.open(io.BytesIO(bytes(value))).convert('RGBA')
    if isinstance(value, (str, os.PathLike)):
        with Image.open(value) as _img:
            return _img.convert('RGBA')
    raise TypeError('expected PNG bytes, a file path or a PIL image, got {}'.format(
        type(value).__name__))


def _png(img) -> bytes:
    _buf = io.BytesIO()
    img.save(_buf, format='PNG')
    return _buf.getvalue()


def _slug(text: str) -> str:
    """
    A filename for `text`. ASCII names stay as they always were, so existing
    goldens keep their paths. A name with other characters, or one too long,
    gets a hash of the full text: '价格区' and '总价' both became 'image', and
    two long node ids sharing their first 80 characters shared a file -- one
    case's golden or diff overwrote another's.
    """
    _plain = re.sub(r'[^A-Za-z0-9._-]+', '-', text).strip('-')
    if text.isascii() and len(_plain) <= 80:
        return _plain or 'image'
    _digest = hashlib.sha256(text.encode('utf-8')).hexdigest()[:10]
    return '{}-{}'.format(_plain[:60].strip('-') or 'image', _digest)


# -- where things go ----------------------------------------------------------

def golden_path(name: str, test_path: str = '', browser: str = '') -> str:
    """`<test dir>/__goldens__/<name>[-<browser>]-<platform>.png`."""
    _dir = os.path.join(os.path.dirname(os.path.abspath(test_path)) if test_path
                        else os.getcwd(), GOLDENS)
    _parts = [_slug(name)] + ([_slug(browser)] if browser else []) + [sys.platform]
    return os.path.join(_dir, '-'.join(_parts) + '.png')


def _artifact_dir() -> str:
    _dir = os.environ.get(ARTIFACTS_VAR) or os.path.join(tempfile.gettempdir(), 'ipandora-images')
    os.makedirs(_dir, exist_ok=True)
    return _dir


def _keep(evidence, name: str, images: dict) -> None:
    """Save golden / actual / diff for the report, and list them on the case."""
    _stem = _slug('{}-{}'.format(getattr(evidence, 'nodeid', '') or 'case', name))
    for _kind, _img in images.items():
        if _img is None:
            continue
        _path = os.path.join(_artifact_dir(), '{}-{}.png'.format(_stem, _kind))
        if isinstance(_img, str):
            _path = _img                      # the golden itself, already on disk
        else:
            _img.save(_path)
        if evidence is not None:
            evidence.artifacts.append({'kind': _kind, 'path': os.path.abspath(_path),
                                       'group': name})


# -- comparing ---------------------------------------------------------------------

def _masked(img, mask: Iterable[Tuple[int, int, int, int]]):
    if not mask:
        return img
    from PIL import ImageDraw
    _img = img.copy()
    _draw = ImageDraw.Draw(_img)
    for _x, _y, _w, _h in mask:
        _draw.rectangle((_x, _y, _x + _w - 1, _y + _h - 1), fill=MASK_FILL)
    return _img


def compare(golden, actual, threshold: float = 0.1, noise: str = 'edges'):
    """
    (counted pixels, diff image, box of what counted or None).

    pixelmatch runs only on the box where the bytes differ, padded so its
    anti-aliasing check sees the same neighbourhood it would on the full image.
    """
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    from pixelmatch.contrib.PIL import pixelmatch
    _width, _height = golden.size
    # the faded golden that pixelmatch draws unchanged pixels as
    _diff = Image.merge('RGBA', [golden.convert('L').point(lambda v: int(255 + (v - 255) * 0.1))] * 3
                        + [Image.new('L', golden.size, 255)])
    _box = ImageChops.difference(golden, actual).getbbox(alpha_only=False)
    if _box is None:
        return 0, _diff, None
    _x0, _y0, _x1, _y1 = _box
    _box = (max(0, _x0 - _PAD), max(0, _y0 - _PAD), min(_width, _x1 + _PAD), min(_height, _y1 + _PAD))
    _crop = Image.new('RGBA', (_box[2] - _box[0], _box[3] - _box[1]))
    _marked = pixelmatch(golden.crop(_box), actual.crop(_box), _crop, threshold=threshold)
    _diff.paste(_crop, _box[:2])
    if noise == 'strict':
        _counted, _where = _marked, _box if _marked else None
    else:
        # pixelmatch paints differing pixels pure red, anti-aliased ones yellow,
        # unchanged ones as a faded grey -- so pure red is exactly what it marked
        _r, _g, _b = _crop.convert('RGB').split()
        _mask = ImageChops.multiply(ImageChops.multiply(
            _r.point(lambda v: 255 if v == 255 else 0),
            _g.point(lambda v: 255 if v == 0 else 0)),
            _b.point(lambda v: 255 if v == 0 else 0))
        _solid = _mask.filter(ImageFilter.MinFilter(3))
        _counted = _solid.histogram()[255]
        _inner = _solid.getbbox()
        _where = (_inner[0] + _box[0], _inner[1] + _box[1], _inner[2] + _box[0],
                  _inner[3] + _box[1]) if _inner else None
    if _where:
        # so the change can be found at a glance, not by hunting for red dots
        ImageDraw.Draw(_diff).rectangle((_where[0] - 3, _where[1] - 3, _where[2] + 2,
                                         _where[3] + 2), outline=(255, 0, 0, 255), width=2)
    return _counted, _diff, _where


def claim_for(label: str, name: str, digest: str, threshold: float, tolerance: float,
              noise: str, mask: Sequence) -> str:
    """Every setting that makes the verdict easier is in the claim, so loosening one shows."""
    return '{} matches golden {!r} {} threshold={:g} tolerance={:g} noise={}{}'.format(
        label, name, digest, threshold, tolerance, noise,
        ' mask={}'.format(len(mask)) if mask else '')


def matches_golden(value: Any, name: str, label: str = 'screen', tolerance: float = 0.0,
                   mask: Sequence[Tuple[int, int, int, int]] = (), threshold: float = 0.1,
                   noise: str = 'edges', check_name: Optional[str] = None) -> Check:
    """
    One Check: `value` looks like the golden image `name`.

    :param tolerance: fraction of the image allowed to differ, after `noise`.
    :param mask:      (x, y, width, height) rectangles ignored on both images --
                      a clock, an avatar, an ad. For web screenshots Playwright's
                      own `page.screenshot(mask=[locator])` works too.
    :param threshold: pixelmatch's per-pixel colour distance, 0-1.
    :param noise:     'edges' (default) ignores differences thinner than a 3x3
                      block -- anti-aliasing, sub-pixel shifts. 'strict' counts
                      every differing pixel.
    """
    from ipandora.core.evidence import recorder
    if noise not in NOISE:
        raise ValueError('noise must be one of {}, got {!r}'.format(NOISE, noise))
    _require()
    _evidence = recorder.current()
    _context = getattr(_evidence, 'context', {}) or {}
    _golden_file = golden_path(name, _context.get('path', ''), _context.get('browser', ''))
    try:
        _shown = os.path.relpath(_golden_file)
    except ValueError:            # another drive, on Windows
        _shown = _golden_file
    def _check(ok, digest, expr):
        _claim = claim_for(label, name, digest, threshold, tolerance, noise, mask)
        return Check(name=check_name or _claim, ok=ok, expr=expr, src=Source.VISUAL, claim=_claim)

    # A value that is not an image, or a golden file that is not one, is a
    # failed judgement like any other -- it raised, and took assert_all's
    # other checks down with it.
    try:
        _actual = _masked(_image(value), mask)
    except Exception as exc:  # noqa: BLE001 -- PIL raises several unrelated types
        return _check(False, 'unreadable', '实际图像无法读取：{}: {}'.format(type(exc).__name__, exc))

    if os.environ.get(UPDATE_VAR):
        os.makedirs(os.path.dirname(_golden_file), exist_ok=True)
        _data = _png(_image(value))
        with open(_golden_file, 'wb') as _f:
            _f.write(_data)
        _keep(_evidence, name, {'golden': _golden_file})
        return _check(True, _digest(_data), '基准图已更新：{}'.format(_shown))

    if not os.path.exists(_golden_file):
        _keep(_evidence, name, {'actual': _actual})
        return _check(False, 'missing',
                      '没有基准图 {}。确认这次的截图（见报告）无误后，用 ipandora run '
                      '--update-baseline 生成；不会自动生成后判为通过'.format(_shown))

    with open(_golden_file, 'rb') as _f:
        _data = _f.read()
    _digest_now = _digest(_data)
    try:
        _golden = _masked(_image(_data), mask)
    except Exception as exc:  # noqa: BLE001 -- PIL raises several unrelated types
        return _check(False, _digest_now, '基准图 {} 无法读取：{}: {}'.format(
            _shown, type(exc).__name__, exc))
    if _golden.size != _actual.size:
        _keep(_evidence, name, {'golden': _golden_file, 'actual': _actual})
        return _check(False, _digest_now, '尺寸不同：基准图 {}x{}，实际 {}x{}'.format(
            *(_golden.size + _actual.size)))

    _counted, _diff, _where = compare(_golden, _actual, threshold, noise)
    _total = _golden.size[0] * _golden.size[1]
    _allowed = int(tolerance * _total)
    if _counted <= _allowed:
        return _check(True, _digest_now, '{} 个像素不同（允许 {}）'.format(_counted, _allowed))
    _keep(_evidence, name, {'golden': _golden_file, 'actual': _actual, 'diff': _diff})
    return _check(False, _digest_now, '{} 个像素不同（{:.3%}，允许 {}），位置 x={}..{} y={}..{}'.format(
        _counted, _counted / _total, _allowed, _where[0], _where[2], _where[1], _where[3]))


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]
