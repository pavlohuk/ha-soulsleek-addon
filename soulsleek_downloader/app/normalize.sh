#!/bin/bash

# A script to perform two-pass loudness normalization using ffmpeg.

# --- Configuration ---
INPUT_FILE="$1"
OUTPUT_FILE="$2"
TARGET_LUFS="-14"
TRUE_PEAK="-1.5"
TARGET_LRA="11"

# --- Script Logic ---

# Exit immediately if a command exits with a non-zero status.
set -e

echo "Running first pass loudness analysis..."

# Run the first pass and capture the detailed log output.
# We redirect stderr to a variable.
LOUDNORM_LOG=$(ffmpeg -hide_banner -i "$INPUT_FILE" -af loudnorm=I=$TARGET_LUFS:TP=$TRUE_PEAK:LRA=$TARGET_LRA:print_format=summary -f null - 2>&1)

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

# Run the second pass to apply the normalization with the parsed values.
ffmpeg -i "$INPUT_FILE" -af loudnorm=I=$TARGET_LUFS:TP=$TRUE_PEAK:LRA=$TARGET_LRA:measured_I=$MEASURED_I:measured_LRA=$MEASURED_LRA:measured_TP=$MEASURED_TP:measured_thresh=$MEASURED_THRESH:offset=$TARGET_OFFSET -c:a libmp3lame -ar 44100 -b:a 320k "$OUTPUT_FILE" -y

echo "Normalization complete for: $OUTPUT_FILE"
