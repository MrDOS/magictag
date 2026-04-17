#! /usr/bin/env python3

"""
Magically retag FLAG files.
"""

__version__ = '0.52.0'

__author__ = 'Samuel Coleman'
__contact__ = 'samuel@seenet.ca'
__license__ = 'WTFPL'

import argparse
import chardet
from collections import abc, OrderedDict
from datetime import datetime
import dateutil.parser
import functools
import humanize
import mutagen
import os
import os.path
import re
import subprocess
import sys
import tempfile
from titlecase import titlecase
import urllib.request

ARTWORK_EXTENSIONS = ("jpg", "jpeg", "png")
"""Accept files with these extensions as album artwork."""
ARTWORK_EXTENSION_REPLACEMENTS = {"jpeg": "jpg"}
"""When renaming artwork, remap these extensions."""
ARTWORK_FORMAT = "folder.{}"
"""Desired filename format for a single artwork file."""
TOUCH_EXTENSIONS = ("cue", "log", "txt")
"""Files with these extensions should have their mtimes matched to the log."""

FEAT_TERMS = ['feat.', 'ft.']
MAYBE_FEAT_TERMS = ['with']
FEAT_PATTERN = lambda: re.compile(
    r' \(?(?P<term>'
    + '|'.join([term.replace('.', r'\.') for term in FEAT_TERMS])
    + r') (?P<feature>[^)]+)\)?',
    re.IGNORECASE,
)
DO_TITLECASE = False

def fix_curly_apostrophes(term):
    """Replace single curly quotes with apostrophes, as God intented."""
    # If we were very clever, we'd ignore the outermost matched pairs of
    # single quotes and only replace unmatched right single quotes (e.g.,
    # s/‘We’re a long way from home’/‘We're a long way from home’/. However,
    # across my whole music library, the only instance of a left single quote
    # is a typo clearly intended to be a right single quote, and which should
    # be an apostrophe anyway.
    return re.sub('[‘’]', "'", term)

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

def generate_sort(tag, tags, songs):
    base_tag = tag[:-4]
    reference_value = tags[base_tag]
    value = reference_value

    if value[:len('The ')] == 'The ':
        insert_point = len(value)
        featuring = FEAT_PATTERN().search(value)
        if featuring is not None:
            insert_point = featuring.span()[0]
        value = value[len('The '):insert_point] + ', The' + value[insert_point:]

    # “P!nk” → “Pink”, but no change to “Godspeed You! Black Emperor”
    value = re.sub(r'(\w)!(\w)', r'\1i\2', value)
    # “KoЯn” → “Korn”
    value = value.replace('Я', 'r')
    # Ke$ha” → “Kesha”
    value = value.replace('$', 's')

    if value != reference_value:
        return value

def generate_artist(tag, tags, songs):
    artist = tags['ARTIST'].strip()
    title_featuring = FEAT_PATTERN().search(tags['TITLE'])
    artist_featuring = FEAT_PATTERN().search(artist)
    if title_featuring is None or artist_featuring is not None:
        return artist

    return artist + ' ' + title_featuring.group('term').lower() + ' ' + title_featuring.group('feature')

def generate_title(tag, tags, songs):
    title_featuring = FEAT_PATTERN().search(tags[tag])
    if title_featuring is None:
        return tags[tag]

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
        value = re.sub(r'^[\._]*(.*?)[\._]*$', r'\1', value)
    return value

