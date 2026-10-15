import argparse
import csv
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
import tempfile
import signal
import urllib.request
from youtube_fallback import download_missing_tracks, missing_tracks
from download_recovery import configure_file_limit, rebuild_crashed_index
from library import (
    AUDIO_EXTENSIONS, OutputNames, SyncState, adopt_existing, load_metadata, track_key,
    track_label, write_csv, write_tags,
)
from spotify_playlist import playlist_id, prepare_spotify_playlist

DEFAULT_CONCURRENT_DOWNLOADS = 2
DEFAULT_TARGET_LUFS = -14


def write_sldl_config(directory, user, password):
    """Keep credentials out of the process list; sldl strips the surrounding quotes."""
    path = os.path.join(directory, "sldl.conf")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(f'user = "{user}"\npass = "{password}"\n')
    return path


def download_music(playlist_url, output_dir, log_file, user, password, pref_format, index_file=None,
                   concurrent_downloads=DEFAULT_CONCURRENT_DOWNLOADS):
    """
    Downloads music from Soulseek using slsk-batchdl and logs the output.
    Returns tuple of (success, failed_tracks_list)
    """
    # Verify sldl binary exists
    if not os.path.exists("/usr/local/bin/sldl"):
        print("❌ sldl binary not found", flush=True)
        return False, []

    print(f"Downloading music from {playlist_url} to {output_dir}", flush=True)
    print(f"Download log: {log_file}", flush=True)
    configure_file_limit(concurrent_downloads)

    failed_tracks = []
    resource_exhausted = False

    try:
        print(f"🎵 Starting download from Spotify playlist...", flush=True)

        # Run process and capture essential output only
        with tempfile.TemporaryDirectory(prefix="sldl-config-") as config_dir, open(log_file, 'w') as f:
            command = [
                "/usr/local/bin/sldl", playlist_url,
                "-c", write_sldl_config(config_dir, user, password),
                "-p", output_dir,
                "--pref-format", pref_format,
                "--concurrent-downloads", str(concurrent_downloads),
                "--no-progress",
            ]
            if index_file:
                command.extend(["--index-path", index_file])
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     universal_newlines=True, encoding="utf-8", errors="replace", bufsize=0)

            for line in process.stdout:
                line = line.rstrip()
                if password:
                    line = line.replace(password, "[REDACTED]")
                f.write(line + '\n')
                f.flush()

                if "No file descriptors available" in line or "Too many open files" in line:
                    resource_exhausted = True
                for prefix in ("Not found: ", "All downloads failed: ", "Out of download retries: "):
                    if line.startswith(prefix):
                        track_name = line[len(prefix):]
                        if track_name not in failed_tracks:
                            failed_tracks.append(track_name)

                # --no-progress keeps output readable; never hide startup/API errors.
                if line:
                    print(line, flush=True)

            process.stdout.close()
            process.wait()

        if index_file:
            if process.returncode < 0 or resource_exhausted:
                try:
                    rebuild_crashed_index(playlist_url, index_file, output_dir)
                except (OSError, ValueError) as error:
                    print(f"⚠️ Cannot reconcile crashed download: {error}", flush=True)
            try:
                failed_tracks = [
                    f"{track['artist']} - {track['title']} ({track['duration']:g}s)"
                    for track in missing_tracks(index_file)
                ]
            except (OSError, ValueError):
                pass  # Keep textual diagnostics when no usable index exists.

        # Show download summary
        if failed_tracks:
            print(f"\n📋 DOWNLOAD SUMMARY:", flush=True)
            print(f"❌ Failed to download {len(failed_tracks)} tracks:", flush=True)
            for failed_track in failed_tracks:
                print(f"   • {failed_track}", flush=True)
            print(flush=True)

        if process.returncode == 0:
            print(f"✅ Download completed successfully!", flush=True)
            return True, failed_tracks
        else:
            print(f"❌ Download failed with exit code: {process.returncode}", flush=True)
            if process.returncode < 0:
                try:
                    reason = signal.Signals(-process.returncode).name
                except ValueError:
                    reason = str(-process.returncode)
                print(f"Downloader terminated by signal: {reason}", flush=True)
            return False, failed_tracks

    except Exception as e:
        print(f"❌ Download error: {e}", flush=True)
        with open(log_file, 'a') as f:
            f.write(f"\n\nError: {e}")
        return False, failed_tracks


