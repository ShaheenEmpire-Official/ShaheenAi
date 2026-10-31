import unittest

from backend.main import extract_page, make_srt, shape_text


class EngineTests(unittest.TestCase):
    def test_extracts_english_article(self):
        html = """
        <html><head><title>Example News</title>
        <meta name="description" content="A useful short description.">
        </head><body><h1>Main heading</h1>
        <p>This is a sufficiently long paragraph containing useful information for a short explainer video.</p>
        </body></html>
        """
        title, description, headings, paragraphs, language = extract_page(
            html, "https://example.com/story"
        )
        self.assertEqual(title, "Example News")
        self.assertIn("short description", description)
        self.assertEqual(language, "English")
        self.assertTrue(paragraphs)

    def test_detects_urdu_script(self):
        html = """
        <html><head><title>اردو خبر</title></head>
        <body><p>یہ ایک معلوماتی مضمون ہے جس میں اہم تفصیلات بیان کی گئی ہیں۔</p></body></html>
        """
        _, _, _, paragraphs, language = extract_page(html, "https://example.com/ur")
        self.assertEqual(language, "Urdu")
        self.assertTrue(paragraphs)

    def test_srt_has_caption_timecodes(self):
        result = make_srt(["First caption", "Second caption"], [2.5, 3.0])
        self.assertIn("00:00:00,000 --> 00:00:02,500", result)
        self.assertIn("00:00:02,500 --> 00:00:05,500", result)

    def test_urdu_text_shaper_keeps_text(self):
        original = "اردو ویڈیو"
        self.assertTrue(shape_text(original, True))


if __name__ == "__main__":
    unittest.main()
