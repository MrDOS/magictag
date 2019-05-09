#! /usr/bin/env python3

"""
Magically retag FLAG files.
"""

__version__ = '0.41.0'

__author__ = 'Samuel Coleman'
__contact__ = 'samuel@seenet.ca'
__license__ = 'WTFPL'

import chardet
from datetime import datetime
import dateutil.parser
from collections import OrderedDict
import mutagen
import os
import os.path
import re
import subprocess
import sys
from titlecase import titlecase
import urllib.request

FEAT_TERMS = ['feat.']
MAYBE_FEAT_TERMS = ['with']
FEAT_PATTERN = lambda: re.compile(r' \(?(?P<term>' + '|'.join([term.replace('.', '\.') for term in FEAT_TERMS]) + ') (?P<feature>[^)]+)\)?', re.IGNORECASE)
DO_TITLECASE = False

def tag_titlecase(title, **kwargs):
    if not DO_TITLECASE:
        return title

    if title.lower() == title or title.upper() == title:
        return title

    callback = kwargs['callback'] if 'callback' in kwargs else None
    return titlecase(title, callback=callback)

def artist_titlecase(title):
    title = re.sub(r'\(featuring ', '(feat. ', title, flags=re.IGNORECASE)
    def titlecase_callback(word,  **kwargs):
        if word.lower() in ['from', 'la', 'with'] + FEAT_TERMS and not titlecase_callback.first_word:
            return word.lower()
        titlecase_callback.first_word = False
    titlecase_callback.first_word = True

    return ' / '.join([tag_titlecase(part, callback=titlecase_callback) for part in title.split(' / ')])

def generate_sort(tag, tags):
    base_tag = tag[:-4]
    reference_value = tags[base_tag]
    value = reference_value

    if value[:len('The ')] == 'The ':
        insert_point = len(value)
        featuring = FEAT_PATTERN().search(value)
        if featuring is not None:
            insert_point = featuring.span()[0]
        value = value[len('The '):insert_point] + ', The' + value[insert_point:]

    value = re.sub(r'(\w)!(\w)', r'\1i\2', value)
    # “KoЯn” → “Korn”
    value = value.replace('Я', 'r')
    # Ke$ha” → “Kesha”
    value = value.replace('$', 's')

    if value != reference_value:
        return value

def generate_artist(tag, tags):
    title_featuring = FEAT_PATTERN().search(tags['TITLE'])
    artist_featuring = FEAT_PATTERN().search(tags['ARTIST'])
    if title_featuring is None or artist_featuring is not None:
        return tags['ARTIST']

    return tags['ARTIST'] + ' ' + title_featuring.group('term').lower() + ' ' + title_featuring.group('feature')

def generate_title(tag, tags):
    title_featuring = FEAT_PATTERN().search(tags[tag])
    if title_featuring is None:
        return tags[tag]
    print(title_featuring)

    return tags[tag][:title_featuring.span()[0]] + tags[tag][title_featuring.span()[1]:]

def generate_filename(song):
    path = os.path.dirname(song.filename)
    track_number = int(song['TRACKNUMBER'][0])
    album_artist = song['ALBUMARTIST'][0]
    artist = filename_filter(song['ARTIST'][0])
    title = filename_filter(song['TITLE'][0])
    if album_artist == 'Various Artists':
        return os.path.join(path, '%02d - %s - %s.flac' % (track_number, artist, title))
    else:
        return os.path.join(path, '%02d - %s.flac' % (track_number, title))

def filename_filter(value):
    value = re.sub(r'[<>:/\\\|]', '-', value)
    value = value.replace('"', "'")
    value = re.sub(r'[?*]', '_', value)
    # If we have trailing special characters at the beginning or end, just drop
    # them (unless the entire name consists of special characters/symbols).
    if re.search(r'[0-9A-Za-z]', value):
        value = re.sub('^[\._]*(.*?)[\._]*$', r'\1', value)
    return value

def fetch_itunes_album_art(album_artist, album, filename):
    try:
        import itunes
    except ImportError:
        print('Couldn\'t load the "itunes" module! Skipping art retrieval.')
        return

    albums = itunes.search_album('%s %s' % (album_artist, album))
    if not len(albums):
        return
    _, low_res = albums[0].get_artwork().popitem()
    high_res = low_res[:low_res.rindex('/') + 1] + '100000x100000-999.jpg'
    urllib.request.urlretrieve(high_res, filename)
    return filename

