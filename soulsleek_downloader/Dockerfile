ARG BUILD_FROM
FROM $BUILD_FROM

# Set up environment
ENV LANG=C.UTF-8

# Install system dependencies
RUN apk add --no-cache \
    python3 \
    ffmpeg \
    curl \
    bash \
    icu-libs \
    libgcc \
    libintl \
    libssl3 \
    libstdc++ \
    zlib

# Install .NET 8 SDK for slsk-batchdl compilation
RUN curl -sSL https://dot.net/v1/dotnet-install.sh | bash /dev/stdin --channel 8.0 --install-dir /usr/share/dotnet \
    && ln -s /usr/share/dotnet/dotnet /usr/bin/dotnet

# Install git for source cloning
RUN apk add --no-cache git unzip

# Install slsk-batchdl from GitHub releases or compile from source
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then \
        curl -L https://github.com/fiso64/slsk-batchdl/releases/download/v2.5.0/sldl_linux-x64.zip -o sldl.zip && \
        unzip sldl.zip && mv sldl /usr/local/bin/ && chmod +x /usr/local/bin/sldl; \
    elif [ "$ARCH" = "armv7l" ]; then \
        curl -L https://github.com/fiso64/slsk-batchdl/releases/download/v2.5.0/sldl_linux-arm.zip -o sldl.zip && \
        unzip sldl.zip && mv sldl /usr/local/bin/ && chmod +x /usr/local/bin/sldl; \
    else \
        git clone https://github.com/fiso64/slsk-batchdl.git /tmp/slsk-batchdl && \
        cd /tmp/slsk-batchdl && \
        dotnet publish -c Release -r linux-musl-x64 --self-contained -p:PublishSingleFile=true -o /usr/local/bin && \
        mv /usr/local/bin/slsk-batchdl /usr/local/bin/sldl; \
    fi && \
    rm -rf /tmp/slsk-batchdl sldl.zip

# Copy app
COPY app/ /app/
RUN chmod +x /app/normalize.sh

# Copy data
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
