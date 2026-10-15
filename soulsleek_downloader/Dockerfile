ARG BUILD_FROM

# --- Build slsk-batchdl in a throwaway SDK stage ---------------------------------
FROM mcr.microsoft.com/dotnet/sdk:8.0-alpine AS sldl
ARG BUILD_ARCH
RUN apk add --no-cache git
# Keep the existing CLI/index format; upstream 3.x renamed the project.
# Build both projects on the .NET 8 SDK (upstream targets .NET 6).
RUN git clone --depth 1 --branch v2.6.0 https://github.com/fiso64/slsk-batchdl.git /src \
    && sed -i 's/net6.0/net8.0/g' /src/slsk-batchdl/slsk-batchdl.csproj /src/slsk-batchdl.HelpGenerator/slsk-batchdl.HelpGenerator.csproj
RUN ARCH="${BUILD_ARCH:-$(uname -m)}" \
    && case "$ARCH" in \
        amd64|x86_64) RID=linux-musl-x64 ;; \
        aarch64|arm64) RID=linux-musl-arm64 ;; \
        *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;; \
    esac \
    && echo "Building slsk-batchdl for $RID" \
    && dotnet publish /src/slsk-batchdl/slsk-batchdl.csproj -c Release -r "$RID" --self-contained \
        -p:PublishSingleFile=true -o /out

# --- Runtime image ------------------------------------------------------------------
FROM $BUILD_FROM

ENV LANG=C.UTF-8

# Runtime libraries for the self-contained .NET binary, FFmpeg and Node.js (yt-dlp EJS).
RUN apk add --no-cache \
    python3 \
    py3-pip \
    ffmpeg \
    nodejs \
    bash \
    icu-libs \
    libgcc \
    libintl \
    libssl3 \
    libstdc++ \
    zlib

COPY --from=sldl /out/sldl /usr/local/bin/sldl
# Fail the build if the binary cannot start on this architecture.
RUN /usr/local/bin/sldl --version

RUN pip install --break-system-packages --no-cache-dir \
        'mutagen>=1.47' 'yt-dlp[default]' 'spotapi[redis,pymongo,websocket]==1.2.8' \
    && python3 -c 'from spotapi import PublicPlaylist; import mutagen, yt_dlp'

# Copy app
COPY app/ /app/
RUN chmod +x /app/normalize.sh

# Copy data
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]

ARG BUILD_ARCH
ARG BUILD_VERSION
LABEL \
    io.hass.name="Soulsleek Downloader" \
    io.hass.type="addon" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.version="${BUILD_VERSION}" \
    org.opencontainers.image.source="https://github.com/pavlohuk/ha-soulsleek-addon"
