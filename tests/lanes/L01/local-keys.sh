#!/usr/bin/env bash
# Local-only disposable signing material. Never commit the generated ignored files.
set -euo pipefail
cd "$(dirname "$0")"
if [ -e local-config.key ]; then echo 'Existing local keys preserved; source tests/lanes/L01/local-config.key'; exit 0; fi
umask 077
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out user-private.pem 2>/dev/null
openssl pkey -in user-private.pem -pubout -out user-public.pem
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out event-private.pem 2>/dev/null
openssl pkey -in event-private.pem -pubout -out event-public.pem
python3 - <<'PY'
from pathlib import Path
pairs={'BT_AUTH_PRIVATE_KEY':'user-private.pem','BT_AUTH_PUBLIC_KEY':'user-public.pem','BT_EVENT_PRIVATE_KEY':'event-private.pem','BT_SERVICE_AUTH_PUBLIC_KEY':'event-public.pem'}
text=''.join(f"{name}='{Path(file).read_text().replace(chr(10), chr(92)+'n')}'\n" for name,file in pairs.items())
Path('local-config.key').write_text(text+"BT_LOCAL_HTTP=1\nBT_WEB_ORIGIN=http://localhost:3000\n")
PY
echo 'Source tests/lanes/L01/local-config.key before running the lane Compose launcher.'
