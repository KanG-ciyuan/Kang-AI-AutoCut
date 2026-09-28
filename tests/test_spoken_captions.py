"""Deterministic caption rules and the existing production execution seam."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from PIL import ImageFont
from src.ai_autocut.spoken_captions import CaptionError, compile_captions, render_states
from src.ai_autocut import execution_adapters as execution


def font(size):
    for name in ('Arial Bold.ttf', 'DejaVuSans-Bold.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    raise unittest.SkipTest('a bold test font is required')


def timing(copy):
    return [dict(text=w, start=i * .4, end=i * .4 + .25) for i, w in enumerate(copy.split())]


def plan(copy='Coba arahkan air ke sini.', words=None, **kwargs):
    options = dict(duration=20, width=360, height=640, font_loader=font)
    options.update(kwargs)
    return compile_captions(copy, timing(copy) if words is None else words, **options)


class CaptionTests(unittest.TestCase):
    def test_punctuation_and_pause_grouping(self):
        copy = 'Lihat ini, lalu arahkan air ke sini.'
        words = timing(copy)
        words[4]['start'] += .15  # .30 second measured pause
        result = plan(copy, words)
        self.assertEqual([len(p.words) for p in result.phrases], [2, 2, 3])

    def test_balanced_grouping_avoids_fixed_five_plus_one(self):
        self.assertEqual([len(p.words) for p in plan('a b c d e f').phrases], [3, 3])

    def test_producer_semantic_boundaries_override_heuristic(self):
        result = plan('a b c d e f', phrase_ends=[2, 6])
        self.assertEqual([len(p.words) for p in result.phrases], [2, 4])
        with self.assertRaises(CaptionError):
            plan('a b c', phrase_ends=[2])

    def test_actual_nonuniform_timing_and_silent_gap(self):
        words = [dict(text='Coba', start=.1, end=.23), dict(text='ini.', start=.4, end=.9)]
        phrase = plan('Coba ini.', words).phrases[0]
        self.assertEqual(phrase.active_word(.15), 0)
        self.assertIsNone(phrase.active_word(.3))
        self.assertEqual(phrase.active_word(.8), 1)
        self.assertIsNone(phrase.active_word(.9))
        states = list(render_states(plan('Coba ini.', words), font))
        self.assertEqual([(s, e, a) for _, s, e, a in states], [(.1, .23, 0), (.23, .4, None), (.4, .9, 1)])

    def test_reject_missing_changed_reordered_words(self):
        for words in ([], timing('Coba hasil.'), timing('ini. Coba')):
            with self.subTest(words=words), self.assertRaises(CaptionError):
                plan('Coba ini.', words)

    def test_reject_invalid_timing(self):
        for start, end in ((-1, .2), (.2, .2), (.3, .2), (0, 30), (float('nan'), .2), (0, float('inf'))):
            with self.subTest(start=start, end=end), self.assertRaises(CaptionError):
                plan('Coba', [dict(text='Coba', start=start, end=end)])
        with self.assertRaises(CaptionError):
            plan('a b', [dict(text='a', start=0, end=1), dict(text='b', start=.8, end=2)])

    def test_unicode_case_punctuation_preserved_from_approval(self):
        result = plan('CAFÉ, bukan 100%!', timing('café bukan 100'))
        self.assertEqual([w.text for p in result.phrases for w in p.words], ['CAFÉ,', 'bukan', '100%!'])

    def test_adaptive_safe_area_and_two_line_limit(self):
        for width, height in ((360, 640), (720, 1280), (640, 360), (640, 640)):
            with self.subTest(canvas=(width, height)):
                result = plan(width=width, height=height)
                l, t, r, b = result.rect
                self.assertGreaterEqual(l, width * .08)
                self.assertLessEqual(r, width * .84)
                self.assertGreaterEqual(t, height * .5)
                self.assertLessEqual(b, height * .84)
                self.assertTrue(all(len(p.lines) <= 2 for p in result.phrases))
                for image, *_ in render_states(result, font):
                    x1, y1, x2, y2 = image.getbbox()
                    self.assertTrue(l <= x1 <= x2 <= r and t <= y1 <= y2 <= b)

    def test_refuse_unreadable_layout_and_title_collision(self):
        for kwargs in (dict(safe_area=(.49, .1, .49, .2)), dict(safe_area=(.1, .8, .1, .3)),
                       dict(reserved=[(0, 400, 360, 640)])):
            with self.subTest(kwargs=kwargs), self.assertRaises(CaptionError):
                plan(**kwargs)
        plan(reserved=[(0, 0, 360, 100)])

    def test_deterministic_pixels_and_single_highlight(self):
        first = list(render_states(plan('Coba ini.'), font))
        second = list(render_states(plan('Coba ini.'), font))
        self.assertEqual([x[0].tobytes() for x in first], [x[0].tobytes() for x in second])
        self.assertNotEqual(first[0][0].tobytes(), first[-1][0].tobytes())
        gap = next(image for image, _, _, active in first if active is None)
        self.assertNotIn((255, 217, 102, 255), set(gap.getdata()))


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class CaptionExecutionTests(unittest.TestCase):
    def fixture(self, root, width=360, height=640):
        (root / 'typography').mkdir()
        (root / 'copy.txt').write_text('Coba ini.', encoding='utf-8')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        f'color=c=blue:s={width}x{height}:r=10:d=1', '-c:v', 'libx264',
                        str(root / 'picture.mp4')], check=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'anullsrc=r=16000:cl=mono', '-t', '1', str(root / 'vo.wav')], check=True)
        digest = lambda name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        alignment = dict(copy_sha256=digest('copy.txt'), audio_path='vo.wav',
                         audio_sha256=digest('vo.wav'), timing_source='manual_measured',
                         words=timing('Coba ini.'))
        (root / 'alignment.json').write_text(json.dumps(alignment))
        request = dict(master='picture.mp4', out='typography/result.mp4',
                       width=width, height=height, fps=10, frame_count=10,
                       font_stack=[str(font(20).path)],
                       events=[dict(lines=['COBA'], start_frame=0, end_frame_exclusive=10)],
                       layout=dict(baseline_y=80, left_margin=25, size_l1=28, size_l2=22, fill=[255,255,255,255]),
                       spoken_captions=dict(approved_copy='copy.txt', alignment='alignment.json'))
        (root / 'typography/typography_request.json').write_text(json.dumps(request))
        return request

    def test_existing_typography_renders_independent_title_and_caption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            result = execution.execute_typography(root)
            self.assertEqual(result['frame_count'], 10)
            self.assertEqual(result['events_rendered'], 1)
            self.assertEqual(result['spoken_captions']['word_count'], 2)
            # Decode an active caption frame, verify both spatial layers exist.
            out = subprocess.run(['ffmpeg', '-v', 'error', '-ss', '0.1', '-i',
                                  str(root / result['path']), '-frames:v', '1',
                                  '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True).stdout
            from PIL import Image
            image = Image.frombytes('RGB', (360, 640), out)
            for box in ((0, 0, 360, 120), (0, 350, 360, 550)):
                self.assertTrue(any(r > 150 and g > 150 for r, g, b in image.crop(box).getdata()))

    def test_existing_art_direction_path_accepts_caption_layer(self):
        from src.ai_autocut.typography_renderer import RenderProfile
        profile_path = Path(__file__).resolve().parents[1] / 'examples/typography/art-direction-a-v1.profile.json'
        profile = RenderProfile.load(profile_path)
        if not Path(profile.font_path).is_file():
            self.skipTest('existing Art Direction fixture font is unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = self.fixture(root, 1080, 1920)
            request.pop('layout')
            request['art_direction'] = dict(profile=str(profile_path))
            request['events'][0]['narrative_role'] = 'HOOK'
            (root / 'typography/typography_request.json').write_text(json.dumps(request))
            result = execution.execute_typography(root)
            self.assertEqual(result['art_direction'], profile.profile_id)
            self.assertEqual(result['spoken_captions']['word_count'], 2)
            self.assertEqual(result['frame_count'], 10)

    def test_caption_only_and_actual_title_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = self.fixture(root)
            request['layout']['baseline_y'] = 520
            (root / 'typography/typography_request.json').write_text(json.dumps(request))
            with self.assertRaisesRegex(execution.ExecutionAdapterError, 'overlaps'):
                execution.execute_typography(root)
            request['events'] = []
            (root / 'typography/typography_request.json').write_text(json.dumps(request))
            result = execution.execute_typography(root)
            self.assertEqual(result['events_rendered'], 0)
            self.assertEqual(result['spoken_captions']['word_count'], 2)

    def test_reject_stale_final_audio_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            with (root / 'vo.wav').open('ab') as f:
                f.write(b'changed')
            with self.assertRaisesRegex(execution.ExecutionAdapterError, 'hash mismatch'):
                execution.execute_typography(root)


if __name__ == '__main__':
    unittest.main()
