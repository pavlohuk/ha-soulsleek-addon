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

# Install .NET 8 Runtime manually
RUN curl -sSL https://dot.net/v1/dotnet-install.sh | bash /dev/stdin --channel 8.0 --runtime dotnet --install-dir /usr/share/dotnet \
    && ln -s /usr/share/dotnet/dotnet /usr/bin/dotnet

# Set up slsk-batchdl
RUN dotnet tool install --global slsk-batchdl --version 2.4.7

# Add tools to path
ENV PATH="/root/.dotnet/tools:${PATH}"

# Copy app
COPY app/ /app/
RUN chmod +x /app/normalize.sh

# Copy data
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
