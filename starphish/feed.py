from flask import current_app
from . import utils
from datetime import datetime, timedelta
import sqlalchemy as sqla

PROVIDERS = {'all':None}

def mark_provider(func):
    PROVIDERS[func.__name__] = func
    return func

@mark_provider
def phishtank():
    """
    Fetch the latest phishtank results for the feed
    """
    with utils.Database.get_db(current_app.config) as db:
        table = db['phishtank']
        maxt = db.query(
            sqla.select(sqla.func.max(table.c.added)).select_from(table.table)
        )
        results = db.query(
            table.select.where(
                table.c.added > sqla.text((maxt['max_1'][0] - timedelta(minutes=5)).strftime("'%Y-%m-%d %H:%M:%S'"))
            )
        )
    results = results.set_index('url').sort_values('added')
    results = results[~results.index.duplicated(keep='last')]
    return results[['added']].rename({'added': 'last_report'}, axis='columns')


@mark_provider
def hot():
    """
    Get a list of 'trending' safebrowse threats.
    The top 5 most checked urls with either 25 or more recent queries or which are
    marked as unsafe
    """
    with utils.Database.get_db(current_app.config) as db:
        table = db['safebrowse_cache']
        df = db.query(
            sqla.select(
                table.c.url, sqla.func.count(), sqla.func.max(table.c.expires)
            ).select_from(table.table).where(
                table.c.expires > sqla.text((
                    datetime.now() - timedelta(days=1)
                ).strftime("'%Y-%m-%d %H:%M:%S'"))
            ).group_by(table.c.url).having(
                (sqla.func.count() > 25) | (sqla.func.sum(table.c.safe) == 0)
            ).order_by(sqla.desc(sqla.func.count())).limit(5)
        )
    return df.set_index('url').rename({'count_1': 'count', 'max_1': 'last_report'}, axis='columns')
