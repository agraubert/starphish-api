from .app import app
from . import utils, feed
from flask import request, redirect, make_response
import requests
import os
from datetime import datetime, timedelta
import traceback
import sqlalchemy as sqla
from hashlib import sha256
import pandas as pd
import json

@app.errorhandler(404)
@utils.log_request
def NotFound(err=None):
    return 'Not Found', 404

@utils.log_request
def blacklist_ip():
    with utils.Database.get_db(app.config) as db:
        db.insert(
            'blacklist',
            ip=request.remote_addr,
            timestamp=datetime.now(),
            endpoint=request.path[:256]
        )
    return "Repeated suspicious activity will result in blacklisting", 404

black_routes = []
if os.path.exists(os.path.join(os.path.dirname(__file__), 'blacklist.txt')):
    with open(os.path.join(os.path.dirname(__file__), 'blacklist.txt')) as r:
        black_routes = [line.strip() for line in r]

if 'BLACKLIST_ROUTES' in app.config:
    black_routes += app.config['BLACKLIST_ROUTES']

for route in black_routes:
    blacklist_ip = app.route('/{}'.format(route))(blacklist_ip)
    print("Blacklisting route", route)

@app.route('/')
@utils.log_request
def redir():
    return redirect("https://starphish.wixsite.com/my-site")

@app.route('/api/marco')
@utils.log_request
def marco():
    return "Polo"

@app.route('/api/_internal/request_log')
@utils.log_request
def request_logs():
    if 'token' not in request.args or request.args['token'] != app.config['INTERNAL_TOKEN']:
        return NotFound.not_logged()

    with utils.Database.get_db(app.config) as db:
        return db.read_table('requests').set_index('id').to_html(), 200

@app.route('/api/_internal/request_log/recent')
@utils.log_request
def request_recent_logs():
    if 'token' not in request.args or request.args['token'] != app.config['INTERNAL_TOKEN']:
        return NotFound.not_logged()

    with utils.Database.get_db(app.config) as db:
        table = db['requests']
        return db.query(
            table.select.order_by(sqla.desc(table.c.id)).limit(1000)
        ).sort_values('id').set_index('id').to_html(), 200

@app.route('/api/safebrowse/hot')
@utils.log_request
@utils.rate_limit(10)
def hot_queries(): # in your area
    """
    Get a list of the top 5 safebrowse queries from the last day (ish)
    """
    return feed.hot().to_json(), 200

@app.route('/api/safebrowse', methods=['POST'])
@utils.log_request
@utils.enforce_content_length
@utils.rate_limit(10)
def safebrowse():
    try:

        data = request.get_json()
        if not isinstance(data, dict):
            return utils.error("Expected request body to be a JSON dictionary", data=data)

        if 'urls' not in data:
            return utils.error('Request body missing required field "urls"', data=data)

        if not isinstance(data['urls'], list):
            return utils.error('Invalid request format. "urls" must be a list', data=data)

        if not len(data['urls']):
            return utils.error('Invalid request format. Empty list of urls', data=data)

        cached = False

        query_urls = []
        cache_matches = {}
        actual_urls = []

        with utils.Database.get_db(app.config) as db:
            pt = db['phishing']
            table = db['safebrowse_cache']
            results = db.query(
                table.select.where(
                    table.c.expires > sqla.text(datetime.now().strftime("'%Y-%m-%d %H:%M:%S'"))
                )
            )
            for url in utils.standardize_urls(data['urls']):
                actual_urls.append(url)
                pt_result = db.query(
                    pt.select.where(
                        pt.c.url == url
                    )
                )
                if len(pt_result):
                    cache_matches[url] = 'SOCIAL_ENGINEERING'
                if url in results['url'].unique():
                    cached = True
                    if not results[results['url'] == url]['safe'].all():
                        cache_matches[url] = results[results['url'] == url].query('type == type')['type'].values[-1]
                else:
                    query_urls.append(url)

        response = requests.post(
            'https://safebrowsing.googleapis.com/v4/threatMatches:find',
            params={'key': app.config['SAFEBROWSING_API_KEY']},
            json={
                "client": {
                    "clientId": "starphish",
                    "clientVersion": "0.0.1"
                },
                "threatInfo": {
                    "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE"],
                    "platformTypes": ["ANY_PLATFORM", "WINDOWS", "OSX", "LINUX"],
                    "threatEntryTypes": ["URL"],
                    "threatEntries": [
                        {'url': url}
                        for url in query_urls
                    ]
                }
            }
        )
        if response.status_code != 200:
            return utils.error(
                "Unexpected response code from Google's Safebrowsing API",
                data={'raw_response': response.text},
                context=data,
                code=response.status_code if response.status_code >= 400 else 500
            )
        response_data = response.json()
        unsafe = {match['threat']['url'] for match in response_data['matches']} if 'matches' in response_data else set()
        now = datetime.now()

        def inline_filter(data):
            seen = set()
            for match in data:
                if match['threat']['url'] not in seen:
                    yield match
                seen.add(match['threat']['url'])

        with utils.Database.get_db(app.config) as db:
            db.multi_insert(
                'safebrowse_cache',
                ([
                    {
                        'url': match['threat']['url'],
                        'url_hash': sha256(url.encode()).hexdigest(),
                        'expires': now + timedelta(seconds=300),
                        'safe': False,
                        'type': match['threatType']
                    }
                    for match in inline_filter(response_data['matches'])
                ] if 'matches' in response_data else [])
            )
        return {
            'success': True,
            'length': len(cache_matches) + (len(response_data['matches']) if 'matches' in response_data else 0),
            'urls_standardized': actual_urls,
            'matches': [
                {
                    'url': url,
                    'threatType': threat
                }
                for url, threat in cache_matches.items()
            ] + (
                [
                    {
                        'url': match['threat']['url'],
                        'threatType': match['threatType']
                    }
                    for match in response_data['matches']
                ]
                if 'matches' in response_data else []
            ),
            'cached': cached,
        }
    except:
        return utils.error(
            "Unexpected internal server error",
            data={
                'traceback': traceback.format_exc()
            },
            code=500
        )

