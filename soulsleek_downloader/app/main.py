import argparse
import os
import subprocess
import json
import shutil

def download_music(playlist_url, output_dir, log_file, user, password, pref_format):
    """
    Downloads music from Soulseek using slsk-batchdl and logs the output.
    """
    # Debug: Check if sldl exists and works
    import os
    if os.path.exists("/usr/local/bin/sldl"):
        print("✅ /usr/local/bin/sldl found")
        os.system("ls -la /usr/local/bin/sldl")
        print("🔍 Testing sldl execution:")
        result = os.system("/usr/local/bin/sldl --help 2>&1 || echo 'sldl failed to run'")
        print(f"Command result: {result}")
        print("🔍 LDD dependencies:")
        os.system("ldd /usr/local/bin/sldl 2>&1 || echo 'ldd failed'")
    else:
        print("❌ /usr/local/bin/sldl NOT found")
        print("Contents of /usr/local/bin/:")
        os.system("ls -la /usr/local/bin/")
    
    print(f"Downloading music from {playlist_url} to {output_dir}")
    command = [
        "/usr/local/bin/sldl", playlist_url,
        "-p", output_dir,
        "--user", user,
        "--pass", password,
        "--pref-format", pref_format
    ]
    
    try:
        print(f"🎵 Starting download with command: {' '.join(command)}")
        print("=" * 60)
        
        # Run process and stream output in real-time
        with open(log_file, 'w') as f:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                     universal_newlines=True, bufsize=1)
            
            for line in process.stdout:
                line = line.rstrip()
                if line:  # Only print non-empty lines
                    print(line)  # This appears in add-on logs
                    f.write(line + '\n')
                    f.flush()
            
            process.wait()
        
        print("=" * 60)
        if process.returncode == 0:
            print(f"✅ Download completed successfully!")
        else:
            print(f"❌ Download failed with exit code: {process.returncode}")
            
    except Exception as e:
        print(f"❌ Download error: {e}")
        with open(log_file, 'a') as f:
            f.write(f"\n\nError: {e}")

def process_music(directory):
    """
    Processes music in the given directory by finding all audio files,
    running the normalize.sh script on them, and reporting any failures.
    """
    print(f"Starting to process and normalize music in: {directory}")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    normalize_script_path = os.path.join(script_dir, "normalize.sh")

    if not os.access(normalize_script_path, os.X_OK):
        print(f"[ERROR] Normalize script not found or not executable at: {normalize_script_path}")
        return

    audio_files = []
    supported_extensions = ['.flac', '.mp3', '.ogg', '.wav', '.aiff']
    for root, _, files in os.walk(directory):
        for file in files:
            if any(file.lower().endswith(ext) for ext in supported_extensions):
                audio_files.append(os.path.join(root, file))

    if not audio_files:
        print("No audio files found to process.")
        return

    parent_dir = os.path.abspath(os.path.join(directory, os.pardir))
    converted_dir = parent_dir
    os.makedirs(converted_dir, exist_ok=True)
    
    print(f"Found {len(audio_files)} audio files. Converted files will be saved to: {converted_dir}")

    successful_conversions = []
    failed_conversions = []

    for file_path in audio_files:
        try:
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            output_file = os.path.join(converted_dir, f"{base_name}.mp3")
            
            print(f"🎧 Processing: {os.path.basename(file_path)}")

            command = ["bash", normalize_script_path, file_path, output_file]
            
            # Run normalization and stream output to console
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                     universal_newlines=True, bufsize=1)
            
            for line in process.stdout:
                line = line.rstrip()
                if line:
                    print(f"   {line}")
            
            process.wait()
            result_returncode = process.returncode

            if result_returncode == 0:
                successful_conversions.append(file_path)
                print(f"   ✅ Successfully normalized: {os.path.basename(output_file)}")
            else:
                failed_conversions.append({"file": file_path, "error": f"Exit code: {result_returncode}"})
        except Exception as e:
            failed_conversions.append({"file": file_path, "error": str(e)})

    print("\n--- PROCESSING REPORT ---")
    print(f"Successfully converted {len(successful_conversions)} files.")
    
    if failed_conversions:
        print(f"Failed to convert {len(failed_conversions)} files:")
        for failed in failed_conversions:
            print(f"  - File: {os.path.basename(failed['file'])}")
    
    # Clean up downloads folder after processing
    try:
        shutil.rmtree(directory)
        print(f"✅ Cleaned up downloads folder: {directory}")
    except Exception as e:
        print(f"⚠️ Could not remove downloads folder: {e}")
    
    print("--------------------------\n")


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
        print(f"Processing local directory: {args.process_dir}")
        process_music(args.process_dir)

    elif args.playlist_url:
        if not all([args.output_dir, args.user, getattr(args, 'pass'), args.pref_format]):
            parser.error("--playlist-url requires --output-dir, --user, --pass, and --pref-format.")
        
        download_dir = os.path.join(args.output_dir, "downloads")
        os.makedirs(download_dir, exist_ok=True)
        
        log_file = os.path.join(args.output_dir, "download_log.txt")

        download_music(
            args.playlist_url,
            download_dir,
            log_file,
            args.user,
            getattr(args, 'pass'),
            args.pref_format
        )
        process_music(download_dir)
    
    else:
        parser.error("You must specify either --playlist-url for downloading or --process-dir for local processing.")

    print("Workflow complete.")

if __name__ == "__main__":
    main()
