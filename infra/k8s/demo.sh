#!/usr/bin/env bash
# Run the whole site on a throwaway kind cluster, built from this checkout.
#
#   infra/k8s/demo.sh up     build the images, start the cluster, migrate, deploy, smoke check, summary
#   infra/k8s/demo.sh down   delete the cluster and everything in it
#
# up reuses a cluster that already exists, with its Secrets and database data; run down first for
# a fresh start. A hosted runner always starts without one.
#
# Each step also runs alone: check, tools, images, cluster, secrets, migrate, deploy, smoke, summary,
# diagnose. .github/workflows/kubernetes.yml runs them one per workflow step.
# Needs docker with buildx, kind, kubectl, jq, yq, openssl, curl, git and python3.
# Every password and signing key is generated in the run, for demo use only, and lives only inside
# the cluster. Images are built locally and loaded straight into the cluster; no registry is used.
set -euo pipefail
cd "$(dirname "$0")/../.."

CLUSTER=${BT_K8S_CLUSTER:-beirut-time}
CONTEXT=kind-$CLUSTER
NAMESPACE=beirut-time
SITE=http://127.0.0.1:3000
WORK=${RUNNER_TEMP:-${TMPDIR:-/tmp}}/beirut-time-k8s
NAME_LABEL=app.kubernetes.io/name
COMPONENT_LABEL=app.kubernetes.io/component
mkdir -p "$WORK"

