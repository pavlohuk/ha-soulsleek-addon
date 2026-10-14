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
    nodejs \
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
    git clone --depth 1 --branch v2.6.0 https://github.com/fiso64/slsk-batchdl.git /tmp/slsk-batchdl && \
    cd /tmp/slsk-batchdl && \
    # Keep the existing CLI/index format; upstream 3.x renamed the project.
    # Build both projects on the installed .NET 8 runtime.
    sed -i 's/net6.0/net8.0/g' slsk-batchdl/slsk-batchdl.csproj slsk-batchdl.HelpGenerator/slsk-batchdl.HelpGenerator.csproj && \
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
RUN pip install --break-system-packages --no-cache-dir 'beets[fetchart,embedart,musicbrainz]' 'yt-dlp[default]' && \
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
