#!/usr/bin/with-contenv bashio

bashio::log.info "Starting Soulsleek Downloader"

SPOTIFY_PLAYLIST_URL=$(bashio::config 'spotify_playlist_url')
OUTPUT_DIRECTORY=$(bashio::config 'output_directory')
SOULSEEK_USER=$(bashio::config 'soulseek_user')
PREFERRED_FORMAT=$(bashio::config 'preferred_format')
# Passed via the environment so the password never appears in the process list.
SOULSEEK_PASS=$(bashio::config 'soulseek_pass')
export SOULSEEK_PASS

# Only the add-on's mounted folders survive a container restart.
case "${OUTPUT_DIRECTORY%/}/" in
    /media/*|/share/*) ;;
    *) bashio::exit.nok "output_directory must be inside /media or /share (got: ${OUTPUT_DIRECTORY})" ;;
esac

# Existing installations may not have the newer options saved yet.
EXTRA_ARGS=(--youtube-fallback --notify)
if bashio::config.has_value 'youtube_fallback' && bashio::config.false 'youtube_fallback'; then
    EXTRA_ARGS[0]=--no-youtube-fallback
fi
if bashio::config.has_value 'notify' && bashio::config.false 'notify'; then
    EXTRA_ARGS[1]=--no-notify
fi
if bashio::config.has_value 'concurrent_downloads'; then
    EXTRA_ARGS+=(--concurrent-downloads "$(bashio::config 'concurrent_downloads')")
fi
if bashio::config.has_value 'target_loudness'; then
    EXTRA_ARGS+=(--target-lufs "$(bashio::config 'target_loudness')")
fi

# YouTube changes often; a stale yt-dlp silently breaks the fallback.
if ! bashio::config.false 'update_yt_dlp' && ! bashio::config.false 'youtube_fallback'; then
    bashio::log.info "Updating yt-dlp..."
    if ! timeout 180 pip install --break-system-packages --no-cache-dir --quiet --upgrade 'yt-dlp[default]'; then
        bashio::log.warning "yt-dlp update failed; using $(python3 -m yt_dlp --version 2>/dev/null || echo 'the bundled version')"
    fi
fi

bashio::log.info "Spotify Playlist URL: ${SPOTIFY_PLAYLIST_URL}"
bashio::log.info "Output Directory: ${OUTPUT_DIRECTORY}"

exec python3 /app/main.py \
    --playlist-url "$SPOTIFY_PLAYLIST_URL" \
    --output-dir "$OUTPUT_DIRECTORY" \
    --user "$SOULSEEK_USER" \
    --pref-format "$PREFERRED_FORMAT" \
    --state-dir /data/state \
    "${EXTRA_ARGS[@]}"
