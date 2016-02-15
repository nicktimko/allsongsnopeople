import sys
import argparse
import pathlib
import shelve

import feedparser
import requests
import parsel
from pydub import AudioSegment as AS

RSS_URL = 'http://www.npr.org/rss/rss.php?id=163479981'
SONGS = pathlib.Path('songs')
SHOWS = pathlib.Path('shows')
SDB = pathlib.Path('asmo')

SONGS.mkdir(exist_ok=True)
SHOWS.mkdir(exist_ok=True)


def xcls(cls):
    return 'contains(concat(" ", @class, " "), " {} ")'.format(cls)


class Show(object):
    def __init__(self, url):
        self.url = url
        self.bad = False
        self.response = requests.get(url)
        self.sel = parsel.Selector(self.response.content.decode('utf-8'))

        self.extract_timestamp()
        if self.bad:
            return
        self.songs = self.count_songs()

    def extract_timestamp(self):
        base_url = self.sel.xpath('//a[@class="download"]/@href').extract_first()
        if base_url is None:
            self.bad = True
            return
        assert 'asc_wholeshow' in base_url
        x = base_url.find('npr/asc/') + len('npr/asc/')
        y = base_url.find('_asc_')
        self.url_timestamp = base_url[x:y]
        self.small_timestamp = self.url_timestamp[self.url_timestamp.rfind('/')+1:]

    def song_url(self, n):
        return ('http://public.npr.org/anon.npr-mp3/npr/asc/{}_asc_{:02d}.mp3'
                .format(self.url_timestamp, n))

    def count_songs(self):
        songs = []
        selectors = self.sel.xpath('//*[{}]//*[{}]'.format(
                xcls('playlistwrap'),
                xcls('playlistitem'),
        ))
        for n, s in enumerate(selectors, start=1):
            def subsel(cls):
                text = (s.xpath('.//*[{}]/text()'.format(xcls(cls)))
                         .extract_first())
                if text is not None:
                    return text.strip()
                return text

            song = {
                '_title': (s
                    .xpath('.//h4/a/text()')
                    .extract_first()
                    .strip()),
                'song': subsel('song'),
                'artist': subsel('artist'),
                'album': subsel('album'),
                'url': self.song_url(n),
            }
            if song['song'] is None:
                song['song'] = song.pop('_title')
            elif song['artist'] is None:
                song['artist'] = song.pop('_title')

            url = song['url']
            song['save_as'] = SONGS / url[url.rfind('/')+1:]

            songs.append(song)
        return songs

    def __iter__(self):
        yield from self.songs

    def download(self, song):
        r = requests.get(song['url'], stream=True)
        with song['save_as'].open('wb') as f:
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)

    def scrape(self):
        for song in self:
            self.download(song)

    def assemble(self):
        stitched = sum(AS.from_file(str(s['save_as'])) for s in self)
        stitched.export(str(SHOWS / (self.small_timestamp + '_asnp.mp3')))


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument('-l', '--limit', type=int, default=5, help="Look back a maximum number of episodes")

    args = parser.parse_args()

    print('Downloading feed...')
    rss = feedparser.parse(RSS_URL)

    print('Loading shelve database')
    with shelve.open(str(SDB)) as db:
        for entry in rss['entries'][:args.limit]:
            link = entry['link']

            if link in db:
                print('Link already indexed, ignoring')
                continue

            print('Downloading show page')
            print(' - {}'.format(link))
            show = Show(link)
            if show.bad:
                db[link] = {'bad': True}
                print('Show has no songs ("bad"), ignoring')
                continue

            print('Downloading {} songs'.format(len(show.songs)))
            show.scrape()
            print('Jamming them together.')
            show.assemble()

            db[link] = show.songs


if __name__ == '__main__':
    sys.exit(main())
