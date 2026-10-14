import argparse
import os
import subprocess
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import tempfile
import signal
from youtube_fallback import download_missing_tracks, missing_tracks
from download_recovery import configure_file_limit, rebuild_crashed_index
from spotify_playlist import prepare_spotify_playlist

def download_music(playlist_url, output_dir, log_file, user, password, pref_format, index_file=None):
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
    configure_file_limit()
    max_concurrent = 2
    
    command = [
        "/usr/local/bin/sldl", playlist_url,
        "-p", output_dir,
        "--user", user,
        "--pass", password,
        "--pref-format", pref_format,
        "--concurrent-downloads", str(max_concurrent),
        "--no-progress",
    ]
    if index_file:
        command.extend(["--index-path", index_file])
    
    failed_tracks = []
    resource_exhausted = False
    
    try:
        print(f"🎵 Starting download from Spotify playlist...", flush=True)
        
        # Run process and capture essential output only
        with open(log_file, 'w') as f:
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

def normalize_single_file(file_path, normalize_script_path, converted_dir):
    """
    Normalize a single audio file.
    """
    try:
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        output_file = os.path.join(converted_dir, f"{base_name}.mp3")
        
        print(f"🎧 Processing: {os.path.basename(file_path)}", flush=True)

        command = ["bash", normalize_script_path, file_path, output_file]
        
        # Run normalization with minimal output
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                 universal_newlines=True, encoding="utf-8", errors="replace", bufsize=0)
        
        # Capture loudness values but don't show FFmpeg details
        loudness_info = {}
        for line in process.stdout:
            line = line.rstrip()
            if "Measured I:" in line:
                loudness_info['input'] = line.split(':')[1].strip()
            elif "Target Offset:" in line:
                loudness_info['offset'] = line.split(':')[1].strip()
            elif "Normalization complete" in line:
                if loudness_info:
                    print(f"   📊 Input: {loudness_info.get('input', 'N/A')} LUFS → Target: -14 LUFS", flush=True)
        
        process.stdout.close()
        process.wait()
        
        if process.returncode == 0:
            print(f"   ✅ Successfully normalized: {os.path.basename(output_file)}", flush=True)
            return {"status": "success", "file": file_path}
        else:
            return {"status": "failed", "file": file_path, "error": f"Exit code: {process.returncode}"}
            
    except Exception as e:
        return {"status": "failed", "file": file_path, "error": str(e)}

def update_metadata_with_beets(music_directory):
    """
    Update metadata and fetch cover art using beets.
    """
    print(f"🎨 Updating metadata and fetching cover art...", flush=True)
    
    try:
        # Import files to beets and update metadata
        command = ["beet", "import", "-A", "-q", music_directory]
        
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                 universal_newlines=True, encoding="utf-8", errors="replace", bufsize=0)
        
        import_successful = False
        for line in process.stdout:
            line = line.rstrip()
            if line:
                if "tagging" in line.lower() or "found" in line.lower():
                    print(f"   📋 {line}", flush=True)
                elif "fetching" in line.lower() or "art" in line.lower():
                    print(f"   🖼️ {line}", flush=True)
                elif "error" in line.lower():
                    print(f"   ⚠️ {line}", flush=True)
                else:
                    # Show other important messages
                    if any(keyword in line.lower() for keyword in ["album", "track", "match"]):
                        print(f"   {line}", flush=True)
        
        process.stdout.close()
        process.wait()
        
        if process.returncode == 0:
            print(f"   ✅ Metadata and cover art processing completed", flush=True)
            return True
        else:
            print(f"   ⚠️ Beets processing completed with warnings (exit code: {process.returncode})", flush=True)
            return True  # Continue even with warnings
            
    except Exception as e:
        print(f"   ❌ Beets processing failed: {e}", flush=True)
        return False

