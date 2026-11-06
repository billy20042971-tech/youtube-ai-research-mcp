import unittest
import json
from unittest.mock import patch

from scripts import content_enrichment


class ContentEnrichmentTests(unittest.TestCase):
    def test_translation_uses_taiwan_traditional_chinese_locale(self):
        payload = json.dumps([[["這是繁體中文", "This is Chinese"]], None, "en"], ensure_ascii=False).encode("utf-8")
        with patch.object(content_enrichment, "_get", return_value=payload) as get:
            translated = content_enrichment.translate_to_traditional_chinese("This is Chinese")
        self.assertEqual(translated, "這是繁體中文")
        self.assertIn("tl=zh-TW", get.call_args.args[0])

    def test_translation_failure_returns_empty_without_fabrication(self):
        with patch.object(content_enrichment, "_get", side_effect=TimeoutError):
            self.assertEqual(content_enrichment.translate_to_traditional_chinese("Unknown text"), "")

    def test_extracts_timestamped_chapters(self):
        chapters = content_enrichment.extract_chapters(
            "00:00 Introduction\n01:25 Build the workflow\n12:40 Results"
        )
        self.assertEqual(chapters, ["Introduction", "Build the workflow", "Results"])

    def test_enriches_from_existing_transcript_and_chapters_without_network(self):
        video = {
            "title": "Research workflow",
            "description": "short",
            "transcript": "A transcript with enough details.",
            "chapters": ["Introduction", "Demonstration"],
        }
        with patch.object(content_enrichment, "translate_to_traditional_chinese", return_value="逐字稿繁體中文"):
            result = content_enrichment.enrich_video_content(video, fetch_transcript=False)
        self.assertEqual(result["transcript_zh"], "逐字稿繁體中文")
        self.assertEqual(result["chapters"], ["Introduction", "Demonstration"])


if __name__ == "__main__":
    unittest.main()
