import unittest
from types import SimpleNamespace
from transcript import video_id, markdown


class Captions(list):
    video_id = 'abcdefghijk'
    language = 'Русский'
    language_code = 'ru'
    is_generated = True


class Tests(unittest.TestCase):
    def test_supported_links(self):
        for url in ['https://youtu.be/abcdefghijk?si=foo',
                    'https://www.youtube.com/watch?v=abcdefghijk&list=foo',
                    'https://youtube.com/shorts/abcdefghijk',
                    'https://youtube.com/live/abcdefghijk']:
            self.assertEqual(video_id(url), 'abcdefghijk')

    def test_invalid_links(self):
        for url in ['https://youtube.com.evil.test/watch?v=abcdefghijk',
                    'file:///abcdefghijk', 'https://youtu.be/short',
                    'https://youtube.com/playlist?list=abcdefghijk']:
            with self.assertRaises(ValueError):
                video_id(url)

    def test_text_and_timestamps(self):
        text = markdown(Captions([SimpleNamespace(start=3661.7, text='Привет\n<script> *мир*')]))
        self.assertIn('[01:01:01]', text)
        self.assertIn('&t=3661s', text)
        self.assertIn('Привет &lt;script&gt; \\*мир\\*', text)
        self.assertIn('автоматические', text)


if __name__ == '__main__':
    unittest.main()
