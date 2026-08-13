#!/usr/bin/env bash
set -euo pipefail

# update-memory-banks.sh - Idempotently provisions and updates Hindsight memory bank configurations and mental models only when differences are detected.

usage() {
    cat <<'EOF'
Usage: ./update-memory-banks.sh <BANKS_DIR> <API_URL> --yes [--prune]

Provisions and updates Hindsight memory bank configurations and Mental Models
via the specified Hindsight REST API URL only if local definitions differ from server state.

Mandatory Arguments & Flags:
  BANKS_DIR   Directory containing bank .json files
  API_URL     Hindsight API base URL (e.g., http://localhost:8888)
  -y, --yes    Mandatory confirmation flag for execution

Flags:
  -p, --prune  Prune leftover mental models on server not present in bank JSON
  -h, --help   Show this help message and exit

Examples:
  ./update-memory-banks.sh ./memorybanks http://localhost:8888 --yes
  ./update-memory-banks.sh ./memorybanks http://localhost:8888 --yes --prune
EOF
}

CONFIRMED="false"
PRUNE="false"
BANKS_DIR=""
API_URL=""

while [ "${#}" -gt 0 ]; do
    case "${1}" in
    -y | --yes)
        CONFIRMED="true"
        shift
        ;;
    -p | --prune)
        PRUNE="true"
        shift
        ;;
    -h | --help)
        usage
        exit 0
        ;;
    -*)
        echo "Error: Unknown option '${1}'" >&2
        echo "" >&2
        usage
        exit 1
        ;;
    *)
        if [ -z "${BANKS_DIR}" ]; then
            BANKS_DIR="${1}"
        elif [ -z "${API_URL}" ]; then
            API_URL="${1}"
        fi
        shift
        ;;
    esac
done

if [ -z "${BANKS_DIR}" ]; then
    echo "Error: Missing mandatory BANKS_DIR parameter." >&2
    echo "" >&2
    usage
    exit 1
fi

if [ -z "${API_URL}" ]; then
    echo "Error: Missing mandatory API_URL parameter." >&2
    echo "" >&2
    usage
    exit 1
fi

if [ "${CONFIRMED}" != "true" ]; then
    echo "Error: Missing mandatory '--yes' / '-y' confirmation flag." >&2
    echo "" >&2
    usage
    exit 1
fi

echo "=== Provisioning Hindsight memory banks from: ${BANKS_DIR} ==="
echo "=== Hindsight API URL: ${API_URL} ==="
echo "=== Prune leftover mental models: ${PRUNE} ==="

if [ ! -d "${BANKS_DIR}" ]; then
    echo "Memory banks directory '${BANKS_DIR}' does not exist yet. Skipping bank updates."
    exit 0
fi

shopt -s nullglob
bank_files=("${BANKS_DIR}"/*.json)
shopt -u nullglob

if [ ${#bank_files[@]} -eq 0 ]; then
    echo "No .json bank files found in ${BANKS_DIR}. Skipping bank updates."
    exit 0
fi

for bank_file in "${bank_files[@]}"; do
    bank_id="$(basename "${bank_file}" .json)"
    echo "=== Processing configuration for bank: ${bank_id} ==="

    python3 -c "
import json, urllib.request, sys

bank_file = '${bank_file}'
api_url = '${API_URL}'
bank_id = '${bank_id}'
do_prune = '${PRUNE}' == 'true'

try:
    with open(bank_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
except Exception as e:
    print(f'  Error loading {bank_file}: {e}')
    sys.exit(1)

local_bank_cfg = {k: v for k, v in data.get('bank', {}).items() if v is not None}

# 1. Fetch current bank config to check if update is needed
config_url = f'{api_url}/v1/default/banks/{bank_id}/config'
needs_config_update = True

try:
    get_req = urllib.request.Request(config_url)
    with urllib.request.urlopen(get_req) as resp:
        remote_cfg = json.load(resp)
        # Compare local bank key-values with remote config
        differ = False
        for k, v in local_bank_cfg.items():
            if remote_cfg.get(k) != v:
                differ = True
                break
        if not differ:
            needs_config_update = False
except Exception:
    # Bank config might not exist yet, so we proceed with update
    needs_config_update = True

if needs_config_update and local_bank_cfg:
    payload = json.dumps({'updates': local_bank_cfg}).encode('utf-8')
    patch_req = urllib.request.Request(
        config_url,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='PATCH'
    )
    try:
        with urllib.request.urlopen(patch_req) as resp:
            print(f'  Config updated (status: {resp.status})')
    except Exception as e:
        print(f'  Config status error: {e}')
else:
    print('  Config unchanged, skipping patch.')

# 2. Fetch current Mental Models to diff against local models
mm_list_url = f'{api_url}/v1/default/banks/{bank_id}/mental-models'
remote_mms = {}

try:
    get_req = urllib.request.Request(mm_list_url)
    with urllib.request.urlopen(get_req) as resp:
        res_data = json.load(resp)
        items = res_data.get('items', res_data) if isinstance(res_data, dict) else res_data
        for item in items:
            if isinstance(item, dict) and item.get('id'):
                remote_mms[item['id']] = item
except Exception:
    pass

local_mms = data.get('mental_models', [])
expected_ids = set()

for mm in local_mms:
    mm_id = mm.get('id')
    if not mm_id:
        continue
    expected_ids.add(mm_id)
    remote_mm = remote_mms.get(mm_id)

    # Compare local vs remote fields
    needs_mm_update = True
    if remote_mm:
        # Key fields comparison
        match = True
        for key in ['name', 'source_query', 'max_tokens', 'trigger', 'tags']:
            if key in mm and remote_mm.get(key) != mm[key]:
                match = False
                break
        if match:
            needs_mm_update = False

    if needs_mm_update:
        payload = json.dumps(mm).encode('utf-8')
        if remote_mm:
            # PATCH existing
            req = urllib.request.Request(
                f'{mm_list_url}/{mm_id}',
                data=payload,
                headers={'Content-Type': 'application/json'},
                method='PATCH'
            )
            action = 'Updated'
        else:
            # POST new
            req = urllib.request.Request(
                mm_list_url,
                data=payload,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            action = 'Registered'

        try:
            with urllib.request.urlopen(req) as resp:
                print(f'  {action} mental model ({mm_id}): {resp.status}')
        except Exception as e:
            print(f'  Mental model error ({mm_id}): {e}')
    else:
        print(f'  Mental model ({mm_id}) unchanged, skipping update.')

# 3. Prune leftover mental models not present in bank JSON (only if --prune is enabled)
if do_prune:
    leftover_ids = set(remote_mms.keys()) - expected_ids
    for leftover_id in leftover_ids:
        del_req = urllib.request.Request(
            f'{mm_list_url}/{leftover_id}',
            method='DELETE'
        )
        try:
            with urllib.request.urlopen(del_req) as del_resp:
                print(f'  Pruned leftover mental model ({leftover_id}): {del_resp.status}')
        except Exception as del_e:
            print(f'  Error pruning mental model ({leftover_id}): {del_e}')
"
done

echo "=== Hindsight memory bank update check complete ==="