@app.route('/api/feed')
@utils.log_request
@utils.rate_limit(12)
def generate_feed():
    def record_source(df, source):
        if 'source' not in df:
            df['source'] = [source]*len(df)
        return df
    try:
        feed_type = request.args.get('type', 'all')
        if feed_type not in feed.PROVIDERS:
            return utils.error(
                "Invalid feed type",
                data={'allowed_types': [*feed.PROVIDERS], 'requested_type': feed_type},
                code=400
            )
        elif feed_type != 'all':
            return feed.PROVIDERS[feed_type]().to_json(orient='index'), 200
        merged_df =  pd.concat([
            record_source(provider(), source)
            for source, provider in feed.PROVIDERS.items()
            if provider is not None
        ], axis='rows').sort_values('last_report', ascending=False)
        merged_df = merged_df[~merged_df.index.duplicated(keep='first')]
        return merged_df.to_json(orient='index'), 200

    except:
        return utils.error(
            "Unexpected internal server error",
            data={
                'traceback': traceback.format_exc()
            }, code=500
        )

@app.route('/api/visitors')
@utils.log_request
def visitor_count():
    with utils.Database.get_db(app.config) as db:
        table = db['requests']
        return {
            'total': int(
                db.query(
                    sqla.select(sqla.func.count(sqla.distinct(table.c.ip))).select_from(table.table).where(
                        table.c.endpoint == sqla.text('"/ (redir)"')
                    )
                )['count_1'][0]
            ),
            'today': int(
                db.query(
                    sqla.select(sqla.func.count(sqla.distinct(table.c.ip))).select_from(table.table).where(
                        table.c.time > sqla.text((datetime.now() - timedelta(days=1)).strftime("'%Y-%m-%d %H:%M:%S'"))
                    ).where(
                        table.c.endpoint == sqla.text('"/ (redir)"')
                    )
                )['count_1'][0]
            )
        }, 200


RSS_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
<channel>
<title>Starphish Phishing Threat Feed</title>
<link>https://starphish.org/api/feed</link>
<description>Recent Phishing Threats</description>
{items}
</channel>
</rss>
"""

ITEM_TEMPLATE = """<item>
<title>{title}</title>
<guid>{title}</guid>
<pubDate>{date}</pubDate>
<description>Malicious phishing site reported by {source}</description>
</item>
"""

def generate_rss_content():
    def record_source(df, source):
        if 'source' not in df:
            df['source'] = [source]*len(df)
        return df
    feed_type = request.args.get('type', 'all')
    if feed_type not in feed.PROVIDERS:
        raise RuntimeError("Lazy")
    elif feed_type != 'all':
        return feed.PROVIDERS[feed_type]().to_dict(orient='index')
    merged_df =  pd.concat([
        record_source(provider(), source)
        for source, provider in feed.PROVIDERS.items()
        if provider is not None
    ], axis='rows').sort_values('last_report', ascending=False)
    merged_df = merged_df[~merged_df.index.duplicated(keep='first')]
    return merged_df.to_dict(orient='index')

@app.route("/rss")
def rss():
    feed_content = generate_rss_content()
    response = make_response(
        RSS_TEMPLATE.format(items="\n".join(
            ITEM_TEMPLATE.format(
                title=key,
                url="#",
                date=data['last_report'].strftime("%a, %d %b %Y %H:%M:%S -0600"),
                source=data['source'],
            )
            for key, data in feed_content.items()
        )), 200
    )
    response.headers['Content-Type'] = 'application/rss+xml'
    return response
