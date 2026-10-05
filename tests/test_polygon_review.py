import unittest
from unittest.mock import MagicMock, patch
from contextlib import contextmanager

import db


class PolygonReviewTests(unittest.TestCase):
    def test_valid_polygon(self):
        db.validate_polygon_review(2, [{'shape': 'polygon', 'polygon': [
            {'x': 0, 'y': 0}, {'x': 10, 'y': 0}, {'x': 10, 'y': 10}]}], None)

    def test_invalid_reviews(self):
        for severity, defects, skip in [(1, [], None), (2, [], None), (2, [], 'skip'),
            (2, [{'shape': 'polygon', 'polygon': [{'x': 0, 'y': 0}]*3}], None)]:
            with self.subTest(severity=severity, defects=defects, skip=skip):
                with self.assertRaises(ValueError):
                    db.validate_polygon_review(severity, defects, skip)

    def test_unowned_assignment_cannot_save(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        @contextmanager
        def connection():
            yield conn
        with patch.object(db, 'get_conn', connection):
            with self.assertRaises(ValueError):
                db.save_annotation('assignment', 'other-user', 2, '', [])
        self.assertEqual(cur.execute.call_count, 1)


if __name__ == '__main__':
    unittest.main()
