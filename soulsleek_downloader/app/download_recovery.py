"""Resource limits and recovery of results after a Soulseek process crash."""

import csv
import os
from pathlib import Path
import resource

from mutagen import File, MutagenError

HEADER = ['filepath', 'artist', 'album', 'title', 'length', 'tracktype', 'state', 'failurereason']


def configure_file_limit():
    """Raise only the soft limit; never require extra container privileges."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    target = 16384 if hard == resource.RLIM_INFINITY else min(16384, hard)
    if soft != resource.RLIM_INFINITY and soft < target:
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
            soft = target
        except (OSError, ValueError) as error:
            print(f'⚠️ Cannot raise open-file limit: {error}', flush=True)
    print(f'Soulseek open-file limit: {soft} (hard: {hard}); concurrent downloads: 2', flush=True)


def identity(row):
    return tuple((row.get(key) or '').strip() for key in ('artist', 'title', 'album', 'length'))


def rebuild_crashed_index(playlist, index, output_dir):
    """Reconcile the full input with durable results, including unstarted tracks.

    A crash can truncate the native index. Preserve readable completed rows and
    use exact audio tags/duration as additional evidence, never partial files.
    """
    with open(playlist, encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not {'artist', 'title', 'album', 'length'}.issubset(reader.fieldnames or []):
            raise ValueError('Invalid playlist CSV for crash recovery')
        source = list(reader)
    completed = set()
    try:
        with open(index, encoding='utf-8-sig', newline='') as stream:
            for row in csv.DictReader(stream):
                if row.get('tracktype') == '0' and row.get('state') in {'1', '3'}:
                    completed.add(identity(row))
    except (OSError, csv.Error, UnicodeError):
        pass

    audio_identities = []
    for path in Path(output_dir).rglob('*'):
        if path.suffix.lower() not in {'.mp3', '.flac', '.ogg', '.wav', '.aiff', '.m4a'}:
            continue
        try:
            audio = File(path, easy=True)
            if audio is not None and audio.tags and audio.info.length > 0:
                tags = tuple(str((audio.get(key) or [''])[0]).strip() for key in ('artist', 'title', 'album'))
                audio_identities.append((tags, audio.info.length))
        except (OSError, ValueError, MutagenError):
            continue
    rows, seen = [], set()
    for row in source:
        key = identity(row)
        if key in seen:
            continue
        seen.add(key)
        duration = float(row['length'])
        present = key in completed or any(
            tags == key[:3] and abs(length - duration) <= 2
            for tags, length in audio_identities
        )
        rows.append(dict(row, filepath='', tracktype='0', state='1' if present else '2',
                         failurereason='0' if present else '2'))
    temporary = str(index) + '.recovered'
    with open(temporary, 'w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, index)
    missing = sum(row['state'] == '2' for row in rows)
    print(f'Crash recovery: {len(rows) - missing} confirmed tracks; {missing} need recovery.', flush=True)
    return missing
