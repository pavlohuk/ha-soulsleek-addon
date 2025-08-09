#!/bin/bash

# A script to perform two-pass loudness normalization using ffmpeg.

INPUT_FILE="$1"
OUTPUT_FILE="$2"
TARGET_LUFS="-14"
TRUE_PEAK="-1.5"
TARGET_LRA="11"

# Run the first pass to get audio stats from the loudnorm filter.
# The output is parsed with jq to extract the measured values.
LOUDNORM_STATS=$(ffmpeg -hide_banner -i "$INPUT_FILE" -af loudnorm=I=$TARGET_LUFS:TP=$TRUE_PEAK:LRA=$TARGET_LRA:print_format=json -f null - 2>&1 | tail -n 12)

# Extract measured values using jq
MEASURED_I=$(echo "$LOUDNORM_STATS" | jq -r '.input_i')
MEASURED_LRA=$(echo "$LOUDNORM_STATS" | jq -r '.input_lra')
MEASURED_TP=$(echo "$LOUDNORM_STATS" | jq -r '.input_tp')
MEASURED_THRESH=$(echo "$LOUDNORM_STATS" | jq -r '.input_thresh')
TARGET_OFFSET=$(echo "$LOUDNORM_STATS" | jq -r '.target_offset')

# Run the second pass to apply the normalization.
ffmpeg -i "$INPUT_FILE" -af loudnorm=I=$TARGET_LUFS:TP=$TRUE_PEAK:LRA=$TARGET_LRA:measured_I=$MEASURED_I:measured_LRA=$MEASURED_LRA:measured_TP=$MEASURED_TP:measured_thresh=$MEASURED_THRESH:offset=$TARGET_OFFSET -ar 44100 -b:a 320k "$OUTPUT_FILE" -y
