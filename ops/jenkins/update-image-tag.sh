#!/bin/sh

set -eu

if [ "$#" -ne 3 ]; then
    echo "Usage: $0 <kustomization-file> <image-name> <immutable-tag>" >&2
    exit 64
fi

kustomization_file=$1
image_name=$2
image_tag=$3
temporary_file="${kustomization_file}.tmp"

trap 'rm -f "$temporary_file"' EXIT HUP INT TERM

awk -v image="$image_name" -v tag="$image_tag" '
    $1 == "-" && $2 == "name:" {
        matching_image = ($3 == image)
    }
    matching_image && $1 == "newTag:" {
        sub(/newTag:.*/, "newTag: " tag)
        matching_image = 0
        updated = 1
    }
    { print }
    END {
        if (!updated) {
            exit 42
        }
    }
' "$kustomization_file" > "$temporary_file" || {
    status=$?
    if [ "$status" -eq 42 ]; then
        echo "Image '$image_name' was not found in $kustomization_file" >&2
    fi
    exit "$status"
}

mv "$temporary_file" "$kustomization_file"
trap - EXIT HUP INT TERM
