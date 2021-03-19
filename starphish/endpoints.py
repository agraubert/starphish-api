from .app import app
from . import utils
from flask import request, redirect
import requests
import os
import traceback


@app.errorhandler(404)
@utils.log_request
def NotFound(err=None):
    return 'Not Found', 404

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
        print(db._tables)
        return db.read_table('requests').to_html(), 200

@app.route('/api/safebrowse', methods=['POST'])
@utils.log_request
@utils.enforce_content_length
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

        response = requests.post(
            'https://safebrowsing.googleapis.com/v4/threatMatches:find',
            params={'key': app.config['SAFEBROWSING_API_KEY']},
            json={
                "client": {
                    "clientId": "starphish",
                    "clientVersion": "0.0.1"
                },
                "threatInfo": {
                    # FIXME: Get full list of threat types
                    "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING"],
                    "platformTypes": ["WINDOWS"],
                    "threatEntryTypes": ["URL"],
                    "threatEntries": [
                        {'url': url}
                        for url in data['urls']
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
        return {
            'success': True,
            'length': len(response_data['matches']) if 'matches' in response_data else 0,
            'matches': response_data['matches'] if 'matches' in response_data else [],
        }
    except:
        return utils.error(
            "Unexpected internal server error",
            data={
                'traceback': traceback.format_exc()
            },
            code=500
        )
