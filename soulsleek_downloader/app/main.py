import argparse
import os
import subprocess
import json

def download_music(playlist_url, output_dir, log_file, user, password, pref_format):
    """
    Downloads music from Soulseek using slsk-batchdl and logs the output.
    """
    print(f"Downloading music from {playlist_url} to {output_dir}")
    command = [
        "sldl", playlist_url,
        "-p", output_dir,
        "--user", user,
        "--pass", password,
        "--pref-format", pref_format
    ]
    
    try:
        with open(log_file, 'w') as f:
            subprocess.run(command, check=True, stdout=f, stderr=subprocess.STDOUT)
        print(f"Download process finished. See {log_file} for details.")
    except subprocess.CalledProcessError as e:
        print(f"An error occurred during download: {e}")
        with open(log_file, 'a') as f:
            f.write(f"\n\nAn error occurred: {e}")

def process_music(directory):
    """
    Processes the downloaded music using beets.
    - Updates metadata and adds cover art.
    - Normalizes volume using ffmpeg.
    - Converts to a compatible bitrate.
    - Checks file integrity.
    - Renames files to 'Title - Artist'.
    """
    print(f"Processing music in {directory}")
    
    # Configure beets
    beets_config = f"""
directory: {directory}
library: {directory}/library.db
plugins: fetchart convert check
paths:
    default: '%aunique{{%asciify{{$artist}}%}}/%aunique{{%asciify{{$album}}%}}/%if{{$multidisc,Disc $disc/%}}{{$track %total}} - %aunique{{%asciify{{$title}}%}}'
    singleton: '%aunique{{%asciify{{$artist}}%}}/{%aunique{{%asciify{{$title}}%}}} - %aunique{{%asciify{{$artist}}%}}'
    comp: 'Compilations/%aunique{{%asciify{{$album}}%}}/%if{{$multidisc,Disc $disc/%}}{{$track %total}} - %aunique{{%asciify{{$title}}%}}'
fetchart:
    auto: yes
convert:
    auto: yes
    command: /app/normalize.sh $source $dest
    extension: mp3
check:
    import: yes
"""
    beets_config_path = os.path.join(directory, "beets_config.yaml")
    with open(beets_config_path, "w") as f:
        f.write(beets_config)

    # Import and process music with beets
    import_command = ["beet", "--config", beets_config_path, "import", "-q", directory]
    
    try:
        subprocess.run(import_command, check=True)
        print("Music processing complete.")
    except subprocess.CalledProcessError as e:
        print(f"An error occurred during music processing: {e}")


def main():
    parser = argparse.ArgumentParser(description="Soulsleek Downloader")
    parser.add_argument("--playlist-url", required=True, help="Spotify playlist URL")
    parser.add_argument("--output-dir", required=True, help="Output directory for downloaded music")
    parser.add_argument("--user", required=True, help="Soulseek username")
    parser.add_argument("--pass", required=True, help="Soulseek password")
    parser.add_argument("--pref-format", required=True, help="Preferred file format")
    args = parser.parse_args()

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

    print("Workflow complete.")

if __name__ == "__main__":
    main()
