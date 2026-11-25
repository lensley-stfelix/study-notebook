import tempfile
import unittest
from pathlib import Path

from PIL import Image
from study_notebook import (attach, load_lesson, new_lesson, save_lesson,
                            ordered_sources, ordered_lessons, write_order,
                            match_source_order, trash_lesson)


class NotebookTest(unittest.TestCase):
    def test_course_order_and_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sources = root / 'sources'
            sources.mkdir()
            first = sources / '001-z.md'
            second = sources / '002-a.md'
            tenth = sources / '010-b.md'
            for path, title in [(first, 'Zebra'), (second, 'Apple'), (tenth, 'Banana')]:
                path.write_text('# ' + title)
            self.assertEqual(ordered_sources([tenth, second, first]), [first, second, tenth])
            a = new_lesson(root, 'Apple', 'My annotations')
            b = new_lesson(root, 'Zebra')
            c = new_lesson(root, 'Banana')
            write_order(root, [a, c, b])
            reordered, count = match_source_order(ordered_lessons(root), [second, tenth, first])
            self.assertEqual((reordered, count), ([b, a, c], 3))
            write_order(root, reordered)
            self.assertEqual(ordered_lessons(root), [b, a, c])
            saved = trash_lesson(root, a)
            self.assertEqual(ordered_lessons(root), [b, c])
            self.assertEqual(load_lesson(saved)['text'], 'My annotations')
            saved.rename(a)
            write_order(root, [b, c, a])
            self.assertEqual(ordered_lessons(root), [b, c, a])

    def test_media_persistence_and_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = new_lesson(root, 'Lesson <1>', 'Original notes')
            note = load_lesson(folder)
            image_marker = attach(folder, note, image=Image.new('RGB', (3, 3), 'red'))
            clip = root / 'lecture.mp4'
            clip.write_bytes(b'test video bytes')
            video_marker = attach(folder, note, source=clip)
            note['text'] += '\n' + image_marker + '\n' + video_marker
            save_lesson(folder, note)
            self.assertEqual(load_lesson(folder), note)
            html = (folder / 'lesson.html').read_text()
            self.assertIn('Lesson &lt;1&gt;', html)
            self.assertIn('Original notes', html)
            self.assertIn('<img src="media/', html)
            self.assertIn('<video controls', html)
            md = (folder / 'lesson.md').read_text()
            self.assertIn('![Clipboard image.png](media/', md)
            self.assertIn('[lecture.mp4](media/', md)
            self.assertEqual(len(list((folder / 'media').iterdir())), 2)
            self.assertTrue(clip.exists())

    def test_unsupported_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = new_lesson(root, 'Notes')
            with self.assertRaises(ValueError):
                attach(folder, load_lesson(folder), source=root / 'invalid.exe')


if __name__ == '__main__':
    unittest.main()
