import unittest

from backend.main import SIZES, extract_page, make_srt, shape_text


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

    def test_srt_has_contiguous_caption_timecodes(self):
        result = make_srt(["First caption", "Second caption"], [2.5, 3.0])
        self.assertIn("00:00:00,000 --> 00:00:02,500", result)
        self.assertIn("00:00:02,500 --> 00:00:05,500", result)
        self.assertEqual(result.count("-->"), 2)

    def test_urdu_text_shaper_keeps_text(self):
        original = "اردو ویڈیو"
        self.assertTrue(shape_text(original, True))

    def test_all_video_shapes_are_supported(self):
        self.assertEqual(SIZES["vertical"], (1080, 1920))
        self.assertEqual(SIZES["landscape"], (1920, 1080))
        self.assertEqual(SIZES["square"], (1080, 1080))

    def test_extract_uses_description_when_body_is_short(self):
        html = """
        <html><head><title>Short page</title>
        <meta name="description" content="A useful description for this simple webpage.">
        </head><body><p>Short.</p></body></html>
        """
        _, description, _, paragraphs, language = extract_page(
            html, "https://example.com/"
        )
        self.assertIn("useful description", description)
        self.assertTrue(paragraphs)
        self.assertEqual(language, "English")


if __name__ == "__main__":
    unittest.main()
