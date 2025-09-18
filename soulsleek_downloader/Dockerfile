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

# Install .NET 8 Runtime for slsk-batchdl
RUN curl -sSL https://dot.net/v1/dotnet-install.sh | bash /dev/stdin --channel 8.0 --runtime dotnet --install-dir /usr/share/dotnet \
    && ln -s /usr/share/dotnet/dotnet /usr/bin/dotnet

# Install slsk-batchdl from GitHub releases
RUN curl -L https://github.com/fiso64/slsk-batchdl/releases/download/v2.5.0/slsk-batchdl-linux-x64 -o /usr/local/bin/sldl \
    && chmod +x /usr/local/bin/sldl

# Copy app
COPY app/ /app/
RUN chmod +x /app/normalize.sh

# Copy data
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