DEFALT_TAGS = OrderedDict.fromkeys([
    'ALBUMARTIST',
    'ALBUMARTISTSORT',
    'ALBUM',
    'ALBUMSORT',
    'DATE',
    'DISCNUMBER',
    'DISCTOTAL',
    'GENRE',
    'ARTIST',
    'ARTISTSORT',
    'TITLE',
    'COMPOSER',
    'DESCRIPTION',
    'PERFORMER',
    'TRACKNUMBER',
    'TRACKTOTAL',
    'REPLAYGAIN_REFERENCE_LOUDNESS',
    'REPLAYGAIN_TRACK_GAIN',
    'REPLAYGAIN_TRACK_PEAK',
    'REPLAYGAIN_ALBUM_GAIN',
    'REPLAYGAIN_ALBUM_PEAK'
])

RENAME_TAGS = {
    'TOTALDISCS': 'DISCTOTAL',
    'TOTALTRACKS': 'TRACKTOTAL'
}

FILTER_TAGS = {
    'ALBUMARTIST': artist_titlecase,
    'ALBUM': tag_titlecase,
    'DATE': lambda year: int(year[0:4]) if len(year) > 0 else None,
    'DISCNUMBER': lambda number: int(number.split('/')[0]),
    'DISCTOTAL': int,
    'GENRE': tag_titlecase,
    'TITLE': artist_titlecase,
    'COMPOSER': tag_titlecase,
    'PERFORMER': tag_titlecase,
    'TRACKNUMBER': lambda number: int(number.split('/')[0]),
    'TRACKTOTAL': int
}

GENERATE_TAGS = OrderedDict([
    ('ALBUMARTIST', lambda tag, tags: tags['ARTIST'] if tags[tag] is None else tags[tag]),
    ('ALBUMARTISTSORT', generate_sort),
    ('ARTIST', generate_artist),
    ('ALBUMSORT', generate_sort),
    ('ARTISTSORT', generate_sort),
    ('TITLE', generate_title),
    ('DISCNUMBER', lambda tag, tags: 1 if tags[tag] is None else tags[tag]),
    ('DISCTOTAL', lambda tag, tags: 1 if tags[tag] is None else tags[tag]),
    ('TRACKTOTAL', lambda tag, tags: len(songs) if tags[tag] is None else tags[tag])
])

