from .app import app
from . import utils
from flask import request, redirect
import requests
import os
from datetime import datetime, timedelta
import traceback
import sqlalchemy as sqla
from hashlib import sha256

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

@app.route('/api/safebrowse/hot')
@utils.log_request
@utils.rate_limit(10)
def hot_queries(): # in your area
    with utils.Database.get_db(app.config) as db:
        table = db['safebrowse_cache']
        df = db.query(
            sqla.select(
                table.c.url, sqla.func.count()
            ).select_from(table.table).where(
                table.c.expires > sqla.text(datetime.now().strftime("'%Y-%m-%d %H:%M:%S'"))
            ).group_by(table.c.url).limit(5)
        )
    return df.set_index('url').rename({'count_1': 'count'}, axis='columns').to_json(), 200

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
            table = db['safebrowse_cache']
            results = db.query(
                table.select.where(
                    table.c.expires > sqla.text(datetime.now().strftime("'%Y-%m-%d %H:%M:%S'"))
                )
            )
            for url in utils.standardize_urls(data['urls']):
                actual_urls.append(url)
                if url in results['url'].unique():
                    cached = True
                    if not results[results['url'] == url]['safe'].all():
                        cache_matches[url] = results[results['url'] == url].query('type == type')['type'][-1]
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
                    for match in response_data['matches']
                ] if 'matches' in response_data else []) + [
                    {
                        'url': url,
                        'url_hash': sha256(url.encode()).hexdigest(),
                        'expires': now + timedelta(seconds=60),
                        'safe': True,
                    }
                    for url in query_urls if url not in unsafe
                ]
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