def index_downloads(index_file, metadata):
    """Map each audio file the downloader confirmed to its playlist track."""
    downloads = {}
    try:
        with open(index_file, encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                if row.get("tracktype") != "0" or row.get("state") not in {"1", "3"} or not row.get("filepath"):
                    continue
                path = os.path.join(os.path.dirname(os.path.abspath(index_file)), row["filepath"])
                downloads[os.path.realpath(path)] = metadata.get(track_key(row)) or {
                    key: (row.get(key) or "").strip() for key in ("artist", "title", "album", "length")
                }
    except (OSError, csv.Error, UnicodeError):
        pass
    return downloads


def normalize_single_file(file_path, normalize_script_path, converted_dir, output_name=None,
                          track=None, target_lufs=DEFAULT_TARGET_LUFS):
    """
    Normalize a single audio file into converted_dir, then apply playlist tags.
    """
    temporary = None
    try:
        if output_name is None:
            output_name = os.path.splitext(os.path.basename(file_path))[0] + ".mp3"
        output_file = os.path.join(converted_dir, output_name)
        # Never leave a half-written file under the final name.
        temporary = os.path.join(converted_dir, f".{output_name}.part")

        print(f"🎧 Processing: {os.path.basename(file_path)}", flush=True)

        command = ["bash", normalize_script_path, file_path, temporary, str(target_lufs)]

        # Run normalization with minimal output
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 universal_newlines=True, encoding="utf-8", errors="replace", bufsize=0)

        # Capture loudness values but don't show FFmpeg details
        loudness_info = {}
        errors = []
        for line in process.stdout:
            line = line.rstrip()
            if "Measured I:" in line:
                loudness_info['input'] = line.split(':')[1].strip()
            elif "Target Offset:" in line:
                loudness_info['offset'] = line.split(':')[1].strip()
            elif "Normalization complete" in line:
                if loudness_info:
                    print(f"   📊 Input: {loudness_info.get('input', 'N/A')} LUFS → Target: {target_lufs} LUFS", flush=True)
            elif line:
                errors.append(line)

        process.stdout.close()
        process.wait()

        if process.returncode != 0:
            return {"status": "failed", "file": file_path,
                    "error": f"Exit code: {process.returncode}", "details": errors[-5:]}
        if track:
            write_tags(temporary, track)
        os.replace(temporary, output_file)
        print(f"   ✅ Successfully normalized: {output_name}", flush=True)
        return {"status": "success", "file": file_path, "output": output_name}

    except Exception as e:
        return {"status": "failed", "file": file_path, "error": str(e)}
    finally:
        if temporary and os.path.exists(temporary):
            os.remove(temporary)


def remove_empty_directories(directory):
    for root, _, _ in sorted(os.walk(directory), key=lambda entry: len(entry[0]), reverse=True):
        for name in os.listdir(root):
            if name.endswith(".incomplete"):
                os.remove(os.path.join(root, name))  # Interrupted transfers are never resumed.
        try:
            os.rmdir(root)
        except OSError:
            pass  # Not empty: keeps failed or unsupported files for inspection/retry.


