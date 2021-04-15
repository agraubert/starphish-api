import argparse
import requests
from ... import utils
from hashlib import sha256
from datetime import datetime
import sqlalchemy as sqla


if __name__ == '__main__':
    parser = argparse.ArgumentParser('starphish-phishtank-full')
    parser.add_argument(
        'url',
        help='URL for the database'
    )

    args = parser.parse_args()

    response = requests.get(
        'https://raw.githubusercontent.com/mitchellkrogza/Phishing.Database/master/phishing-links-NEW-last-hour.txt'
    )

    if response.status_code == 200:
        key = sha256(response.content).hexdigest()
        with utils.Database.init_with_url(args.url) as db:
            log_table = db['phishtank_log']
            results = db.query(
                log_table.select.where(
                    log_table.c.hash == key
                )
            )
            if len(results):
                print("Skipping duplicate Phishtank update")
                print("Last updated:", max(results['time']))
            else:
                update = [
                    {
                        'url': line.strip(),
                        'url_hash': sha256(line.strip().encode()).hexdigest(),
                        'added': datetime.now()
                    }
                    for line in response.text.split('\n')
                    if len(line.strip())
                ]
                db.multi_insert(
                    'phishtank',
                    update
                )
                print("Added", len(update), "links")
                db.insert(
                    'phishtank_log',
                    time=datetime.now(),
                    length=len(update),
                    hash=key
                )
    else:
        print("Skipping update due to unexpected status:", response.status_code)