def main():
    global FEAT_TERMS, MAYBE_FEAT_TERMS, DO_TITLECASE

    flags = [flag[2:] for flag in sys.argv[1:] if flag.startswith('--')]
    paths = [path for path in sys.argv[1:] if not path.startswith('--')]
    directory = None
    whole_directory = False

    if len(paths) == 1 and os.path.isdir(paths[0]):
        directory = os.path.relpath(paths[0], '.')
        whole_directory = True
        paths = [os.path.join(directory, f) for f in os.listdir(directory)]
        print('"%s" is a directory. Processing its entire contents.' % directory)

    access_time = datetime.now().timestamp()
    rip_time = None

    log_paths = [f for f in paths if f.lower().endswith('.log')]
    for log_path in log_paths:
        with open(log_path, 'rb') as log_file:
            log_raw = log_file.read()
            log = None

            charsets = (chardet.detect(log_raw)['encoding'], 'UTF-8', 'ASCII')
            for charset in charsets:
                try:
                    log = log_raw.decode(charset)
                    print('Decoded the log as %s.' % charset)
                    break
                except UnicodeDecodeError:
                    print("Tried to decode the log as %s, but failed!" % charset)

            if log is None:
                print('Failed to decode the log. Skipping log parsing.')
            else:
                rip_time_match = re.search('extraction logfile from ((.+)( for .*)|(.+))', log)
                if rip_time_match is not None:
                    opt1, opt2, _, _ = rip_time_match.groups()
                    time_string = opt2 if opt2 is not None else opt1
                    rip_time = dateutil.parser.parse(time_string).timestamp()

    info_paths = [f for f in paths if os.path.basename(f.lower()) == 'info.txt']
    for info_path in info_paths:
        with open(info_path, 'r') as info_file:
            info = info_file.read()
            info_time_match = re.search('NFO generated on.....: (?P<time>.+)', info)
            if info_time_match is not None:
                time_string = info_time_match.groups('time')[0]
                rip_time = dateutil.parser.parse(time_string).timestamp()

    for extra_path in [f for f in paths if f.lower().split('.')[-1] in ('cue', 'jpg', 'png', 'log', 'txt')]:
        if rip_time is not None:
            os.utime(extra_path, times=(access_time, rip_time))
        os.chmod(extra_path, 0o644)

    path_directories = list(set([os.path.dirname(path) for path in paths]))
    if directory is None and len(path_directories) == 1:
        directory = path_directories[0] if path_directories[0] != '' else '.'
        path_filenames = set([os.path.basename(path) for path in paths])
        directory_filenames = set(os.listdir(directory))

        if path_filenames == directory_filenames:
            whole_directory = True

    song_paths = [f for f in paths if f.lower().endswith('.flac')]

    if 'with-as-feature-term' in flags:
        FEAT_TERMS += MAYBE_FEAT_TERMS

    if 'fix-title-case' in flags:
        DO_TITLECASE = True

    if 'add-replay-gain' in flags:
        print('Calculating ReplayGain...')
        subprocess.run(['metaflac', '--add-replay-gain'] + song_paths)

    songs = [mutagen.File(f) for f in song_paths]
    album_artist = None
    album = None
    album_date = None
    print('Tagging...')
    for song in songs:
        tags = DEFALT_TAGS.copy()
        for tag, value in song.tags:
            tag = tag.upper()

            if tag in RENAME_TAGS:
                tag = RENAME_TAGS[tag]

            if tag not in tags:
                continue

            if tag in FILTER_TAGS:
                value = FILTER_TAGS[tag](value)

            tags[tag] = value

        for tag in GENERATE_TAGS:
            tags[tag] = GENERATE_TAGS[tag](tag, tags)

        album_artist = tags['ALBUMARTIST']
        album = tags['ALBUM']
        album_date = tags['DATE']

        song.delete()
        song.clear_pictures()
        for tag in tags:
            if tags[tag] is not None and tags[tag] != '':
                song[tag] = [str(tags[tag])]
        song.save(padding=lambda _: 8192)

        if rip_time is not None:
            os.utime(song.filename, times=(access_time, rip_time))
        os.chmod(song.filename, 0o644)

        os.rename(song.filename, generate_filename(song))

    if len(log_paths) > 1:
        print('Multiple log files; not renaming.')
    elif len(log_paths) == 1:
        log_path = log_paths[0]
        new_log_path = os.path.join(os.path.dirname(log_path), '%s - %s.log' % (filename_filter(album_artist), filename_filter(album)))
        os.rename(log_path, new_log_path)

    cue_paths = [f for f in paths if f.lower().endswith('.cue')]
    if len(cue_paths) > 1:
        print('Multiple cue files; not renaming.')
    elif len(cue_paths) == 1:
        cue_path = cue_paths[0]
        new_cue_path = os.path.join(os.path.dirname(cue_path), '%s.cue' % (filename_filter(album)))
        os.rename(cue_path, new_cue_path)

    if whole_directory:
        image_paths = [f for f in paths if f.lower().split('.')[-1] in ('jpg', 'jpeg')]
        if len(image_paths) > 1:
            print('Multiple image files; not renaming.')
        elif len(image_paths) == 1:
            image_path = image_paths[0]
            new_image_path = os.path.join(os.path.dirname(image_path), 'folder.jpg')
            os.rename(image_path, new_image_path)
        else:
            print('Fetching artwork...')
            artwork_path = os.path.join(directory, 'folder.jpg')
            artwork_path = fetch_itunes_album_art(album_artist, album, artwork_path)
            if artwork_path is not None:
                if rip_time is not None:
                    os.utime(artwork_path, times=(access_time, rip_time))
                os.chmod(artwork_path, 0o644)

        if rip_time is not None:
            os.utime(directory, times=(access_time, rip_time))
        os.chmod(directory, 0o755)

        if directory == '.':
            print('Cannot rename the directory while in it!')
        else:
            parent = os.path.dirname(directory)
            os.rename(directory, os.path.join(parent, '%s (%s)' % (filename_filter(album), album_date)))

    return 0

if __name__ == '__main__':
    sys.exit(main())