def process_music(directory, output_dir=None, tracks=None, state=None, target_lufs=DEFAULT_TARGET_LUFS):
    """
    Normalize every audio file in directory into output_dir (default: its parent).

    tracks maps a downloaded file's real path to its playlist metadata; such files
    get playlist tags and are recorded in the sync state. A source file is removed
    only after its own conversion succeeded. Returns a summary dict.
    """
    print(f"Starting to process and normalize music in: {directory}", flush=True)
    summary = {"converted": [], "failed": []}
    tracks = tracks or {}

    script_dir = os.path.dirname(os.path.abspath(__file__))
    normalize_script_path = os.path.join(script_dir, "normalize.sh")

    if not os.access(normalize_script_path, os.X_OK):
        print(f"[ERROR] Normalize script not found or not executable at: {normalize_script_path}", flush=True)
        return summary

    audio_files = []
    for root, _, files in os.walk(directory):
        for file in sorted(files):
            if os.path.splitext(file)[1].lower() in AUDIO_EXTENSIONS:
                audio_files.append(os.path.join(root, file))

    if not audio_files:
        print("No audio files found to process.", flush=True)
        remove_empty_directories(directory)
        return summary

    converted_dir = output_dir or os.path.abspath(os.path.join(directory, os.pardir))
    os.makedirs(converted_dir, exist_ok=True)
    state = state or SyncState(None, converted_dir)
    names = OutputNames(converted_dir, state)

    # One ffmpeg per CPU pair; respect cgroup/affinity limits of the container.
    max_workers = max(1, len(os.sched_getaffinity(0)) // 2)
    print(f"Found {len(audio_files)} audio files. Using {max_workers} threads for processing.", flush=True)
    print(f"Converted files will be saved to: {converted_dir}", flush=True)

    # Names are reserved up front so parallel conversions never share an output file.
    jobs = []
    for file_path in audio_files:
        track = tracks.get(os.path.realpath(file_path))
        base = track_label(track) if track else os.path.splitext(os.path.basename(file_path))[0]
        jobs.append((file_path, names.reserve(base, track), track))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            (executor.submit(normalize_single_file, file_path, normalize_script_path, converted_dir,
                             name, track, target_lufs), track)
            for file_path, name, track in jobs
        ]
        for future, track in futures:
            result = future.result()
            if result["status"] != "success":
                summary["failed"].append(result)
                continue
            summary["converted"].append(result["output"])
            if track:
                state.mark(track, result["output"], track.get("source", "soulseek"))
            try:
                os.remove(result["file"])
            except OSError as error:
                print(f"⚠️ Could not remove converted download: {error}", flush=True)
    state.save()

    print("\n--- PROCESSING REPORT ---", flush=True)
    print(f"Successfully converted {len(summary['converted'])} files.", flush=True)

    if summary["failed"]:
        print(f"Failed to convert {len(summary['failed'])} files (kept for retry in {directory}):", flush=True)
        for failed in summary["failed"]:
            print(f"  - File: {os.path.basename(failed['file'])} — {failed['error']}", flush=True)
            for detail in failed.get("details", []):
                print(f"      {detail}", flush=True)

    remove_empty_directories(directory)
    print("--------------------------\n", flush=True)
    return summary


