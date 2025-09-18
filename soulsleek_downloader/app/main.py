import argparse
import os
import subprocess
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import tempfile

def download_music(playlist_url, output_dir, log_file, user, password, pref_format):
    """
    Downloads music from Soulseek using slsk-batchdl and logs the output.
    Returns tuple of (success, failed_tracks_list)
    """
    # Verify sldl binary exists
    if not os.path.exists("/usr/local/bin/sldl"):
        print("❌ sldl binary not found", flush=True)
        return False, []
    
    print(f"Downloading music from {playlist_url} to {output_dir}", flush=True)
    # Use multiple concurrent downloads for sldl
    max_concurrent = min(4, multiprocessing.cpu_count())
    
    command = [
        "/usr/local/bin/sldl", playlist_url,
        "-p", output_dir,
        "--user", user,
        "--pass", password,
        "--pref-format", pref_format,
        "--concurrent-downloads", str(max_concurrent)
    ]
    
    failed_tracks = []
    
    try:
        print(f"🎵 Starting download from Spotify playlist...", flush=True)
        
        # Run process and capture essential output only
        with open(log_file, 'w') as f:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                     universal_newlines=True, bufsize=0)
            
            for line in process.stdout:
                line = line.rstrip()
                f.write(line + '\n')
                f.flush()
                
                # Track failed downloads
                if "Failed:" in line and "artist:" in line.lower():
                    # Extract track info from failed download line
                    failed_tracks.append(line)
                
                # Only show essential download progress
                if any(keyword in line for keyword in [
                    'Downloading', 'tracks:', 'Succeeded:', 'Failed:', 'Completed:'
                ]):
                    print(line, flush=True)
            
            process.wait()
        
        # Show download summary
        if failed_tracks:
            print(f"\n📋 DOWNLOAD SUMMARY:", flush=True)
            print(f"❌ Failed to download {len(failed_tracks)} tracks:", flush=True)
            for failed_track in failed_tracks:
                # Clean up the failed track info for display
                clean_track = failed_track.replace("Failed:", "").strip()
                print(f"   • {clean_track}", flush=True)
            print(flush=True)
        
        if process.returncode == 0:
            print(f"✅ Download completed successfully!", flush=True)
            return True, failed_tracks
        else:
            print(f"❌ Download failed with exit code: {process.returncode}", flush=True)
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
                                 universal_newlines=True, bufsize=0)
        
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
                                 universal_newlines=True, bufsize=0)
        
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
    
    # Clean up downloads folder after processing
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

        download_success, failed_tracks = download_music(
            args.playlist_url,
            download_dir,
            log_file,
            args.user,
            getattr(args, 'pass'),
            args.pref_format
        )
        
        if download_success or os.listdir(download_dir):  # Process if download succeeded or files exist
            process_music(download_dir)
    
    else:
        parser.error("You must specify either --playlist-url for downloading or --process-dir for local processing.")

    print("Workflow complete.", flush=True)

if __name__ == "__main__":
    main()
