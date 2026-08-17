#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SITE_FILE="$SCRIPT_DIR/site.txt"

if [ ! -f "$SITE_FILE" ]; then
  echo "Error: $SITE_FILE not found" >&2
  exit 1
fi

URL="$(tr -d '[:space:]' < "$SITE_FILE")"
URL="${URL%/}"

usage() {
  echo "Usage:" >&2
  echo "  $0 exec <command>        — run a shell command" >&2
  echo "  $0 upload <local> <remote> — upload a file" >&2
  echo "  $0 download <remote> [local] — download a file" >&2
  exit 1
}

ACTION="${1:-}"
shift || true

case "$ACTION" in
  exec)
    CMD="$1"
    if [ -z "$CMD" ]; then
      echo "Error: missing command" >&2
      usage
    fi
    RESPONSE=$(curl -s -X POST "$URL/exec" \
      -H "Content-Type: application/json" \
      -d "$(printf '{"cmd":"%s"}' "$(echo "$CMD" | sed 's/"/\\"/g')")")

    STDOUT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('stdout',''),end='')")
    STDERR=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('stderr',''),end='')")
    RC=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('returncode',1))")

    [ -n "$STDOUT" ] && printf '%s' "$STDOUT"
    [ -n "$STDERR" ] && printf '%s' "$STDERR" >&2
    exit "$RC"
    ;;

  upload)
    LOCAL="$1"
    REMOTE="$2"
    if [ -z "$LOCAL" ] || [ -z "$REMOTE" ]; then
      echo "Error: missing local or remote path" >&2
      usage
    fi
    if [ ! -f "$LOCAL" ]; then
      echo "Error: local file not found: $LOCAL" >&2
      exit 1
    fi
    CONTENT=$(base64 -w0 "$LOCAL" 2>/dev/null || base64 "$LOCAL")
    RESPONSE=$(curl -s -X POST "$URL/upload" \
      -H "Content-Type: application/json" \
      -d "$(python3 -c "import json,sys; print(json.dumps({'path':sys.argv[1],'content':sys.argv[2]}))" "$REMOTE" "$CONTENT")")

    echo "$RESPONSE" | python3 -c "
import sys,json
d=json.load(sys.stdin)
if 'error' in d:
    print('Error: '+d['error'], file=sys.stderr); sys.exit(1)
print(f\"Uploaded {d['size']} bytes -> {d['path']}\")"
    ;;

  download)
    REMOTE="$1"
    LOCAL="${2:-$(basename "$REMOTE")}"
    if [ -z "$REMOTE" ]; then
      echo "Error: missing remote path" >&2
      usage
    fi
    ENCODED=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$REMOTE")
    HTTP_CODE=$(curl -s -o "$LOCAL" -w "%{http_code}" "$URL/download?path=$ENCODED")
    if [ "$HTTP_CODE" = "200" ]; then
      echo "Downloaded -> $LOCAL ($(wc -c < "$LOCAL") bytes)"
    else
      echo "Error (HTTP $HTTP_CODE): $(cat "$LOCAL")" >&2
      rm -f "$LOCAL"
      exit 1
    fi
    ;;

  *)
    usage
    ;;
esac
