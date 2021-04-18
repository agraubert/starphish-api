"""
This migration renames the phishtank table to phishing
and adds the source column
"""
from ... import utils
import sqlalchemy as sqla
import argparse

if __name__ == '__main__':
    parser = argparse.ArgumentParser('migration')
    parser.add_argument('url')

    args = parser.parse_args()

    with utils.Database(args.url, echo=True) as db:
        db.execute(
            sqla.text(
                "alter table phishtank add column source varchar(16);"
            )
        )
        db.execute(
            sqla.text(
                'update phishtank set source = "phishtank";'
            )
        )
        db.execute(
            sqla.text(
                "alter table phishtank rename to phishing;"
            )
        )
