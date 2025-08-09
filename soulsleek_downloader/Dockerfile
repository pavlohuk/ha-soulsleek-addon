ARG BUILD_FROM
FROM $BUILD_FROM

# Set up environment
ENV LANG C.UTF-8

# Install dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    ffmpeg \
    dotnet-sdk \
    jq

# Install beets
RUN pip3 install beets

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
