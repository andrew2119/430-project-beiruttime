"""Run the connected walkthrough for the smokes part, with a scripted possession review.

NOT PHYSICAL INSPECTION. Test only: CI runs it on its own disposable stack, it is never part
of a product or deploy path, and it uses no credentials or secrets.

Usage: python .github/ci/walkthrough.py <run-dir> <origin>

It runs the tree's own walkthrough (tests/integration/sprint-1/connected_walkthrough.py, every
phase, native backend) and changes one thing. When publication stops because the private demo
drafts wait for a possession review, it drives the walkthrough's own five review actions for
each draft (challenge, submit, assign, inspect, decide) and publishes again. The inputs come
from the scripted actor, scripted-review/n05-scripted-actor.py, over the file protocol in
scripted-review/listing_coordinator.py:
  - the frozen test icon, web/public/icons/bt-192.png, as the photo;
  - a fixed approved verdict;
  - the operator as reviewer, with no credentials file.
That exercises the review routes only. Nobody inspects a watch, so it proves nothing about
possession; a real person's review stays unproven.

A tree whose publication passes without a review runs unchanged, and nothing scripted runs.
Any other publication failure, a real outage included, fails exactly as it would without this
driver. The review is bounded: at most 4 publication attempts, 15 review calls and 300 seconds.
"""
import base64
import importlib.util
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REVIEW = HERE / 'scripted-review'
WALK = ROOT / 'tests/integration/sprint-1/connected_walkthrough.py'
ACTOR = REVIEW / 'n05-scripted-actor.py'
# The actor is a fixed file; any change to it must be reviewed again, so its bytes are pinned.
ACTOR_SHA256 = '83905ef4a28119d94ad45f366d52bf300e2ab7bd36e4a06bce84c323ce134633'
LABEL = 'not physical inspection'
TAG = 'N05-SCRIPTED-REVIEW'
IMPORTS, CALLS = 4, 15

sys.path.insert(0, str(REVIEW))
import listing_coordinator as coordinator  # noqa: E402
import listing_evidence as codec  # noqa: E402
import proof_types as proof  # noqa: E402

# The one publication failure the review answers: the child process held for a pending review.
HOLD = codec.encode(dict(exit_code=1, timed_out=False, exception_type='PublicationUnavailable',
                         failure_category=coordinator.PENDING['category'],
                         http_status=coordinator.PENDING['http_status'], upstream=coordinator.PENDING['upstream']))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def attempt(walk, publish, entry):
    """One publication attempt: None once it passes, its error when it stopped at exactly the review hold.

    Any other failure, a real outage included, is raised unchanged.
    """
    proof.require(entry['imports'] < IMPORTS, 'scripted publication exceeded its attempt bound')
    entry['imports'] += 1
    before = set(walk.run_dir.glob('publication-child-*.json'))
    try:
        publish('publication')
        return None
    except RuntimeError as error:
        records = sorted(set(walk.run_dir.glob('publication-child-*.json')) - before)
        try:
            held = len(records) == 1 and codec.encode(proof.strict_json(proof.private_bytes(records[0], 4096))) == HOLD
        except (OSError, ValueError, TypeError):
            held = False
        if not held:
            raise
        return error


def review(walk, actor, reference, end, entry):
    """The walkthrough's own five review actions for one draft, fed by the scripted actor's inputs."""
    folder = walk.run_dir / coordinator.INPUTS
    files = {key: walk.run_dir / f'scripted-review-{reference}-{key}.private'
             for key in ('challenge', 'submit', 'inspection', 'verdict')}
    proof.require(all(coordinator.absent(path) for path in files.values()),
                  'listing review output existed before the current action')

    def act(action, file):
        proof.require(entry['review_calls'] < CALLS and time.monotonic() < end,
                      'scripted listing review exceeded its call or time bound')
        entry['review_calls'] += 1
        walk.listing_review(reference, action, file)  # the operator reviews: no credentials file

    try:
        act('challenge', files['challenge'])
        state = walk.state['listing_proofs'][reference]
        photo = coordinator.await_input(folder, reference, 'photo', dict(
            reference=reference, binding=state['binding'], after='challenge'), end, coordinator.PHOTO_ENVELOPE_LIMIT)
        proof.require(type(photo) is dict and set(photo) == {'pngBase64'} and type(photo['pngBase64']) is str,
                      'scripted photo input must be the test image alone, with no reviewer credentials')
        raw = base64.b64decode(photo['pngBase64'], validate=True)
        proof.require(raw.startswith(proof.PNG) and proof.digest(raw) == actor.PHOTO_SHA,
                      'scripted photo input is not the frozen test icon')
        proof.private_write(files['submit'], raw)
        act('submit', files['submit'])
        act('assign', None)
        act('inspect', files['inspection'])
        proof.require(proof.private_bytes(files['inspection'], coordinator.INPUT_LIMIT) == raw,
                      'the assigned reviewer did not read the exact submitted test icon')
        verdict = coordinator.await_input(folder, reference, 'verdict', dict(
            reference=reference, binding=state['binding'], after='inspect', inspection=state['inspection'],
            photo_sha256=proof.digest(raw)), end, coordinator.VERDICT_ENVELOPE_LIMIT)
        proof.require(codec.encode(verdict) == codec.encode(actor.VERDICT),
                      'scripted verdict is not the fixed approved test verdict')
        proof.private_write(files['verdict'], codec.encode(verdict))
        act('decide', files['verdict'])
    finally:
        for path in files.values():
            path.unlink(missing_ok=True)
    entry['references'].append(reference)
    print(TAG, reference, f'approved by the scripted test actor; {LABEL}', flush=True)