def fetch_itunes_album_art(album_artist, album, filename_format):
    try:
        import itunes
    except ImportError:
        print('Couldn\'t load the "itunes" module! Skipping art retrieval.')
        return

    try:
        albums = itunes.search_album('%s %s' % (album_artist, album))
    except Exception as e:
        print('Failure searching for album art (%s)! Skipping art retrieval.' % e)
        return

    if not len(albums):
        print('No iTunes search results. Continuing without album art.')
        return

    _, low_res = albums[0].get_artwork().popitem()

    # low_res will be something like:
    #
    #    https://is1-ssl.mzstatic.com/image/thumb/Music211/v4/80/f3/c6/
    #    80f3c6e7-f7dd-8554-7be8-6ff1c1ca1456/656465471581_cover.jpg/100x100bb.jpg
    #
    # or:
    #
    #     https://is1-ssl.mzstatic.com/image/thumb/Music211/v4/27/7c/e4/
    #     277ce44b-d805-5a35-d640-f738a3c265e6/24UM1IM41433.rgb.jpg/100x100bb.jpg
    #
    # or even:
    #
    #     https://is1-ssl.mzstatic.com/image/thumb/Music221/v4/f6/f7/c4/
    #     f6f7c443-46cc-c56a-7369-ffd4676b425e/098787168563.png/100x100bb.jpg
    #
    # The second-last element seems to be a source image filename. As you can
    # see, it varies significantly, often including human-readable terms like
    # “cover”, or even the album title. Crucially, it usually has a .jpg
    # extension, but occasionally – increasingly frequently for newer albums –
    # it has a .png extension.
    #
    # The last element of the URL (here “100x100bb.jpg” in both cases) is
    # parametric, controlling the resolution and quality of the output. Try
    # “400x400-92.jpg”, for example, to get a 400x400 px JPEG with compression
    # quality 92. (I don't know what “bb” means, but it yields the same file
    # size as requests for quality 80 or with no quality parameter, although
    # all three responses have slightly differing header bytes.) The
    # compression format can also be controlled by modifying the extension; you
    # can get a JPEG image with .jpg, a PNG with .png, or a WebP with .webp.
    #
    # If you request an impossibly high resolution or quality level, the API
    # will simply give you the biggest thing it has. For example, in the case
    # of the first URL given above, the source imagery appears to be
    # 3000x3000 px, and so you will get the same image response for both
    # “3000x3000-100.jpg” and “4000x4000-100.jpg” – or, for that matter, for
    # “10000x10000-999.jpg”.
    #
    # I am fairly certain that requesting the largest, highest-quality image
    # possible in the same format as the source image avoids re-encoding.

    source, _ = low_res.rsplit("/", maxsplit=1)
    _, source_ext = source.rsplit(".", maxsplit=1)
    high_res = f"{source}/10000x10000-999.{source_ext}"
    filename = filename_format.format(source_ext)

    try:
        urllib.request.urlretrieve(high_res, filename)
    except Exception as e:
        print('Found iTunes match, but failed to retrieve the album art (%s)! Continuing without it.' % e)
        return

    return filename

def optimize_image(path_ext):
    path, ext = path_ext

    print(f"Optimizing {path}...")

    fd, temp_path = tempfile.mkstemp(suffix=f".{ext}", dir=os.path.dirname(path))
    os.close(fd)

    if ext in ("jpg", "jpeg"):
        optimize_jpg(path, temp_path)
    elif ext == "png":
        optimize_png(path, temp_path)
    else:
        print(f"{path}: unrecognized extension '{ext}'; not optimizing.")
        os.unlink(temp_path)
        return

    old_size = os.stat(path).st_size
    new_size = os.stat(temp_path).st_size
    delta_size = old_size - new_size
    delta_percent = (1 - (new_size / old_size)) * 100

    os.rename(temp_path, path)

    print(
        f"{path}: saved {humanize.naturalsize(old_size)} "
        f"- {humanize.naturalsize(new_size)} "
        f"= {humanize.naturalsize(delta_size)} ({delta_percent:.1f}%)."
    )

@functools.cache
def _check_mozjpeg():
    completion = subprocess.run(["jpegtran", "-version"], capture_output=True)

    if not b"mozjpeg" in completion.stderr:
        print(
            "warning: not using MozJPEG jpegtran, so optimized JPEGs will not "
            "be as small as possible"
        )

def optimize_jpg(input_path, output_path):
    _check_mozjpeg()

    subprocess.run(
        [
            "jpegtran",
            "-optimize",
            "-progressive",
            "-copy",
            "icc",
            "-outfile",
            output_path,
            input_path,
        ]
    )

def optimize_png(input_path, output_path):
    subprocess.run(["pngout", "-y", input_path, output_path])

