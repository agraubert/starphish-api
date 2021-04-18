import requests
import time
from bs4 import BeautifulSoup
from .. import utils
import sqlalchemy as sqla
from datetime import datetime
from hashlib import sha256
import random
from tqdm import tqdm
import argparse

MAX_IDX = 148112

if __name__ == '__main__':
    parser = argparse.ArgumentParser('starphish-aa419')
    parser.add_argument('url')

    args = parser.parse_args()

    count = 0

    for i in tqdm(range(1, MAX_IDX, 20)):
        response = requests.get('https://db.aa419.org/fakebankslist.php?start={}'.format(i))
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            if soup is not None:
                table = soup.find('table', {'class': 'ewTable'})
                if table is not None:
                    links = [
                        {
                            'url': link.attrs['href'],
                            'url_hash': sha256(link.attrs['href'].encode()).hexdigest(),
                            'added': datetime.now(),
                            'source': 'aa419'
                        }
                        for link in table.find_all('a', {'rel': 'nofollow'})
                        if link is not None
                    ]
                    if len(links):
                        with utils.Database.init_with_url(args.url) as db:
                            table = db['phishing']
                            db.multi_insert(
                                'phishing',
                                links
                            )
                        count += len(links)
        time.sleep(random.randint(1, 10))