def notify_home_assistant(title, message, event_data):
    """Persistent notification plus an event for automations (needs homeassistant_api)."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return
    for path, payload in (
        ("services/persistent_notification/create",
         {"title": title, "message": message, "notification_id": "soulsleek_downloader"}),
        ("events/soulsleek_downloader_finished", event_data),
    ):
        request = urllib.request.Request(
            f"http://supervisor/core/api/{path}", data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(request, timeout=10).close()
        except OSError as error:
            print(f"⚠️ Home Assistant notification failed: {error}", flush=True)


def sync_playlist(args, password):
    """Download, recover, convert and tag one playlist. Returns the exit code."""
    download_dir = os.path.join(args.output_dir, "downloads")
    os.makedirs(download_dir, exist_ok=True)
    log_file = os.path.join(args.output_dir, "download_log.txt")
    download_success, failed_tracks, pending = True, [], []
    downloads = {}

    # A fresh structured index prevents retrying failures from another playlist/run;
    # the persistent sync state (not the index) decides what is already in the library.
    with tempfile.TemporaryDirectory(prefix="soulsleek-index-") as index_dir:
        index_file = os.path.join(index_dir, "tracks.csv")
        try:
            print("Loading public Spotify playlist...", flush=True)
            playlist_input = prepare_spotify_playlist(args.playlist_url, index_dir)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            print(f"❌ Playlist import failed: {error}", flush=True)
            print("Workflow failed before track search. See the Home Assistant add-on log above.", flush=True)
            return 1

        metadata = load_metadata(os.path.splitext(playlist_input)[0] + ".json")
        state_file = os.path.join(args.state_dir, f"{playlist_id(args.playlist_url)}.json") if args.state_dir else None
        state = SyncState(state_file, args.output_dir)
        if metadata:
            adopted = adopt_existing(state, metadata.values(), args.output_dir)
            if adopted:
                print(f"📚 Found {adopted} tracks from earlier runs in {args.output_dir}", flush=True)
                state.save()
            pending = [track for track in metadata.values() if not state.is_synced(track)]
            print(f"📚 Library: {len(metadata) - len(pending)} tracks already synced; {len(pending)} to download.",
                  flush=True)
            playlist_input = os.path.join(index_dir, "pending.csv")
            write_csv(playlist_input, pending)

        if pending or not metadata:
            download_success, failed_tracks = download_music(
                playlist_input, download_dir, log_file, args.user, password, args.pref_format,
                index_file=index_file, concurrent_downloads=args.concurrent_downloads,
            )
            if not download_success and not os.path.isfile(index_file):
                print("❌ Downloader stopped before producing track results; YouTube fallback cannot run.", flush=True)
                print(f"See the error above or {log_file}.", flush=True)
                return 1
            downloads.update(index_downloads(index_file, metadata))
            if args.youtube_fallback:
                recovered = []
                download_missing_tracks(index_file, download_dir, log_file, recovered)
                for track, path in recovered:
                    downloads[os.path.realpath(path)] = dict(metadata.get(track_key(track)) or track,
                                                             source="youtube")

    summary = {"converted": [], "failed": []}
    # Process new downloads, and leftovers kept by an earlier failed conversion.
    if ((pending or not metadata) and download_success) or os.listdir(download_dir):
        summary = process_music(download_dir, args.output_dir, downloads, state, args.target_lufs)

    still_missing = [track_label(track) for track in pending if not state.is_synced(track)]
    if still_missing:
        print(f"⚠️ Not in the library yet ({len(still_missing)}): " + "; ".join(still_missing), flush=True)
    ok = download_success and not summary["failed"]
    if args.notify:
        lines = [f"Added {len(summary['converted'])} tracks."]
        if still_missing:
            lines.append(f"Missing ({len(still_missing)}): " + ", ".join(still_missing[:20])
                         + (" …" if len(still_missing) > 20 else ""))
        if summary["failed"]:
            lines.append(f"Conversion failed for {len(summary['failed'])} files; see the add-on log.")
        if not download_success:
            lines.append("The Soulseek downloader stopped with an error; see the add-on log.")
        notify_home_assistant("Soulsleek Downloader", "\n\n".join(lines), {
            "playlist_url": args.playlist_url, "added": len(summary["converted"]),
            "missing": still_missing, "conversion_failures": len(summary["failed"]), "success": ok,
        })
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser(description="Soulsleek Downloader and Processor")

    # Group for download functionality
    download_group = parser.add_argument_group('Download and Process')
    download_group.add_argument("--playlist-url", help="Spotify playlist URL")
    download_group.add_argument("--output-dir", help="Output directory for music")
    download_group.add_argument("--user", help="Soulseek username")
    download_group.add_argument("--pass", help="Soulseek password (default: $SOULSEEK_PASS)")
    download_group.add_argument("--pref-format", help="Preferred file format for download")
    download_group.add_argument(
        "--youtube-fallback", action=argparse.BooleanOptionalAction, default=True,
        help="Recover missing Soulseek tracks from YouTube (default: enabled)",
    )
    download_group.add_argument("--state-dir", help="Persistent directory for incremental sync state")
    download_group.add_argument("--concurrent-downloads", type=int, default=DEFAULT_CONCURRENT_DOWNLOADS,
                                choices=range(1, 5), metavar="1-4", help="Parallel Soulseek downloads")
    download_group.add_argument("--notify", action=argparse.BooleanOptionalAction, default=False,
                                help="Send a Home Assistant notification and event when finished")

    # Group for local processing functionality
    process_group = parser.add_argument_group('Process Local Folder')
    process_group.add_argument("--process-dir", help="Path to a local directory to process")
    parser.add_argument("--target-lufs", type=float, default=DEFAULT_TARGET_LUFS,
                        help="Integrated loudness target (default: -14)")

    args = parser.parse_args()
    # Read once, then hide the secret from child processes' environments.
    password = getattr(args, 'pass') or os.environ.pop("SOULSEEK_PASS", None)

    if args.process_dir:
        if args.playlist_url or args.user or getattr(args, 'pass') or args.pref_format:
            parser.error("--process-dir cannot be used with download arguments.")
        print(f"Processing local directory: {args.process_dir}", flush=True)
        summary = process_music(args.process_dir, target_lufs=args.target_lufs)
        exit_code = 1 if summary["failed"] else 0

    elif args.playlist_url:
        if not all([args.output_dir, args.user, password, args.pref_format]):
            parser.error("--playlist-url requires --output-dir, --user, --pass, and --pref-format.")
        exit_code = sync_playlist(args, password)

    else:
        parser.error("You must specify either --playlist-url for downloading or --process-dir for local processing.")

    print("Workflow complete." if exit_code == 0 else "Workflow finished with errors; see above.", flush=True)
    return exit_code

if __name__ == "__main__":
    sys.exit(main())
