# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_visual.py
@Time  : 2026-11-05

Image verdicts. Acceptance from docs/design/14 §4:

- anti-aliasing and font-rendering differences pass at the default settings;
  changing a button's colour fails, and the diff shows where;
- a change inside a masked area passes;
- replacing a golden is caught by --fail-on-weakened.

Plus what would make the verdict mislead: a missing golden that "passes", a
size mismatch, a cropped comparison that counts differently from a full one,
and settings loosened without the inventory noticing.
"""
import io
import json
import os
import random
import sys
import textwrap

import pytest

PIL = pytest.importorskip('PIL', reason='image verdicts need the `visual` extra')
pytest.importorskip('pixelmatch', reason='image verdicts need the `visual` extra')

from PIL import Image, ImageDraw  # noqa: E402
from pixelmatch.contrib.PIL import pixelmatch  # noqa: E402

from ipandora.core.assertion import visual  # noqa: E402
from ipandora.core.assertion.field import that  # noqa: E402
from ipandora.core.evidence import recorder  # noqa: E402
from ipandora.core.report import build, to_html  # noqa: E402
from ipandora.core.runner import inventory, run  # noqa: E402


def drawing(color=(37, 99, 235), offset=0.0, scale=4, extra=None):
    """
    Shapes rendered at `scale` times and downsampled: the anti-aliased edges a
    browser produces. A sub-pixel `offset` or another `scale` changes only
    those edges -- the kind of difference two renderers make.
    """
    _w, _h, _s = 400, 200, scale
    _big = Image.new('RGB', (_w * _s, _h * _s), 'white')
    _d = ImageDraw.Draw(_big)
    _o = int(offset * _s)
    _d.ellipse((40 * _s + _o, 40 * _s, 140 * _s + _o, 140 * _s), fill=(30, 30, 30))
    _d.line((200 * _s + _o, 30 * _s, 380 * _s + _o, 120 * _s), fill=(0, 0, 0), width=3 * _s)
    _d.rounded_rectangle((200 * _s, 150 * _s, 330 * _s, 190 * _s), radius=8 * _s, fill=color)
    if extra:
        extra(_d, _s)
    return _big.resize((_w, _h), Image.LANCZOS)


def noisy(img, amount=3):
    random.seed(0)
    _out = img.copy()
    _px = _out.load()
    for _y in range(img.size[1]):
        for _x in range(img.size[0]):
            _px[_x, _y] = tuple(max(0, min(255, _c + random.randint(-amount, amount)))
                                for _c in _px[_x, _y])
    return _out


@pytest.fixture
def case(tmp_path, monkeypatch):
    """An open evidence slot whose test file lives in tmp_path."""
    monkeypatch.setenv(visual.ARTIFACTS_VAR, str(tmp_path / 'artifacts'))
    monkeypatch.delenv(visual.UPDATE_VAR, raising=False)
    recorder.begin('test_x.py::test_x', path=str(tmp_path / 'test_x.py'), browser='chromium')
    yield recorder.current()
    recorder.end('test_x.py::test_x')


def golden(tmp_path, img, name='checkout'):
    _path = visual.golden_path(name, str(tmp_path / 'test_x.py'), 'chromium')
    os.makedirs(os.path.dirname(_path), exist_ok=True)
    img.save(_path)
    return _path


class TestWhatCountsAsDifferent:

    @pytest.mark.parametrize('variant', [
        pytest.param(lambda: drawing(offset=0.25), id='sub-pixel edges'),
        pytest.param(lambda: drawing(scale=3), id='another anti-aliasing filter'),
        pytest.param(lambda: noisy(drawing()), id='colour noise'),
    ])
    def test_rendering_differences_pass_by_default(self, tmp_path, case, variant):
        golden(tmp_path, drawing())
        _img = variant()
        # they really are different images, and pixelmatch alone flags some
        assert _img.tobytes() != drawing().tobytes()
        _check = that(_img, '结算页').matches_golden('checkout')
        assert _check.ok, _check.expr

    def test_a_button_changing_colour_fails_and_the_diff_shows_where(self, tmp_path, case):
        golden(tmp_path, drawing())
        _check = that(drawing(color=(22, 163, 74)), '结算页').matches_golden('checkout')
        assert not _check.ok
        assert '位置 x=' in _check.expr
        _kinds = {_a['kind']: _a['path'] for _a in case.artifacts}
        assert set(_kinds) == {'golden', 'actual', 'diff'}
        # the red box is drawn around the button (200..330, 150..190)
        _diff = Image.open(_kinds['diff']).convert('RGB')
        assert _diff.getpixel((198, 170))[:3] == (255, 0, 0)
        # and nowhere near the unchanged circle
        assert _diff.getpixel((90, 90))[:3] != (255, 0, 0)

    def test_strict_counts_what_edges_lets_through(self, tmp_path, case):
        golden(tmp_path, drawing())
        _img = drawing(offset=0.25)
        assert that(_img).matches_golden('checkout').ok
        assert not that(_img).matches_golden('checkout', noise='strict').ok

    def test_tolerance_is_a_fraction_of_the_image(self, tmp_path, case):
        golden(tmp_path, drawing())
        _changed = drawing(color=(22, 163, 74))
        assert not that(_changed).matches_golden('checkout', tolerance=0.01).ok
        assert that(_changed).matches_golden('checkout', tolerance=0.2).ok

    def test_a_change_inside_a_mask_passes(self, tmp_path, case):
        golden(tmp_path, drawing())
        _clock = drawing(extra=lambda d, s: d.rectangle((10 * s, 160 * s, 120 * s, 190 * s),
                                                        fill=(200, 0, 0)))
        assert not that(_clock).matches_golden('checkout').ok
        assert that(_clock).matches_golden('checkout', mask=[(5, 155, 120, 40)]).ok
        # and the mask does not hide a change outside it
        _both = drawing(color=(22, 163, 74), extra=lambda d, s: d.rectangle(
            (10 * s, 160 * s, 120 * s, 190 * s), fill=(200, 0, 0)))
        assert not that(_both).matches_golden('checkout', mask=[(5, 155, 120, 40)]).ok

    @pytest.mark.parametrize('variant', [
        lambda: drawing(color=(22, 163, 74)), lambda: drawing(offset=0.25),
        lambda: noisy(drawing()), lambda: drawing(scale=3),
    ])
    def test_comparing_only_the_changed_box_counts_the_same_as_the_whole_image(self, variant):
        _a, _b = drawing().convert('RGBA'), variant().convert('RGBA')
        _counted, _, _ = visual.compare(_a, _b, noise='strict')
        assert _counted == pixelmatch(_a, _b)


def scene(seed, jitter):
    """Random shapes; `jitter` shifts each by up to a pixel, anti-aliased."""
    _r = random.Random(seed)
    _s, _w, _h = 4, 120, 80
    _big = Image.new('RGB', (_w * _s, _h * _s), 'white')
    _d = ImageDraw.Draw(_big)
    for _ in range(6):
        _x, _y = _r.randint(0, _w - 20) * _s, _r.randint(0, _h - 20) * _s
        _bw, _bh = _r.randint(4, 30) * _s, _r.randint(4, 30) * _s
        _col = tuple(_r.randint(0, 255) for _ in range(3))
        _jx = int(jitter * _r.random() * _s)
        (_d.ellipse if _r.random() < .5 else _d.rectangle)((_x + _jx, _y, _x + _jx + _bw, _y + _bh),
                                                         fill=_col)
    return _big.resize((_w, _h), Image.LANCZOS).convert('RGBA')


def test_the_cropped_comparison_matches_the_full_one_on_random_scenes():
    # pixelmatch's anti-aliasing check looks two pixels out; cropping with
    # less margin than that miscounted ~5% of these (measured: pad 0 -> 21 of
    # 400, pad 1 -> 15, pad 2 and 3 -> 0)
    for _seed in range(60):
        _a, _b = scene(_seed, 0), scene(_seed, 1.0)
        _counted, _, _ = visual.compare(_a, _b, noise='strict')
        assert _counted == pixelmatch(_a, _b), _seed


class TestGoldens:

    def test_a_missing_golden_fails_and_says_how_to_make_one(self, tmp_path, case):
        _check = that(drawing(), '结算页').matches_golden('checkout')
        assert not _check.ok
        assert '没有基准图' in _check.expr and '--update-baseline' in _check.expr
        assert not os.path.exists(visual.golden_path('checkout', str(tmp_path / 'test_x.py'),
                                                     'chromium'))
        assert [_a['kind'] for _a in case.artifacts] == ['actual']

    def test_update_mode_writes_the_golden(self, tmp_path, case, monkeypatch):
        monkeypatch.setenv(visual.UPDATE_VAR, '1')
        _check = that(drawing(), '结算页').matches_golden('checkout')
        assert _check.ok
        monkeypatch.delenv(visual.UPDATE_VAR)
        assert that(drawing(), '结算页').matches_golden('checkout').ok

    def test_goldens_are_per_browser_and_platform(self, tmp_path):
        _path = visual.golden_path('checkout', str(tmp_path / 'sub' / 'test_x.py'), 'webkit')
        assert _path == str(tmp_path / 'sub' / '__goldens__' /
                            'checkout-webkit-{}.png'.format(sys.platform))

    def test_a_different_size_fails_with_both_sizes(self, tmp_path, case):
        golden(tmp_path, drawing())
        _check = that(drawing().resize((400, 210)), '结算页').matches_golden('checkout')
        assert not _check.ok and '400x200' in _check.expr and '400x210' in _check.expr

    def test_png_bytes_paths_and_images_are_all_accepted(self, tmp_path, case):
        _path = golden(tmp_path, drawing())
        _buf = io.BytesIO()
        drawing().save(_buf, format='PNG')
        assert that(_buf.getvalue()).matches_golden('checkout').ok
        assert that(_path).matches_golden('checkout').ok
        with pytest.raises(TypeError):
            visual._image(42)


class TestTheClaim:

    def test_every_loosening_setting_is_in_the_claim(self, tmp_path, case):
        golden(tmp_path, drawing())
        _base = that(drawing(), 'screen').matches_golden('checkout').claim
        for _kwargs in ({'tolerance': 0.01}, {'threshold': 0.3}, {'noise': 'strict'},
                        {'mask': [(0, 0, 10, 10)]}):
            assert that(drawing(), 'screen').matches_golden('checkout', **_kwargs).claim != _base

    def test_the_claim_names_the_golden_by_its_content(self, tmp_path, case):
        golden(tmp_path, drawing())
        _before = that(drawing()).matches_golden('checkout').claim
        golden(tmp_path, drawing(color=(22, 163, 74)))
        assert that(drawing()).matches_golden('checkout').claim != _before


# -- through run() --------------------------------------------------------------

SUITE = '''
    import os
    from PIL import Image, ImageDraw
    from ipandora.core.assertion import assert_all
    from ipandora.core.assertion.field import that

    def screen():
        img = Image.new('RGB', (300, 120), 'white')
        d = ImageDraw.Draw(img)
        d.rectangle((20, 20, 140, 60), fill=os.environ.get('BUTTON', '#2563eb'))
        return img

    def test_checkout():
        assert_all(that(screen(), '结算页').matches_golden('checkout'))
'''


@pytest.fixture
def project(tmp_path, monkeypatch):
    _dir = tmp_path / 'suite'
    _dir.mkdir()
    (_dir / 'test_screen.py').write_text(textwrap.dedent(SUITE), encoding='utf-8')
    monkeypatch.setenv('IPANDORA_CONFIG_DIR', str(tmp_path / 'no-conf'))
    monkeypatch.setenv('IPANDORA_RUNS_DIR', str(tmp_path / 'home' / 'runs'))
    monkeypatch.delenv('BUTTON', raising=False)
    return _dir


def go(target, **kwargs):
    kwargs.setdefault('persist', False)
    kwargs.setdefault('quiet', True)
    kwargs.setdefault('baseline', '')
    return run(str(target), **kwargs)


class TestThroughTheRunner:

    def test_the_golden_lifecycle(self, project, monkeypatch):
        # no golden: fails, and nothing is written
        _first = go(project)
        assert not _first.ok and '没有基准图' in _first.cases[0].message
        assert not (project / '__goldens__').exists()
        # --update-baseline writes it
        assert go(project, update_goldens=True).ok
        assert len(os.listdir(str(project / '__goldens__'))) == 1
        # the same image passes; a changed button fails, with all three images
        assert go(project).ok
        monkeypatch.setenv('BUTTON', '#16a34a')
        _changed = go(project)
        assert not _changed.ok
        assert {_a['kind'] for _a in _changed.cases[0].artifacts} == {'golden', 'actual', 'diff'}

    def test_the_report_shows_golden_actual_and_diff_side_by_side(self, project, monkeypatch):
        go(project, update_goldens=True)
        monkeypatch.setenv('BUTTON', '#16a34a')
        _html = to_html(build(go(project)))
        assert '图像判定 · checkout' in _html
        for _title in ('基准图', '实际', '差异'):
            assert _title in _html
        assert _html.count('data:image/png;base64,') >= 3

    def test_replacing_the_golden_is_caught_by_the_baseline_gate(self, project, monkeypatch):
        _accepted = go(project, update_goldens=True)
        _baseline = inventory.build(_accepted)
        # someone makes the test green by re-recording the golden over a regression
        monkeypatch.setenv('BUTTON', '#16a34a')
        _rerecorded = go(project, update_goldens=True)
        assert _rerecorded.ok                                  # green...
        _changes = inventory.compare(_baseline, _rerecorded)
        assert any(_f.weakening for _f in _changes), _changes  # ...but --fail-on-weakened stops it

    def test_parallel_runs_bring_the_images_back(self, project, monkeypatch):
        pytest.importorskip('xdist')
        go(project, update_goldens=True)
        monkeypatch.setenv('BUTTON', '#16a34a')
        _result = go(project, workers=2)
        assert {_a['kind'] for _a in _result.cases[0].artifacts} == {'golden', 'actual', 'diff'}
        assert all(os.path.exists(_a['path']) for _a in _result.cases[0].artifacts)


PAGE = ('<style>body{{font:16px sans-serif;margin:40px}}{extra}</style><h1>结算</h1>'
        '<p id="a">订单金额 100.50 元，含运费。</p>'
        '<button style="background:{color};color:#fff;border:0;padding:8px 16px">付款</button>')


@pytest.fixture(scope='module')
def shots():
    """What Chromium actually renders: the same page, and three variations of it."""
    pytest.importorskip('playwright')
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as _p:
            _browser = _p.chromium.launch()
            _page = _browser.new_page(viewport={'width': 800, 'height': 300})

            def _shot(color='#2563eb', extra=''):
                _page.set_content(PAGE.format(color=color, extra=extra))
                return _page.screenshot()
            _out = {'base': _shot(), 'again': _shot(),
                    'subpixel text': _shot(extra='#a{transform:translateX(.4px)}'),
                    'button colour': _shot(color='#16a34a')}
            _browser.close()
            return _out
    except Exception as exc:  # noqa: BLE001
        if os.environ.get('IPANDORA_REQUIRE_BROWSER'):
            pytest.fail('no browser: {}'.format(exc))
        pytest.skip('no browser: {}'.format(str(exc).splitlines()[0][:100]))


class TestRealBrowserScreenshots:

    def test_the_same_page_rendered_again_passes(self, tmp_path, case, shots):
        golden(tmp_path, Image.open(io.BytesIO(shots['base'])))
        assert that(shots['again']).matches_golden('checkout').ok

    def test_a_colour_change_fails_where_text_drift_is_absorbed_by_a_small_tolerance(
            self, tmp_path, case, shots):
        # A 0.4px shift of a paragraph depends on how the machine rasterises the
        # glyphs: 0 pixels left after the 3x3 filter locally, 18 (0.0075%) on a
        # GitHub runner, where dense CJK strokes still form small solid blocks.
        # A button changing colour is ~50 times that, so a 0.1% tolerance keeps
        # one and not the other.
        golden(tmp_path, Image.open(io.BytesIO(shots['base'])))
        assert shots['subpixel text'] != shots['base']        # it is a different image
        _shifted = that(shots['subpixel text']).matches_golden('checkout', tolerance=0.001)
        assert _shifted.ok, _shifted.expr
        _changed = that(shots['button colour']).matches_golden('checkout', tolerance=0.001)
        assert not _changed.ok and '位置' in _changed.expr