# The services are the Railway services; the databases are the ones the Postgres init script creates.
SERVICES=()
for file in infra/railway/*.json; do
  name=$(basename "$file" .json)
  [ "$name" = web ] || SERVICES+=("$name")
done
read -r -a DATABASES <<<"$(sed -n 's/^for service in \([a-z_ ]*\); do$/\1/p' infra/foundation/postgres-init.sh)"

k() { kubectl --context "$CONTEXT" --namespace "$NAMESPACE" "$@"; }

fail() {
  if [ -n "${GITHUB_ACTIONS:-}" ]; then echo "::error::$*"; else echo "error: $*" >&2; fi
  exit 1
}

group() { if [ -n "${GITHUB_ACTIONS:-}" ]; then echo "::group::$*"; else echo "== $*"; fi; }
endgroup() { if [ -n "${GITHUB_ACTIONS:-}" ]; then echo "::endgroup::"; fi; }

# Free space on / in KiB, recorded at each stage so the summary shows what the run used.
disk_mark() { printf '%s\t%s\n' "$1" "$(df -Pk / | awk 'NR == 2 {print $4}')" >>"$WORK/disk.tsv"; }

render() {
  kubectl kustomize infra/k8s >"$WORK/rendered.yaml"
  yq ea -o=json '[.]' "$WORK/rendered.yaml" >"$WORK/rendered.json"
}

compose_config() { infra/foundation/compose.sh config --format json >"$WORK/compose.json"; }

# manifests COMPONENT [NAME...]: the rendered objects of one component (optionally only some names),
# as one v1 List for kubectl apply.
manifests() {
  local component=$1
  shift
  jq --arg label "$COMPONENT_LABEL" --arg name "$NAME_LABEL" --arg component "$component" --args '
    {apiVersion: "v1", kind: "List", items: [.[]
      | select(.metadata.labels[$label] == $component)
      | select(($ARGS.positional | length) == 0
          or (.metadata.labels[$name] as $own | any($ARGS.positional[]; . == $own)))]}' "$@" <"$WORK/rendered.json"
}

images_in_manifests() {
  jq -r '[.[] | .spec.template.spec.containers[]?.image] | unique[]' "$WORK/rendered.json"
}

cluster_exists() { kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; }

# Services whose migration Job completed.
migrated_services() {
  k get jobs -l "$COMPONENT_LABEL=migration" -o json | jq -r --arg name "$NAME_LABEL" '.items[]
    | select(any(.status.conditions[]?; .type == "Complete" and .status == "True"))
    | .metadata.labels[$name]'
}

contains() {
  local wanted=$1 item
  shift
  for item in "$@"; do [ "$item" = "$wanted" ] && return 0; done
  return 1
}

# Compose, kubectl kustomize and yq produce the inputs (no cluster); check.py itself is standard Python.
step_check() {
  compose_config
  render
  yq -o=json '.' infra/k8s/kind.yaml >"$WORK/kind.json"
  python3 -I infra/k8s/check.py "$WORK/compose.json" "$WORK/rendered.json" "$WORK/kind.json"
}

step_tools() {
  local tool missing=()
  for tool in docker kind kubectl jq yq openssl curl git python3; do
    command -v "$tool" >/dev/null || missing+=("$tool")
  done
  [ ${#missing[@]} -eq 0 ] || fail "missing tools: ${missing[*]}"
  docker version --format 'docker {{.Server.Version}}'
  docker buildx version
  kind version
  kubectl version --client
  yq --version
  jq --version
  python3 --version
  nproc 2>/dev/null || true
  free -h 2>/dev/null || true
  df -h /
  : >"$WORK/disk.tsv"
  disk_mark 'start of run'
}

step_images() {
  [ -s "$WORK/compose.json" ] || compose_config
  local revision plan="$WORK/bake.json" image
  revision=$(git rev-parse HEAD)
  # The Compose build: context, Dockerfile and build arguments are read from Compose as they are
  # (check.py holds the context and Dockerfile to Railway's and allows no other build setting).
  jq --arg revision "$revision" --args '
    .services as $services
    | {group: {default: {targets: $ARGS.positional}},
       target: (reduce $ARGS.positional[] as $name ({}; .[$name] = {
         context: $services[$name].build.context,
         dockerfile: $services[$name].build.dockerfile,
         args: ($services[$name].build.args // {}),
         tags: ["beirut-time/\($name):local"],
         labels: {"org.opencontainers.image.revision": $revision}}))}' \
    "${SERVICES[@]}" web <"$WORK/compose.json" >"$plan"
  BUILDX_NO_DEFAULT_ATTESTATIONS=1 docker buildx bake --file "$plan" --progress plain
  [ -s "$WORK/rendered.json" ] || render
  for image in $(images_in_manifests); do
    case "$image" in beirut-time/*) ;; *) docker pull --quiet "$image" ;; esac
  done
  disk_mark 'images built'
}

step_cluster() {
  local images=() image revision
  disk_mark 'before cluster'
  if cluster_exists; then
    echo "cluster $CLUSTER already exists; reusing it"
  else
    kind create cluster --name "$CLUSTER" --config infra/k8s/kind.yaml --wait 120s
  fi
  [ -s "$WORK/rendered.json" ] || render
  while IFS= read -r image; do images+=("$image"); done < <(images_in_manifests)
  kind load docker-image --name "$CLUSTER" "${images[@]}"
  : >"$WORK/images.tsv"
  for image in "${images[@]}"; do
    revision=$(docker image inspect "$image" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
    [ "$revision" != '<no value>' ] || revision=''
    printf '%s\t%s\t%s\n' "$image" "$(docker image inspect "$image" --format '{{.Id}}')" "$revision" >>"$WORK/images.tsv"
  done
  kubectl --context "$CONTEXT" apply -f infra/k8s/namespace.yaml
  disk_mark 'images loaded'
}

# Pipe a kubectl create --dry-run object through this to label it and apply it.
apply_labelled() {
  k label --local -f - -o yaml "app.kubernetes.io/part-of=$NAMESPACE" | k apply -f -
}

SECRET_DIR=''
SECRET_FILES=()
forget_secret_files() {
  [ -n "$SECRET_DIR" ] || return 0
  rm -f "${SECRET_FILES[@]}"
  rmdir "$SECRET_DIR"
  SECRET_DIR=''
}

step_secrets() {
  local database key
  [ ${#DATABASES[@]} -gt 0 ] || fail "no databases found in infra/foundation/postgres-init.sh"
  SECRET_DIR=$(mktemp -d "$WORK/secrets.XXXXXX")
  SECRET_FILES=("$SECRET_DIR/passwords.env" "$SECRET_DIR/user-private-key" "$SECRET_DIR/user-public-key"
                "$SECRET_DIR/service-private-key" "$SECRET_DIR/service-public-key")
  # The generated values exist on disk only for this step, readable by this user only.
  trap forget_secret_files EXIT
  (
    set -euo pipefail
    umask 077
    dir=$SECRET_DIR
    if ! k get secret database-passwords >/dev/null 2>&1; then
      {
        echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)"
        for database in "${DATABASES[@]}"; do
          key=$(printf '%s' "$database" | tr '[:lower:]' '[:upper:]')
          echo "${key}_DB_PASSWORD=$(openssl rand -hex 24)"
          echo "${key}_OWNER_PASSWORD=$(openssl rand -hex 24)"
        done
      } >"$dir/passwords.env"
      k create secret generic database-passwords --from-env-file="$dir/passwords.env" \
        --dry-run=client -o yaml | apply_labelled
    else
      echo "Secret database-passwords already exists; keeping it"
    fi
    if ! k get secret signing-keys >/dev/null 2>&1; then
      # One pair signs user sessions (Identity); the other signs service calls and events.
      for key in user service; do
        openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$dir/$key-private-key" 2>/dev/null
        openssl pkey -in "$dir/$key-private-key" -pubout -out "$dir/$key-public-key"
      done
      k create secret generic signing-keys \
        --from-file=user-private-key="$dir/user-private-key" --from-file=user-public-key="$dir/user-public-key" \
        --from-file=service-private-key="$dir/service-private-key" \
        --from-file=service-public-key="$dir/service-public-key" \
        --dry-run=client -o yaml | apply_labelled
    else
      echo "Secret signing-keys already exists; keeping it"
    fi
  )
  forget_secret_files
  trap - EXIT
  k create configmap postgres-init --from-file=01-databases.sh=infra/foundation/postgres-init.sh \
    --dry-run=client -o yaml | apply_labelled
}

step_migrate() {
  local deadline=$((SECONDS + 360)) pending name failed=() migrated=()
  [ -s "$WORK/rendered.json" ] || render
  manifests database | k apply -f -
  k rollout status deployment/postgres --timeout=180s
  # Job templates cannot change in place, so each run starts its migrations afresh.
  k delete jobs -l "$COMPONENT_LABEL=migration" --ignore-not-found --cascade=foreground --wait=true
  manifests migration | k apply -f -
  while :; do
    pending=$(k get jobs -l "$COMPONENT_LABEL=migration" -o json | jq -r '[.items[]
      | select(any(.status.conditions[]?; (.type == "Complete" or .type == "Failed") and .status == "True") | not)
      | .metadata.name] | join(" ")')
    [ -n "$pending" ] && [ "$SECONDS" -lt "$deadline" ] || break
    sleep 3
  done
  k get jobs -l "$COMPONENT_LABEL=migration" -o wide
  while IFS= read -r name; do migrated+=("$name"); done < <(migrated_services)
  for name in "${SERVICES[@]}"; do
    if ! contains "$name" ${migrated[@]+"${migrated[@]}"}; then
      failed+=("$name")
      group "Migration log: $name"
      k logs "job/$name-migrate" --all-containers --tail=200 || true
      endgroup
    fi
  done
  [ ${#failed[@]} -eq 0 ] || fail "migrations did not complete for: ${failed[*]}"
}

step_deploy() {
  local deadline=$((SECONDS + 300)) name migrated=() ready=() skipped=() waiting commit
  [ -s "$WORK/rendered.json" ] || render
  while IFS= read -r name; do migrated+=("$name"); done < <(migrated_services)
  # A service starts only after its own migration completed, as Railway's pre-deploy command requires.
  for name in "${SERVICES[@]}"; do
    if contains "$name" ${migrated[@]+"${migrated[@]}"}; then ready+=("$name"); else skipped+=("$name"); fi
  done
  if [ ${#ready[@]} -gt 0 ]; then manifests service "${ready[@]}" | k apply -f -; fi
  manifests site | k apply -f -
  commit=${BT_K8S_HEAD:-$(git rev-parse HEAD)}
  kubectl --context "$CONTEXT" annotate namespace "$NAMESPACE" --overwrite "beirut-time/commit=$commit" \
    "beirut-time/built-from=$(git rev-parse HEAD)"
  while :; do
    waiting=$(k get deployments -l "$COMPONENT_LABEL in (service,site)" -o json | jq -r '[.items[]
      | select((.status.observedGeneration // 0) < .metadata.generation
          or (.status.updatedReplicas // 0) < .spec.replicas
          or (.status.readyReplicas // 0) < .spec.replicas
          or (.status.unavailableReplicas // 0) > 0)
      | .metadata.name] | join(" ")')
    [ -n "$waiting" ] && [ "$SECONDS" -lt "$deadline" ] || break
    sleep 3
  done
  k get deployments -o wide
  k get pods -o wide
  [ -z "$waiting" ] || echo "not ready after 300 s: $waiting"
  [ ${#skipped[@]} -eq 0 ] || echo "not deployed because the migration did not complete: ${skipped[*]}"
  [ -z "$waiting" ] && [ ${#skipped[@]} -eq 0 ] || fail "not running: ${skipped[*]:-} ${waiting}"
}

# Runs inside the site's pod: proves the site reaches each service at its in-cluster address.
# shellcheck disable=SC2016 # JavaScript, not shell: the ${...} belong to its template string.
HEALTH_JS='
const [url, service, want] = process.argv.slice(1);
fetch(url, { signal: AbortSignal.timeout(5000) })
  .then(async (response) => {
    const text = await response.text();
    let body = null;
    try { body = JSON.parse(text); } catch {}
    if (response.status !== 200 || !body || body.status !== want || body.service !== service) {
      throw new Error(`${response.status} ${text.slice(0, 200)}`);
    }
  })
  .catch((error) => { console.error(error.message); process.exit(1); });
'

# Reads the sign-in page the way a browser does (the tokenizer of the HTML standard, with the rules
# of its tree builder that make inputs inert) and prints why the check fails, or nothing. The page
# must be served as HTML, in bytes that read the same in every encoding a browser may use for it,
# with no Content-Disposition or Content-Encoding header and no Transfer-Encoding but chunked, and
# must not start like a feed.
# Only whole attributes of input start tags count: names in any case, values exactly as written,
# with no character reference decoded. Nothing counts inside a comment, a quoted value, an element
# whose content a browser reads as text, a template, svg or math, and no hidden input counts. Where
# the rest of the page cannot be read for certain, the scan stops there. The password input must
# carry its own autocomplete. This reads static markup only: it does not show that the fields are
# visible or usable. It does not use html.parser, whose rules differ between releases.
SIGN_IN_PY='
import json
import re
import sys

SPACE = "\t\n\f "
NAME_END = SPACE + "/>"
ATTRIBUTE_END = SPACE + "/>="
VALUE_END = SPACE + ">"
HTTP_SPACE = "\t\n\r "
CASE = re.ASCII | re.IGNORECASE
LETTER = re.compile("[A-Za-z]")
LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
COMMENT_END = re.compile("--!?>")
# The labels of UTF-8 in the Encoding standard.
UTF8 = ("unicode-1-1-utf-8", "unicode11utf8", "unicode20utf8", "utf-8", "utf8", "x-unicode20utf8")
# With no charset, only these bytes read the same in each encoding a browser may pick, and only if
# no meta or xml declaration names another.
PLAIN_BYTES = re.compile(b"[\t\n\f\r -~]*")
DECLARATION = re.compile(b"<meta|<[?]xml", re.IGNORECASE)
# The whitespace bytes of the MIME Sniffing standard, and the start of a tag that its rules for
# telling a feed from HTML read as a feed, here in any case and without the rdf:RDF namespace test.
SNIFF_SPACE = "\t\n\f\r "
FEED = re.compile("<(?:rss|feed|rdf:rdf)", CASE)
# Elements whose content is text up to their first end tag, in any case. Script text has its own
# rules below, and plaintext runs to the end of the page.
TEXT_END = {name: re.compile("</" + name + "[\t\n\f />]", CASE) for name in (
    "style", "textarea", "title", "xmp", "iframe", "noembed", "noframes", "noscript")}
# Script text can hide a </script>: after <!-- and then <script>, the next </script> does not end it.
SCRIPT_DATA = re.compile("<!--|</script[\t\n\f />]", CASE)
SCRIPT_ESCAPED = re.compile("-->|</script[\t\n\f />]|<script[\t\n\f />]", CASE)
SCRIPT_DOUBLE = re.compile("-->|</script[\t\n\f />]", CASE)
# Start tags that stop the scan inside svg or math: the integration points, whose content a browser
# reads as HTML again, the elements that end the svg or math early, and frameset.
FOREIGN_STOP = frozenset((
    "foreignobject", "desc", "title", "mi", "mo", "mn", "ms", "mtext", "annotation-xml",
    "b", "big", "blockquote", "body", "br", "center", "code", "dd", "div", "dl", "dt", "em", "embed",
    "font", "h1", "h2", "h3", "h4", "h5", "h6", "head", "hr", "i", "img", "li", "listing", "menu",
    "meta", "nobr", "ol", "p", "pre", "ruby", "s", "small", "span", "strike", "strong", "sub", "sup",
    "table", "tt", "u", "ul", "var", "frameset"))
# Start tags that stop the scan inside select, where older browsers ignore them and so read their
# content as markup, not as text.
SELECT_STOP = frozenset((
    "style", "xmp", "iframe", "noembed", "noframes", "noscript", "title", "svg", "math"))
# Start tags that stop the scan inside noscript, whose content a browser with scripting off reads
# as markup: each would change how what follows is read.
NOSCRIPT_STOP = frozenset(TEXT_END) | frozenset((
    "script", "plaintext", "template", "svg", "math", "select", "frameset"))


def sniff_end(text):
    """Where the rules of the MIME Sniffing standard for telling a feed from HTML stop reading
    text, which starts after any UTF-8 byte order mark. They skip whitespace, then after each <
    skip a comment to the next -->, a <! to the next > or a <? to the next ?>, and decide at the
    first other byte or tag; an unended block is read to the end. Any rss, feed or rdf:RDF tag
    that starts before this index fails the check, so a sniffer that ends a block sooner is
    covered too."""
    s, n = 0, len(text)
    while True:
        while s < n and text[s] in SNIFF_SPACE:
            s += 1
        if not text.startswith("<", s):
            return s  # text, or the end of the page
        for opening, closing in (("<!--", "-->"), ("<!", ">"), ("<?", "?>")):
            if text.startswith(opening, s):
                end = text.find(closing, s + len(opening))
                if end < 0:
                    return n
                s = end + len(closing)
                break
        else:
            return s + 1  # the first tag that is not skipped


def page_text(path, served):
    """The page as text and no reason, or None and the reason it is not read. It must be served as
    HTML, with one content type, no Content-Disposition, no content coding and no transfer coding
    but chunked, in bytes that read the same in every encoding a browser may use, and must not
    start like a feed."""
    headers = {}
    try:
        for name, values in json.loads(served).items():
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                raise ValueError(name)
            headers.setdefault(name.translate(LOWER), []).extend(values)  # names in any case
    except (ValueError, AttributeError):
        headers = {}
    types = headers.get("content-type", [])
    if not types:
        return None, "served with no content type, not as HTML"
    if len(types) > 1 or "," in types[0]:
        return None, "served with more than one content type, not certain to be HTML"
    essence, _, parameters = types[0].strip(HTTP_SPACE).partition(";")
    essence = essence.rstrip(HTTP_SPACE).translate(LOWER)
    if essence != "text/html":
        return None, "served as %s, not as HTML" % (re.sub("[^ -~]", "?", essence) or "an empty type")
    if "content-disposition" in headers:
        return None, "served with a Content-Disposition header, so a browser may save it instead"
    # curl asks for no compression and saves the bytes as sent, while a browser decodes them first.
    if "content-encoding" in headers:
        return None, "served with a Content-Encoding header, so a browser may decode it first"
    codings = [coding.strip(HTTP_SPACE).translate(LOWER)
               for value in headers.get("transfer-encoding", []) for coding in value.split(",")]
    if any(coding != "chunked" for coding in codings):
        return None, "served with a transfer coding other than chunked, so a browser may decode it"
    labels = []
    for parameter in parameters.split(";"):
        key, equals, label = parameter.lstrip(HTTP_SPACE).partition("=")
        if equals and key.translate(LOWER) == "charset":
            labels.append(label.rstrip(HTTP_SPACE).translate(LOWER))
    with open(path, "rb") as page:
        body = page.read()
    if body.startswith(b"\xef\xbb\xbf"):
        body = body[3:]  # a UTF-8 byte order mark outranks any charset
    elif body.startswith((b"\xfe\xff", b"\xff\xfe")) or "\"" in parameters:
        body = None  # UTF-16, or a quoted parameter, read by rules this check does not keep
    elif labels:
        body = body if labels[0] in UTF8 else None  # the first charset is the one that counts
    elif not PLAIN_BYTES.fullmatch(body) or DECLARATION.search(body):
        body = None
    try:
        text = None if body is None else body.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if text is None:
        return None, "served as HTML, but not certain to read as UTF-8"
    feed = FEED.search(text)
    if feed and feed.start() < sniff_end(text):
        return None, "served as HTML, but it starts like a feed, which a browser may show instead"
    return text, ""


def read_tag(page, i):
    """The tag whose name starts at i: its name, its attributes, whether a / right before its >
    closes it, and the index just after it, or None if the page ends inside the tag. Names are
    lowered in ASCII only, as a browser does. Values are kept as written, with no character
    reference decoded, so a value that holds one never equals a word this check looks for."""
    n = len(page)
    j = i
    while j < n and page[j] not in NAME_END:
        j += 1
    name = page[i:j].translate(LOWER)
    attributes = {}
    closing = False
    while j < n:
        if page[j] == ">":
            return name, attributes, closing, j + 1
        closing = page[j] == "/"
        if closing or page[j] in SPACE:
            j += 1
        else:
            k = j + 1
            while k < n and page[k] not in ATTRIBUTE_END:
                k += 1
            key = page[j:k].translate(LOWER)
            while k < n and page[k] in SPACE:
                k += 1
            value = ""
            if k < n and page[k] == "=":
                k += 1
                while k < n and page[k] in SPACE:
                    k += 1
                if k < n and page[k] in "\"\x27":
                    close = page.find(page[k], k + 1)
                    if close < 0:
                        return None
                    value, k = page[k + 1:close], close + 1
                else:
                    start = k
                    while k < n and page[k] not in VALUE_END:
                        k += 1
                    value = page[start:k]
            attributes.setdefault(key, value)  # a repeated name keeps its first value
            j = k
    return None


def comment_end(page, k):
    """The index just after a comment whose text starts at k, or -1 if it runs to the end."""
    if page.startswith(">", k):
        return k + 1
    if page.startswith("->", k):
        return k + 2
    end = COMMENT_END.search(page, k)
    return end.end() if end else -1


def markup(page, i, foreign):
    """The index just after the comment, doctype, bogus comment or CDATA section at the < at i, or
    -1 if it runs to the end. Only inside svg or math does <![CDATA[ start text, up to ]]>."""
    if page.startswith("<!--", i):
        return comment_end(page, i + 4)
    if foreign and page.startswith("<![CDATA[", i):
        end = page.find("]]>", i + 9)
        return end + 3 if end >= 0 else -1
    if page.startswith("</>", i):
        return i + 3
    end = page.find(">", i + 2)  # a doctype or a bogus comment, up to the next >
    return end + 1 if end >= 0 else -1


def script_end(page, i):
    """The index of the end tag of a script whose text starts at i, or -1 if it runs to the end."""
    state = SCRIPT_DATA
    while True:
        found = state.search(page, i)
        if not found:
            return -1
        token = found.group().lower()
        if token == "<!--":
            state, i = SCRIPT_ESCAPED, found.start() + 2  # the -- of <!-- can begin -->
        elif token == "-->":
            state, i = SCRIPT_DATA, found.end()
        elif token.startswith("<script"):
            state, i = SCRIPT_DOUBLE, found.end()
        elif state is SCRIPT_DOUBLE:
            state, i = SCRIPT_ESCAPED, found.end()
        else:
            return found.start()


def foreign_end(page, i, root):
    """The index just after the end tag that closes the svg or math element whose content starts
    at i, or -1 if it runs to the end or the scan cannot be sure where it ends. Inside, a browser
    reads every tag as a plain tag, with no text elements, and an end tag closes the nearest open
    element of its name; one that matches none may close the svg or math, so the scan stops."""
    names = [root]
    i = page.find("<", i)
    while i >= 0:
        if LETTER.match(page, i + 1):
            tag = read_tag(page, i + 1)
            if tag is None or tag[0] in FOREIGN_STOP:
                return -1
            if not tag[2]:
                names.append(tag[0])
            i = tag[3]
        elif page.startswith("</", i) and LETTER.match(page, i + 2):
            tag = read_tag(page, i + 2)
            if tag is None or tag[0] not in names:
                return -1  # this also stops at </br> and </p>, which end the svg or math early
            while names.pop() != tag[0]:
                pass
            if not names:
                return tag[3]
            i = tag[3]
        elif page.startswith(("<!", "</", "<?"), i):
            i = markup(page, i, True)
        else:
            i += 1  # a < that opens nothing is text
        if i < 0:
            return -1
        i = page.find("<", i)
    return -1


def scripting_off_alike(page, i, end):
    """Whether a browser with scripting off, which reads the noscript text from i to end as markup,
    still reads what follows as the scan does: the text holds only whole tags that end before end,
    no comment, doctype or bogus comment, and no start tag that changes how later markup is read."""
    i = page.find("<", i, end)
    while i >= 0:
        start = LETTER.match(page, i + 1)
        if start or page.startswith("</", i) and LETTER.match(page, i + 2):
            tag = read_tag(page, i + (1 if start else 2))
            if tag is None or tag[3] > end or start and tag[0] in NOSCRIPT_STOP:
                return False
            i = tag[3]
        elif page.startswith(("<!", "</", "<?"), i):
            return False
        else:
            i += 1  # a < that opens nothing is text
        i = page.find("<", i, end)
    return True


def inputs(page):
    """The attributes of every input start tag that a browser makes a field of: outside comments,
    text, templates, svg and math, and not hidden. Where the rest of the page cannot be read for
    certain, the scan stops, and nothing after counts."""
    page = page.replace("\r\n", "\n").replace("\r", "\n")
    controls = []
    levels = [0]  # the select elements open in the page, then in each open template
    i = page.find("<")
    while i >= 0:
        if LETTER.match(page, i + 1):
            tag = read_tag(page, i + 1)
            if tag is None:
                break
            name, attributes, closing, i = tag
            if name in ("plaintext", "frameset") or any(levels) and name in SELECT_STOP:
                break
            if name == "input":
                kind = attributes.get("type")
                hidden = kind is not None and ("&" in kind or kind.translate(LOWER) == "hidden")
                if len(levels) == 1 and not hidden:
                    controls.append(attributes)
            elif name == "template":
                levels.append(0)
            elif name == "select":
                levels[-1] += 1
            elif name in ("svg", "math"):
                if not closing:
                    i = foreign_end(page, i, name)
            elif name == "script":
                i = script_end(page, i)
            elif name in TEXT_END:
                end = TEXT_END[name].search(page, i)
                if end is None or name == "noscript" and not scripting_off_alike(page, i, end.start()):
                    break
                i = end.start()
        elif page.startswith("</", i) and LETTER.match(page, i + 2):
            tag = read_tag(page, i + 2)
            if tag is None:
                break
            name, i = tag[0], tag[3]
            if name == "template" and len(levels) > 1:
                levels.pop()
            elif name == "select" and levels[-1]:
                levels[-1] -= 1
        elif page.startswith(("<!", "</", "<?"), i):
            i = markup(page, i, False)
        else:
            i += 1  # a < that opens nothing is text
        if i < 0:
            break
        i = page.find("<", i)
    return controls


text, problem = page_text(sys.argv[1], sys.argv[2])
if text is not None:
    controls = inputs(text)
    password = [c for c in controls if c.get("name") == "password"]
    checks = [
        ("name", "email", any(c.get("name") == "email" for c in controls)),
        ("name", "password", bool(password)),
        ("autocomplete", "current-password",
         any(c.get("autocomplete") == "current-password" for c in password)),
    ]
    missing = "".join(" %s=\"%s\"" % (name, value) for name, value, present in checks if not present)
    problem = "missing:" + missing if missing else ""
print(problem, end="")
'

step_smoke() {
  local failures=() name endpoint want locale theme page="$WORK/page.html" redirect='' status problem served
  # A temporary or permanent redirect to /en on a loopback address of this same site, nowhere else.
  local to_en='^30[78] http://(127\.0\.0\.1|localhost|\[::1\]):3000/en/?$'
  : >"$WORK/smoke.txt"
  result() {
    local line="ok: $2"
    if [ "$1" != ok ]; then line="FAILED: $2"; failures+=("$2"); fi
    echo "$line" | tee -a "$WORK/smoke.txt"
  }
  fetch() { curl --fail --silent --show-error --max-time 20 --retry 3 --retry-delay 2 --retry-connrefused "$@"; }
  has() { grep -qF -- "$1" "$page"; }

  for name in "${SERVICES[@]}"; do
    for endpoint in live ready; do
      want=ok
      [ "$endpoint" = ready ] && want=ready
      if k exec deploy/web -c web -- node -e "$HEALTH_JS" "http://$name:8000/health/$endpoint" "$name" "$want"; then
        result ok "$name /health/$endpoint from the site's pod"
      else
        result failed "$name /health/$endpoint from the site's pod"
      fi
    done
  done

  if fetch "$SITE/api/health" | jq -e '.status == "ok" and .service == "web"' >/dev/null; then
    result ok "site /api/health"
  else
    result failed "site /api/health"
  fi

  # The site redirects / to the visitor's locale, /en by default. The redirect is checked before
  # anything follows it, and the page is then fetched from this site's own address, never the Location.
  if redirect=$(fetch --output /dev/null --write-out '%{http_code} %{redirect_url}' "$SITE/") \
      && [[ $redirect =~ $to_en ]] && fetch --output "$page" "$SITE/en" && has 'lang="en"' && has 'Beirut Time'; then
    result ok "home page / redirects to /en on this machine ($redirect)"
  else
    result failed "home page / redirects to /en on this machine (got ${redirect:-nothing})"
  fi

  for locale in en ar; do
    for theme in light dark; do
      if fetch --header "Cookie: bt-theme=$theme" --output "$page" "$SITE/$locale" \
          && has 'Beirut Time' && has 'main-content' && has "data-theme=\"$theme\"" && has "lang=\"$locale\""; then
        result ok "home page /$locale in the $theme theme"
      else
        result failed "home page /$locale in the $theme theme"
      fi
    done
  done

  # The sign-in form's controls, read as a browser reads them (SIGN_IN_PY): HTML attribute names
  # ignore case, and React writes them as the source spells them (autoComplete), but the values
  # must match exactly, because they are the form's keys, which the sign-in request sends unchanged.
  # Only a 200 response served as HTML counts, with its response headers (header_json) read for the
  # type, codings and disposition. Redirects are not followed, so a redirect fails here even if its
  # own body holds the form.
  # A failure names the HTTP status and every attribute that was missing, or why the page was not read.
  if ! served=$(fetch --output "$page" --write-out '%{http_code} %{header_json}' "$SITE/en/account"); then
    problem='missing: the page'
  elif [ "${served%% *}" != 200 ]; then
    problem='not the page itself'
  else
    problem=$(python3 -I -c "$SIGN_IN_PY" "$page" "${served#* }")
  fi
  status=${served%% *}
  if [ -z "$problem" ]; then
    result ok "sign-in page /en/account shows the email and password form"
  else
    result failed "sign-in page /en/account shows the email and password form (HTTP ${status:-none}, $problem)"
  fi

  # Exactly the Railway services, each once and each ready.
  if fetch "$SITE/api/web/v1/status" | jq -e --args \
      '([.services[].service] | sort) == ($ARGS.positional | sort) and all(.services[]; .status == "ready")' \
      "${SERVICES[@]}" >/dev/null; then
    result ok "site status lists exactly the ${#SERVICES[@]} services, all ready"
  else
    result failed "site status lists exactly the ${#SERVICES[@]} services, all ready"
  fi
  rm -f "$page"
  [ ${#failures[@]} -eq 0 ] || fail "${#failures[@]} smoke check(s) failed"
}

step_summary() {
  local built head commit image id revision
  built=$(git rev-parse HEAD)
  head=${BT_K8S_HEAD:-$built}
  echo '## Kubernetes demo'
  echo
  if [ "$head" = "$built" ]; then
    echo "Commit: \`$built\`"
  else
    echo "Commit: \`$head\` (built and deployed as the merge commit \`$built\`)"
  fi
  echo
  if cluster_exists; then
    commit=$(kubectl --context "$CONTEXT" get namespace "$NAMESPACE" -o json 2>/dev/null \
      | jq -r '.metadata.annotations["beirut-time/commit"] // empty' || true)
    echo "Cluster: kind \`$CLUSTER\`, $(kind version | awk '{print $2}'), Kubernetes \
$(kubectl --context "$CONTEXT" version -o json 2>/dev/null | jq -r '.serverVersion.gitVersion // "unknown"')."
    echo "Deployed commit recorded on the namespace: \`${commit:-none}\`."
    echo "The site was served at $SITE inside the runner only; the cluster is deleted with the runner."
    echo
    echo '| Running service | Ready | In-cluster address | Image |'
    echo '| --- | --- | --- | --- |'
    k get deployments -o json | jq -r '.items[] | "| \(.metadata.name) | \(.status.readyReplicas // 0)/\(.spec.replicas) | \(
      if .metadata.name == "postgres" then "postgres:5432" else "http://\(.metadata.name):\(.spec.template.spec.containers[0].ports[0].containerPort)" end
      ) | `\(.spec.template.spec.containers[0].image)` |"' 2>/dev/null || echo '| (could not list deployments) | | | |'
    echo
    echo '| Migration | Result |'
    echo '| --- | --- |'
    k get jobs -o json | jq -r '.items[] | "| \(.metadata.name) | \(
      [.status.conditions[]? | select(.status == "True") | .type] | if length == 0 then "running" else join(", ") end) |"' \
      2>/dev/null || echo '| (could not list jobs) | |'
  else
    echo "No cluster \`$CLUSTER\` is running, so nothing was deployed."
  fi
  if [ -s "$WORK/images.tsv" ]; then
    echo
    echo '| Image | Image id | Built from |'
    echo '| --- | --- | --- |'
    while IFS=$'\t' read -r image id revision; do
      echo "| \`$image\` | \`${id#sha256:}\` | \`${revision:-external}\` |"
    done <"$WORK/images.tsv"
  fi
  if [ -s "$WORK/disk.tsv" ]; then
    disk_mark 'end of run'
    echo
    echo '| Stage | Free disk on / |'
    echo '| --- | --- |'
    awk -F '\t' '{ printf "| %s | %.1f GiB |\n", $1, $2 / 1048576 }
      NR == 1 || $2 < low { low = $2 } NR == 1 { first = $2 } { last = $2 }
      END { printf "\nMost disk the run used at once: %.1f GiB; still in use at the end: %.1f GiB.\n",
            (first - low) / 1048576, (first - last) / 1048576 }' "$WORK/disk.tsv"
  fi
  if [ -s "$WORK/smoke.txt" ]; then
    echo
    echo '### Smoke check'
    echo
    sed 's/^/- /' "$WORK/smoke.txt"
  fi
}

step_diagnose() {
  local pod
  group 'Objects'
  k get all,jobs,configmaps -o wide || true
  endgroup
  group 'Events'
  k get events --sort-by=.lastTimestamp || true
  endgroup
  group 'Node capacity'
  kubectl --context "$CONTEXT" describe nodes | sed -n '/^Capacity:/,/^Events:/p' || true
  endgroup
  for pod in $(k get pods -o json | jq -r '.items[] | select(.status.phase != "Succeeded")
      | select(any(.status.conditions[]?; .type == "Ready" and .status == "True") | not) | .metadata.name'); do
    group "Pod $pod"
    k describe pod "$pod" || true
    k logs "$pod" --all-containers --tail=200 || true
    k logs "$pod" --all-containers --tail=200 --previous 2>/dev/null || true
    endgroup
  done
}

step_down() {
  if cluster_exists; then kind delete cluster --name "$CLUSTER"; else echo "no cluster $CLUSTER"; fi
}

step_up() {
  step_tools
  step_check
  step_images
  step_cluster
  step_secrets
  step_migrate
  step_deploy
  step_smoke
  step_summary
  echo "The site is running at $SITE; stop it with infra/k8s/demo.sh down."
}

case "${1:-}" in
  check | tools | images | cluster | secrets | migrate | deploy | smoke | summary | diagnose | up | down) "step_$1" ;;
  *) sed -n '2,14p' "$0" >&2; exit 2 ;;
esac
