"""Allocate missing-polygon Bad beans without changing original annotations.

Run from the project directory after migration 006. Defaults to a dry run.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
import psycopg2
import psycopg2.extras
from db import _db_config


def allocate(conn, username, execute=False):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id FROM annotators WHERE lower(username)=lower(%s) AND is_active AND role='annotator'", (username,))
        target = cur.fetchone()
        if not target:
            raise ValueError("Active reviewer not found.")
        cur.execute("""SELECT src.id, src.image_id, src.assigned_by_admin
            FROM assignments src JOIN annotations a ON a.assignment_id=src.id
            WHERE src.assignment_kind='primary' AND src.status='done'
              AND src.annotator_id<>%s AND a.overall_severity=2
              AND a.skip_reason IS NULL AND a.defects='[]'::jsonb
              AND NOT EXISTS (SELECT 1 FROM assignments r WHERE r.source_assignment_id=src.id
                              AND r.assignment_kind='polygon_review')
            ORDER BY src.id""", (target['id'],))
        rows = cur.fetchall()
        assigned = 0
        for row in rows if execute else []:
            cur.execute("""INSERT INTO assignments
                (image_id, annotator_id, assigned_by_admin, assignment_kind, source_assignment_id, metadata)
                VALUES (%s,%s,%s,'polygon_review',%s,%s::jsonb)
                ON CONFLICT (source_assignment_id) WHERE assignment_kind='polygon_review' DO NOTHING
                RETURNING id""", (row['image_id'], target['id'], row['assigned_by_admin'], row['id'],
                                      json.dumps({'reason': 'Bad label missing defect polygons'})))
            assigned += int(cur.fetchone() is not None)
        return {'target': username, 'candidates': len(rows), 'assigned': assigned}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', default='lovepreet123456')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    config = _db_config()
    config['connect_timeout'] = 20
    with psycopg2.connect(**config) as conn:
        print(json.dumps(allocate(conn, args.username, args.execute)))
