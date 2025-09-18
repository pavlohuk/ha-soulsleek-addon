ARG BUILD_FROM
FROM $BUILD_FROM

# Set up environment
ENV LANG=C.UTF-8

# Install system dependencies
RUN apk add --no-cache \
    python3 \
    python3-dev \
    py3-pip \
    ffmpeg \
    curl \
    bash \
    icu-libs \
    libgcc \
    libintl \
    libssl3 \
    libstdc++ \
    zlib \
    build-base \
    jpeg-dev \
    zlib-dev

# Install .NET 8 SDK for slsk-batchdl compilation
RUN curl -sSL https://dot.net/v1/dotnet-install.sh | bash /dev/stdin --channel 8.0 --install-dir /usr/share/dotnet \
    && ln -s /usr/share/dotnet/dotnet /usr/bin/dotnet

# Install git for source cloning
RUN apk add --no-cache git unzip

# Compile slsk-batchdl from source with musl compatibility for all architectures
RUN ARCH=$(uname -m) && \
    echo "Detected architecture: $ARCH" && \
    echo "Compiling from source for musl compatibility..." && \
    git clone https://github.com/fiso64/slsk-batchdl.git /tmp/slsk-batchdl && \
    cd /tmp/slsk-batchdl && \
    if [ "$ARCH" = "x86_64" ]; then \
        DOTNET_ARCH="linux-musl-x64"; \
    elif [ "$ARCH" = "aarch64" ]; then \
        DOTNET_ARCH="linux-musl-arm64"; \
    else \
        DOTNET_ARCH="linux-musl-x64"; \
    fi && \
    echo "Building for $DOTNET_ARCH..." && \
    dotnet publish slsk-batchdl/slsk-batchdl.csproj -c Release -r $DOTNET_ARCH --self-contained -p:PublishSingleFile=true -o /usr/local/bin && \
    ls -la /usr/local/bin/ && \
    echo "Verifying sldl installation:" && ls -la /usr/local/bin/sldl && \
    echo "Testing sldl:" && (/usr/local/bin/sldl --version || echo "Version check failed") && \
    rm -rf /tmp/slsk-batchdl

# Install beets for metadata and cover art processing
RUN python3 -m venv /opt/beets && \
    /opt/beets/bin/pip install --no-cache-dir beets[fetchart,embedart,chroma,discogs,musicbrainz] && \
    ln -s /opt/beets/bin/beet /usr/local/bin/beet && \
    mkdir -p /root/.config/beets

# Copy beets configuration
COPY beets_config.yaml /root/.config/beets/config.yaml

# Copy app
COPY app/ /app/
RUN chmod +x /app/normalize.sh

# Copy data
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