def process_music(directory):
    """
    Processes music in the given directory by finding all audio files,
    running the normalize.sh script on them, and reporting any failures.
    """
    print(f"Starting to process and normalize music in: {directory}", flush=True)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    normalize_script_path = os.path.join(script_dir, "normalize.sh")

    if not os.access(normalize_script_path, os.X_OK):
        print(f"[ERROR] Normalize script not found or not executable at: {normalize_script_path}", flush=True)
        return

    audio_files = []
    supported_extensions = ['.flac', '.mp3', '.ogg', '.wav', '.aiff']
    for root, _, files in os.walk(directory):
        for file in files:
            if any(file.lower().endswith(ext) for ext in supported_extensions):
                audio_files.append(os.path.join(root, file))

    if not audio_files:
        print("No audio files found to process.", flush=True)
        return

    parent_dir = os.path.abspath(os.path.join(directory, os.pardir))
    converted_dir = parent_dir
    os.makedirs(converted_dir, exist_ok=True)
    
    # Determine number of threads (use half of available cores for stability)
    max_workers = max(1, multiprocessing.cpu_count() // 2)
    print(f"Found {len(audio_files)} audio files. Using {max_workers} threads for processing.", flush=True)
    print(f"Converted files will be saved to: {converted_dir}", flush=True)

    successful_conversions = []
    failed_conversions = []

    # Process files in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for file_path in audio_files:
            future = executor.submit(normalize_single_file, file_path, normalize_script_path, converted_dir)
            futures.append(future)
        
        # Collect results
        for future in futures:
            result = future.result()
            if result["status"] == "success":
                successful_conversions.append(result["file"])
            else:
                failed_conversions.append({"file": result["file"], "error": result["error"]})

    print("\n--- PROCESSING REPORT ---", flush=True)
    print(f"Successfully converted {len(successful_conversions)} files.", flush=True)
    
    if failed_conversions:
        print(f"Failed to convert {len(failed_conversions)} files:", flush=True)
        for failed in failed_conversions:
            print(f"  - File: {os.path.basename(failed['file'])}", flush=True)
    
    # Update metadata and fetch cover art with beets (only if conversions were successful)
    if successful_conversions:
        print(f"\n🎨 Starting metadata and cover art processing...", flush=True)
        update_metadata_with_beets(converted_dir)
    
    # Preserve originals when conversion fails, including recovered YouTube audio.
    if failed_conversions:
        print(f"⚠️ Keeping downloads for retry: {directory}", flush=True)
        return

    # Clean up downloads folder after successful processing
    try:
        shutil.rmtree(directory)
        print(f"✅ Cleaned up downloads folder: {directory}", flush=True)
    except Exception as e:
        print(f"⚠️ Could not remove downloads folder: {e}", flush=True)
    
    print("--------------------------\n", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Soulsleek Downloader and Processor")
    
    # Group for download functionality
    download_group = parser.add_argument_group('Download and Process')
    download_group.add_argument("--playlist-url", help="Spotify playlist URL")
    download_group.add_argument("--output-dir", help="Output directory for music")
    download_group.add_argument("--user", help="Soulseek username")
    download_group.add_argument("--pass", help="Soulseek password")
    download_group.add_argument("--pref-format", help="Preferred file format for download")
    download_group.add_argument(
        "--youtube-fallback", action=argparse.BooleanOptionalAction, default=True,
        help="Recover missing Soulseek tracks from YouTube (default: enabled)",
    )

    # Group for local processing functionality
    process_group = parser.add_argument_group('Process Local Folder')
    process_group.add_argument("--process-dir", help="Path to a local directory to process")

    args = parser.parse_args()

    if args.process_dir:
        if args.playlist_url or args.user or getattr(args, 'pass') or args.pref_format:
            parser.error("--process-dir cannot be used with download arguments.")
        print(f"Processing local directory: {args.process_dir}", flush=True)
        process_music(args.process_dir)

    elif args.playlist_url:
        if not all([args.output_dir, args.user, getattr(args, 'pass'), args.pref_format]):
            parser.error("--playlist-url requires --output-dir, --user, --pass, and --pref-format.")
        
        download_dir = os.path.join(args.output_dir, "downloads")
        os.makedirs(download_dir, exist_ok=True)
        
        log_file = os.path.join(args.output_dir, "download_log.txt")

        # A fresh structured index prevents retrying failures from another playlist/run.
        with tempfile.TemporaryDirectory(prefix="soulsleek-index-") as index_dir:
            index_file = os.path.join(index_dir, "tracks.csv")
            try:
                print("Loading public Spotify playlist...", flush=True)
                playlist_input = prepare_spotify_playlist(args.playlist_url, index_dir)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                print(f"❌ Playlist import failed: {error}", flush=True)
                print("Workflow failed before track search. See the Home Assistant add-on log above.", flush=True)
                return 1
            download_success, failed_tracks = download_music(
                playlist_input, download_dir, log_file, args.user,
                getattr(args, 'pass'), args.pref_format, index_file=index_file,
            )
            if not download_success and not os.path.isfile(index_file):
                print("❌ Downloader stopped before producing track results; YouTube fallback cannot run.", flush=True)
                print(f"See the error above or {log_file}.", flush=True)
                return 1
            if args.youtube_fallback:
                download_missing_tracks(index_file, download_dir, log_file)
        
        if download_success or os.listdir(download_dir):  # Process if download succeeded or files exist
            process_music(download_dir)
    
    else:
        parser.error("You must specify either --playlist-url for downloading or --process-dir for local processing.")

    print("Workflow complete.", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