def stage_icon(run, actor):
    """Give the actor the tree's test icon at run/source, as a plain file, after checking it is the frozen one."""
    raw = (ROOT / actor.PHOTO_PATH).read_bytes()
    proof.require(proof.digest(raw) == actor.PHOTO_SHA, f'the tree\'s {actor.PHOTO_PATH} is not the frozen test icon')
    target = run / 'source' / actor.PHOTO_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    proof.require(coordinator.absent(target), 'a test icon was already staged in this run')
    proof.private_write(target, raw)


def publication(walk, publish, actor, entry):
    """Publish; when the private drafts wait for review, review each with scripted inputs, then publish again."""
    hold = attempt(walk, publish, entry)
    if hold is None:
        entry['state'] = 'not needed: publication passed without a review'
        return
    order = list(actor.REFS)
    fixtures = json.loads((ROOT / 'demo/listings.json').read_text())['listings']
    proof.require(order == [row['id'] for row in fixtures if row['seller_type'] == 'private'],
                  'scripted actor references differ from the private demo drafts in fixture order')
    proofs = walk.state.get('listing_proofs', {})
    todo = [reference for reference in order if proofs.get(reference, {}).get('commands', {})
            .get('decide', {}).get('result', {}).get('state') != 'approved']
    # The actor answers all three references in order, so only an untouched or a fully approved
    # state can continue; a partial review is refused, never repeated or skipped.
    proof.require(todo in ([], order) and not any(reference in proofs for reference in todo),
                  'partially reviewed listing state cannot resume with the scripted actor')
    if not todo:
        raise hold
    entry['state'] = 'incomplete'
    stage_icon(walk.run_dir, actor)
    end = time.monotonic() + coordinator.REVIEW_SECONDS
    folder = walk.run_dir / coordinator.INPUTS
    if coordinator.absent(folder):
        folder.mkdir(mode=0o700)
    coordinator.safe_folder(walk.run_dir)
    coordinator.safe_folder(folder)
    proof.require(not any(folder.iterdir()), 'stale scripted listing input exists')
    print(f'{TAG} start: frozen test icon, fixed approved verdict, operator reviewer; {LABEL}', flush=True)
    with coordinator.hosted_actor(walk.run_dir, end):
        for position, reference in enumerate(todo):
            if position and attempt(walk, publish, entry) is None:
                raise RuntimeError('publication passed before every private draft was reviewed')
            review(walk, actor, reference, end, entry)
    hold = attempt(walk, publish, entry)
    if hold is not None:
        raise hold
    entry['state'] = 'passed'


def main(run_dir, origin):
    run = Path(run_dir).resolve()
    run.chmod(0o700)  # the review routes and the actor accept only an owner-only run folder
    proof.require(proof.digest(ACTOR.read_bytes()) == ACTOR_SHA256, 'the scripted actor differs from its pinned bytes')
    actor = load('n05_scripted_actor', ACTOR)
    walk = load('connected_walkthrough', WALK).Walkthrough(origin, 'native', run)
    entry = dict(state='not reached', label=LABEL, photo=f'frozen test icon {actor.PHOTO_PATH}',
                 verdict='fixed approved test verdict', reviewer='operator, no credentials file',
                 physical_inspection_verified=False, references=[], imports=0, review_calls=0)
    publish = walk.run_phase

    def run_phase(phase):
        return publication(walk, publish, actor, entry) if phase == 'publication' else publish(phase)

    walk.run_phase = run_phase
    try:
        walk.all()
    finally:
        try:
            (run / 'all-evidence.json').write_text(json.dumps(walk.evidence, indent=2))
        finally:
            walk.client.close()
            print(f'{TAG} summary ' + json.dumps(entry, sort_keys=True), flush=True)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
