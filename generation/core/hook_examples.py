"""Load the entire fixed hook corpus with portable provenance, without network access."""
import hashlib
import json
from pathlib import Path

from prompts.lore_hooks import HOOK_CORPUS_ROLE

CORPUS = Path(__file__).resolve().parents[1] / 'docs/hook_dataset/2026-09-24/hooks.json'


def youtube_hook_examples():
    data = json.loads(CORPUS.read_text(encoding='utf-8'))
    items = data['items']
    if len(items) != data['count'] or len(items) < 40:
        raise ValueError('Hook corpus is incomplete; expected at least 40 reviewed examples')
    if len({x['video_id'] for x in items}) != len(items):
        raise ValueError('Duplicate video in hook corpus')
    # Keep annotations in the review dataset. In a writing prompt, the quoted prose
    # should outweigh our commentary about it; do not duplicate its first sentence.
    fields = ('id', 'title', 'channel', 'quote')
    return {'version': data['version'], 'count': len(items),
            'sha256': hashlib.sha256(CORPUS.read_bytes()).hexdigest(),
            'role': HOOK_CORPUS_ROLE,
            'items': [{k: x[k] for k in fields} for x in items]}


def format_hook_examples(corpus: dict) -> str:
    """Render the quoted openings as readable passages in the writer's system prompt."""
    return '\n\n'.join(
        f"{item['id']}. {item['title']} ({item['channel']})\n{item['quote']}"
        for item in corpus['items']
    )