ALLOWED_TAGS = OrderedDict.fromkeys([
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
    'ALBUM': [str.strip, fix_curly_apostrophes, tag_titlecase],
    'DATE': lambda year: int(year[0:4]) if len(year) > 0 else None,
    'DISCNUMBER': lambda number: int(number.split('/')[0]),
    'DISCTOTAL': int,
    'GENRE': tag_titlecase,
    'ARTIST': artist_titlecase,
    'TITLE': [str.strip, fix_curly_apostrophes, artist_titlecase],
    'COMPOSER': tag_titlecase,
    'PERFORMER': tag_titlecase,
    'TRACKNUMBER': lambda number: int(number.split('/')[0]),
    'TRACKTOTAL': int
}

GENERATE_TAGS = OrderedDict([
    ('ALBUMARTIST', lambda tag, tags, songs: tags['ARTIST'] if tags[tag] is None else tags[tag]),
    ('ALBUMARTISTSORT', generate_sort),
    ('ARTIST', generate_artist),
    ('ALBUMSORT', generate_sort),
    ('ARTISTSORT', generate_sort),
    ('TITLE', generate_title),
    ('DISCNUMBER', lambda tag, tags, songs: 1 if tags[tag] is None else tags[tag]),
    ('DISCTOTAL', lambda tag, tags, songs: 1 if tags[tag] is None else tags[tag]),
    ('TRACKTOTAL', lambda tag, tags, songs: len(songs) if tags[tag] is None else tags[tag])
])

def main():
    global FEAT_TERMS, MAYBE_FEAT_TERMS, DO_TITLECASE

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--with-as-feature-term",
        action="store_true",
        help="treat “with” as a term for featured artists",
    )
    parser.add_argument(
        "--fix-title-case", action="store_true", help="fix tag capitalization"
    )
    parser.add_argument(
        "--add-replay-gain",
        action="store_true",
        help="calculate track/album ReplayGain",
    )
    parser.add_argument(
        "--optimize-existing-artwork",
        action="store_true",
        help="optimize existing artwork files (slow; newly-fetched artwork is always optimized)",
    )
    parser.add_argument(
        "paths", metavar="path", nargs="+",
        help="directory or tracks to magic"
    )

    args = parser.parse_args()
    paths = args.paths
    directory = None
    whole_directory = False

    if len(paths) == 1 and os.path.isdir(paths[0]):
        directory = os.path.relpath(paths[0], '.')
        whole_directory = True
        paths = [os.path.join(directory, f) for f in os.listdir(directory)]
        print('"%s" is a directory. Processing its entire contents.' % directory)

    paths_exts = [(path, path.split(".")[-1].lower()) for path in paths]

    access_time = datetime.now().timestamp()
    rip_time = None

    log_paths = [path[0] for path in paths_exts if path[1] == "log"]
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

    for touch_path in [path[0] for path in paths_exts if path[1] in TOUCH_EXTENSIONS]:
        if rip_time is not None:
            os.utime(touch_path, times=(access_time, rip_time))
        os.chmod(touch_path, 0o644)

    path_directories = list(set([os.path.dirname(path) for path in paths]))
    if directory is None and len(path_directories) == 1:
        directory = path_directories[0] if path_directories[0] != '' else '.'
        path_filenames = set([os.path.basename(path) for path in paths])
        directory_filenames = set(os.listdir(directory))

        if path_filenames == directory_filenames:
            whole_directory = True

    song_paths = [path[0] for path in paths_exts if path[1] == "flac"]

    if args.with_as_feature_term:
        FEAT_TERMS += MAYBE_FEAT_TERMS

    if args.fix_title_case:
        DO_TITLECASE = True

    if args.add_replay_gain:
        print('Calculating ReplayGain...')
        subprocess.run(['metaflac', '--add-replay-gain'] + song_paths)

    songs = [mutagen.File(f) for f in song_paths]
    album_artist = None
    album = None
    album_date = None
    print('Tagging...')
    for song in songs:
        tags = ALLOWED_TAGS.copy()
        for tag, value in song.tags:
            tag = tag.upper()

            if tag in RENAME_TAGS:
                tag = RENAME_TAGS[tag]

            if tag not in tags:
                continue

            if tag in FILTER_TAGS:
                filters = FILTER_TAGS[tag]
                if not isinstance(filters, abc.Sequence):
                    filters = [filters]

                for tag_filter in filters:
                    try:
                        value = tag_filter(value)
                    except ValueError as e:
                        print(f'Error filtering value for tag {tag} of song {song.filename}: {e}')

            tags[tag] = value

        for tag in GENERATE_TAGS:
            try:
                tags[tag] = GENERATE_TAGS[tag](tag, tags, songs)
            except ValueError as e:
                print(f'Error generating value for tag {tag} of song {song.filename}: {e}')

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

    cue_paths = [path[0] for path in paths_exts if path[1] == "cue"]
    if len(cue_paths) > 1:
        print('Multiple cue files; not renaming.')
    elif len(cue_paths) == 1:
        cue_path = cue_paths[0]
        new_cue_path = os.path.join(os.path.dirname(cue_path), '%s.cue' % (filename_filter(album)))
        os.rename(cue_path, new_cue_path)

    if whole_directory:
        artwork_paths = [path for path in paths_exts if path[1] in ARTWORK_EXTENSIONS]
        optimize_paths = []

        if len(artwork_paths) > 1:
            print("Multiple image files; not renaming.")

        elif len(artwork_paths) == 1:
            artwork_path, artwork_ext = artwork_paths[0]

            new_artwork_ext = ARTWORK_EXTENSION_REPLACEMENTS.get(artwork_ext, artwork_ext)
            new_artwork_path = ARTWORK_FORMAT.format(new_artwork_ext)
            new_artwork_path = os.path.join(os.path.dirname(artwork_path), new_artwork_path)

            os.rename(artwork_path, new_artwork_path)
            artwork_paths = [(new_artwork_path, new_artwork_ext)]

        else:
            print("Fetching artwork...")
            artwork_path = os.path.join(directory, ARTWORK_FORMAT)
            artwork_path = fetch_itunes_album_art(album_artist, album, artwork_path)

            if artwork_path is not None:
                artwork_paths = [(artwork_path, artwork_path.rsplit(".", maxsplit=1)[-1])]
                optimize_paths = artwork_paths

        if args.optimize_existing_artwork:
            optimize_paths = artwork_paths

        for path in optimize_paths:
            optimize_image(path)

        for path in artwork_paths:
            if rip_time is not None:
                os.utime(path[0], times=(access_time, rip_time))
            os.chmod(path[0], 0o644)

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
