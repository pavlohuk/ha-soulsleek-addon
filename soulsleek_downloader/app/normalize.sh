#!/bin/bash

# A script to perform two-pass loudness normalization using ffmpeg.
# Usage: normalize.sh <input> <output.mp3> [target LUFS]

# --- Configuration ---
INPUT_FILE="$1"
OUTPUT_FILE="$2"
TARGET_LUFS="${3:--14}"
TRUE_PEAK="-1.5"
TARGET_LRA="11"

# --- Script Logic ---

# Exit immediately if a command exits with a non-zero status.
set -eo pipefail

echo "Running first pass loudness analysis..."

# Run the first pass and capture the detailed log output (ffmpeg writes it to stderr).
if ! LOUDNORM_LOG=$(ffmpeg -hide_banner -nostdin -i "$INPUT_FILE" -map 0:a:0 -af loudnorm=I=$TARGET_LUFS:TP=$TRUE_PEAK:LRA=$TARGET_LRA:print_format=summary -f null - 2>&1); then
    echo "Error: loudness analysis failed."
    echo "--- FFMPEG LOG ---"
    echo "$LOUDNORM_LOG" | tail -n 20
    echo "--------------------"
    exit 1
fi

echo "First pass complete. Parsing statistics..."

# Function to parse a value from the ffmpeg log.
# Usage: parse_value "Value Name"
parse_value() {
    echo "$LOUDNORM_LOG" | grep "$1" | awk -F ':[ \t]+' '{print $2}' | sed 's/ .*//' | tail -n 1
}

# Parse the required values from the log.
MEASURED_I=$(parse_value "Input Integrated")
MEASURED_LRA=$(parse_value "Input LRA")
MEASURED_TP=$(parse_value "Input True Peak")
MEASURED_THRESH=$(parse_value "Input Threshold")
TARGET_OFFSET=$(parse_value "Target Offset")

# Check if all values were parsed successfully.
if [ -z "$MEASURED_I" ] || [ -z "$MEASURED_LRA" ] || [ -z "$MEASURED_TP" ] || [ -z "$MEASURED_THRESH" ] || [ -z "$TARGET_OFFSET" ]; then
    echo "Error: Failed to parse one or more values from the ffmpeg log."
    echo "--- FFMPEG LOG ---"
    echo "$LOUDNORM_LOG"
    echo "--------------------"
    exit 1
fi

echo "Successfully parsed values:"
echo "  - Measured I:      $MEASURED_I"
echo "  - Measured LRA:    $MEASURED_LRA"
echo "  - Measured TP:       $MEASURED_TP"
echo "  - Measured Thresh: $MEASURED_THRESH"
echo "  - Target Offset:   $TARGET_OFFSET"

echo "Running second pass to apply normalization..."

# Second pass with the measured values. Keep only the first audio stream and an
# embedded cover (if any); ID3v2.3 is the most widely supported tag version.
second_pass() {
    ffmpeg -hide_banner -nostdin -v error -i "$INPUT_FILE" -map 0:a:0 "$@" \
        -af loudnorm=I=$TARGET_LUFS:TP=$TRUE_PEAK:LRA=$TARGET_LRA:measured_I=$MEASURED_I:measured_LRA=$MEASURED_LRA:measured_TP=$MEASURED_TP:measured_thresh=$MEASURED_THRESH:offset=$TARGET_OFFSET \
        -c:a libmp3lame -ar 44100 -b:a 320k -id3v2_version 3 -f mp3 "$OUTPUT_FILE" -y
}
if ! second_pass -map "0:v?" -c:v copy; then
    echo "Retrying without the embedded cover..."
    second_pass -vn
fi

echo "Normalization complete for: $OUTPUT_FILE"
