"""Little Atlas product and RSS checks without paid API requests."""
import io
import os
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import generate_pin as pins
import pin_feed


class LittleAtlasTests(unittest.TestCase):
    def test_every_topic_has_little_atlas_brief(self):
        self.assertEqual(pins.TYPE_ORDER, ['strengths', 'parenting', 'mandala', 'keepsake', 'free_atlas'])
        for topic in pins.TYPE_ORDER:
            prompt = pins.copy_prompt(topic)
            self.assertIn('Little Atlas', prompt)
            self.assertIn('not psychological assessment', prompt)
            self.assertTrue(pins.PIN_TYPES[topic]['board'].startswith('Little Atlas'))
            self.assertNotIn('com.faceslimmer.app', prompt)

    def test_copy_requires_brand_and_rejects_unsupported_claims(self):
        self.assertTrue(pins.copy_problems({'description': 'A family keepsake.'}))
        self.assertFalse(pins.copy_problems({'description': 'Explore a symbolic child profile with Little Atlas.'}))
        self.assertTrue(pins.copy_problems({'description': "Little Atlas predicts your child's future."}))

    @patch.dict(os.environ, {'SITE_URL': 'https://little-atlas.com'})
    def test_manual_link_and_rss_use_same_website(self):
        for topic in pins.TYPE_ORDER:
            self.assertEqual(pins.pin_link(topic), pin_feed.landing_link('https://little-atlas.com', topic))
            board = pins.PIN_TYPES[topic]['board']
            root = ET.fromstring(pin_feed.render_feed('https://little-atlas.com', board, []))
            self.assertTrue(root.findtext('channel/title').startswith('Little Atlas'))
            self.assertNotIn('Face Slimmer', root.findtext('channel/description'))

    def test_little_atlas_artwork_renders(self):
        raw = pins.compose(Image.new('RGB', (1000, 1500)), 'Discover Your Child’s Strengths', 'A gentle starting point')
        self.assertEqual(Image.open(io.BytesIO(raw)).size, (1000, 1500))


if __name__ == '__main__':
    unittest.main()
