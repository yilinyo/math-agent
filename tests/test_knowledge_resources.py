import asyncio
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from agent_platform.app import create_app
from agent_platform.knowledge_resources import INDEX_FILES, KnowledgeResources, ResourceCreate, ResourceUpdate, encoded
from agent_platform.models import PlatformError
from reasoning_agent.custom2.strategy_skills import select_strategy_skills
from reasoning_agent.lexical_strategy_retrieval import build_lexical_payloads, get_shared_lexical_strategy_retriever
from reasoning_agent.resource_files import resource_lock
from test_platform_graph import client_for_pass, config, context
from agent_platform.graph_runtime import LangGraphRuntime


@pytest.fixture
def resources(tmp_path):
    data = tmp_path / 'strategy_data'
    data.mkdir()
    handbook = tmp_path / 'skill2_en/linear_algebra/linear_algebra_skill.md'
    handbook.parent.mkdir(parents=True)
    handbook.write_text('# Linear algebra\nOriginal rank method.', encoding='utf-8')
    cards = [{'id': i, 'name': name, 'description': name + ' method', 'tags': [name],
              'applicability': ['Check assumptions'], 'steps': [{'step': 'Prove', 'detail': name}],
              'example': {'problem': 'Example', 'solution': 'Proof'}}
             for i, name in enumerate(['Rank', 'Determinant'])]
    lexical, manifest = build_lexical_payloads(cards)
    for name, value in [('strategy_meta.json', cards), ('strategy_lexical_index.json', lexical),
                        ('strategy_lexical_manifest.json', manifest), ('strategy_index.json', {
                            'embedding_model': 'Qwen/Qwen3-Embedding-0.6B', 'embedding_dim': 1024,
                            'num_strategies': 2, 'cards_digest': manifest['cards_digest']})]:
        (data / name).write_bytes(encoded(value))
    np.save(data / 'strategy_embeddings.npy', np.eye(2, 1024, dtype=np.float32))
    return KnowledgeResources(tmp_path, embedder=lambda text: np.ones(1024, dtype=np.float32))


def update(resources, kind, identifier, content):
    return resources.save(kind, identifier, ResourceUpdate(
        revision=resources.get(kind, identifier)['revision'], content=content))


def snapshot(resources):
    return {name: (resources.data / name).read_bytes() for name in INDEX_FILES}


def new_strategy():
    return {'name': 'Bijection with inverse verification', 'tags': ['bijection'],
            'description': 'Prove a counting identity by constructing mutually inverse maps.',
            'applicability': ['Two finite sets can be paired by explicit invertible maps.'],
            'steps': [{'step': 'Define the maps', 'detail': 'Construct the map and prove both inverse identities.'}],
            'example': {'problem': 'Count the subsets of a finite set.', 'solution': 'Use the indicator-vector bijection.'}}


def test_create_strategy_assigns_unique_ids_and_publishes_complete_indexes(resources):
    cached = get_shared_lexical_strategy_retriever(data_dir=resources.data)
    old_vectors = np.load(resources.data / 'strategy_embeddings.npy')
    with TestClient(create_app(resources=resources, rate_limits=False)) as client:
        response = client.post('/v1/resources/strategy', json={'content': json.dumps(new_strategy())})
        assert response.status_code == 201, response.text
        item = response.json()
        assert item['id'] == '2' and len(item['revision']) == 64
        assert json.loads(item['content']) == {**new_strategy(), 'id': 2}
        assert client.get('/v1/resources/strategy/2').json() == item
        assert client.get('/v1/resources/strategy?q=bijection').json()['total'] == 1
        another = client.post('/v1/resources/strategy', json={'content': json.dumps(new_strategy())})
        assert another.status_code == 201 and another.json()['id'] == '3'
    assert KnowledgeResources(resources.root).get('strategy', '2') == item
    updated = get_shared_lexical_strategy_retriever(data_dir=resources.data)
    assert updated is not cached and len(updated.cards) == 4
    vectors = np.load(resources.data / 'strategy_embeddings.npy')
    assert vectors.shape == (4, 1024)
    np.testing.assert_array_equal(vectors[:2], old_vectors)
    np.testing.assert_allclose(vectors[2:], np.ones((2, 1024)) / 32)
    assert json.loads((resources.data / 'strategy_index.json').read_text())['num_strategies'] == 4
    assert json.loads((resources.data / 'strategy_lexical_manifest.json').read_text())['card_ids'] == [0, 1, 2, 3]
    assert resources.version()


@pytest.mark.parametrize('fields', [
    {'id': 1}, {'name': ''}, {'tags': []}, {'applicability': ['']}, {'steps': []},
    {'steps': [{'step': 'Prove'}]}, {'example': {'solution': 'Answer'}},
    {'example': {'problem': 'Question', 'solution': ''}},
])
def test_create_rejects_invalid_schema_without_writing(resources, fields):
    before = snapshot(resources)
    with pytest.raises(PlatformError, match='resource_invalid_new_strategy'):
        resources.save('strategy', None, ResourceCreate(content=json.dumps({**new_strategy(), **fields})))
    assert snapshot(resources) == before
    assert not resources.version()


def test_create_busy_and_failed_encoding_do_not_consume_id(resources):
    draft = ResourceCreate(content=json.dumps(new_strategy()))
    before = snapshot(resources)
    with resource_lock(resources.data):
        with pytest.raises(PlatformError, match='resource_busy'):
            resources.save('strategy', None, draft)
    resources.embedder = lambda _: np.zeros(1024)
    with pytest.raises(PlatformError, match='resource_embedding_failed'):
        resources.save('strategy', None, draft)
    assert snapshot(resources) == before
    resources.embedder = lambda _: np.ones(1024)
    assert resources.save('strategy', None, draft)['id'] == '2'


def test_create_publication_failure_rolls_back_new_row(resources, monkeypatch):
    import agent_platform.knowledge_resources as module
    before = snapshot(resources)
    replace = module.os.replace
    failed = False
    def fail_once(source, target):
        nonlocal failed
        if Path(target).name == 'strategy_embeddings.npy' and not failed:
            failed = True
            raise OSError('disk unavailable')
        return replace(source, target)
    monkeypatch.setattr(module.os, 'replace', fail_once)
    with pytest.raises(PlatformError, match='resource_unavailable'):
        resources.save('strategy', None, ResourceCreate(content=json.dumps(new_strategy())))
    assert snapshot(resources) == before
    assert not resources.version()
    assert not (resources.data / '.resources-transaction.json').exists()


def test_api_lists_existing_and_edits_actual_handbook(resources):
    with TestClient(create_app(resources=resources, rate_limits=False)) as client:
        assert client.get('/health/ready').json()['knowledge_resources']
        page = client.get('/v1/resources/strategy', params={'limit_size': 1}).json()
        assert page['corpus_total'] == 2 and page['next_offset'] == 1
        assert client.get('/v1/resources/strategy?q=determinant').json()['total'] == 1
        item = client.get('/v1/resources/skill/linear_algebra').json()
        assert item['source'] == 'skill2_en/linear_algebra/linear_algebra_skill.md'
        assert str(resources.root) not in json.dumps(item)
        body = {'revision': item['revision'], 'content': '# Rank\nChanged rank method.'}
        assert client.put('/v1/resources/skill/linear_algebra', json=body).status_code == 200
        assert client.put('/v1/resources/skill/linear_algebra', json=body).status_code == 409
        assert client.get('/v1/resources/skill/not_a_domain').status_code == 404
        assert client.get('/v1/resources/unknown').status_code == 404
        assert client.post('/v1/resources/skill', json=body).status_code == 405
    material = select_strategy_skills('linear_algebra', [], repo_root=resources.root)
    assert 'Changed rank method' in material[0].prompt


def test_strategy_publish_updates_indexes_and_cached_retrievers(resources):
    from reasoning_agent.strategy_retrieval import get_shared_strategy_retriever

    lexical_before = get_shared_lexical_strategy_retriever(data_dir=resources.data)
    vector_before = get_shared_strategy_retriever(data_dir=resources.data, model_dir=resources.root / 'model', device='cpu')
    card = json.loads(resources.get('strategy', '0')['content'])
    card['name'] = 'Bijection'
    update(resources, 'strategy', '0', json.dumps(card))
    lexical_after = get_shared_lexical_strategy_retriever(data_dir=resources.data)
    vector_after = get_shared_strategy_retriever(data_dir=resources.data, model_dir=resources.root / 'model', device='cpu')
    assert lexical_before is not lexical_after and vector_before is not vector_after
    assert lexical_after.cards[0]['name'] == 'Bijection'
    assert vector_after._metadata[0]['name'] == 'Bijection'
    assert vector_before._embedding is vector_after._embedding
    vectors = np.load(resources.data / 'strategy_embeddings.npy')
    np.testing.assert_allclose(vectors[0], np.ones(1024) / 32)
    np.testing.assert_array_equal(vectors[1], np.eye(2, 1024)[1])
    assert json.loads((resources.data / 'strategy_lexical_manifest.json').read_text())['cards_digest'] == json.loads(
        (resources.data / 'strategy_index.json').read_text())['cards_digest']


def test_example_only_edit_skips_encoding_and_rejects_shape_changes(resources):
    resources.embedder = lambda _: pytest.fail('Example is not part of vector document')
    card = json.loads(resources.get('strategy', '0')['content'])
    card['example']['solution'] = 'Updated proof'
    update(resources, 'strategy', '0', json.dumps(card))
    before = snapshot(resources)
    card['id'] = 88
    with pytest.raises(PlatformError, match='resource_invalid_strategy'):
        update(resources, 'strategy', '0', json.dumps(card))
    assert snapshot(resources) == before


def test_encoding_failure_and_publication_failure_leave_originals(resources, monkeypatch):
    import agent_platform.knowledge_resources as module

    before = snapshot(resources)
    card = json.loads(resources.get('strategy', '0')['content'])
    card['name'] = 'Changed'
    def failed_embedding(_):
        raise ValueError('private local error')
    resources.embedder = failed_embedding
    with pytest.raises(PlatformError, match='resource_embedding_failed'):
        update(resources, 'strategy', '0', json.dumps(card))
    assert snapshot(resources) == before
    resources.embedder = lambda _: np.ones(1024)
    replace = module.os.replace
    failed = False
    def fail_once(source, target):
        nonlocal failed
        if Path(target).name == 'strategy_embeddings.npy' and not failed:
            failed = True
            raise OSError('disk failure')
        return replace(source, target)
    monkeypatch.setattr(module.os, 'replace', fail_once)
    with pytest.raises(PlatformError, match='resource_unavailable'):
        update(resources, 'strategy', '0', json.dumps(card))
    assert snapshot(resources) == before
    assert not (resources.data / '.resources-transaction.json').exists()


def test_active_reader_blocks_edit(resources):
    with resource_lock(resources.data):
        with pytest.raises(PlatformError, match='resource_busy'):
            update(resources, 'skill', 'linear_algebra', '# New material')


def test_interrupted_rollback_retains_backups_for_startup_recovery(resources, monkeypatch):
    import agent_platform.knowledge_resources as module

    before = snapshot(resources)
    card = json.loads(resources.get('strategy', '0')['content'])
    card['name'] = 'Changed'
    replace = module.os.replace
    metadata_writes = 0
    def failed_disk(source, target):
        nonlocal metadata_writes
        if Path(target).name == 'strategy_meta.json':
            metadata_writes += 1
        if Path(target).name == 'strategy_embeddings.npy' or metadata_writes > 1:
            raise OSError('disk unavailable during rollback')
        return replace(source, target)
    monkeypatch.setattr(module.os, 'replace', failed_disk)
    with pytest.raises(PlatformError, match='resource_unavailable'):
        update(resources, 'strategy', '0', json.dumps(card))
    assert (resources.data / '.resources-transaction.json').exists()
    assert list(resources.data.glob('.resource-edit-*'))
    monkeypatch.setattr(module.os, 'replace', replace)
    recovered = KnowledgeResources(resources.root)
    assert snapshot(recovered) == before
    assert not (resources.data / '.resources-transaction.json').exists()
    assert not list(resources.data.glob('.resource-edit-*'))


def test_resource_revision_invalidates_old_checkpoint_and_new_one_resumes(resources, monkeypatch):
    import agent_platform.reasoning_runtime as module
    original_hash = module.config_hash
    monkeypatch.setattr(module, 'config_hash', lambda *args: original_hash(*args, root=resources.root))
    runtime = LangGraphRuntime(client_for_pass(), config())
    runtime.resources = resources
    ctx, _, old = context()
    asyncio.run(runtime.run(ctx))
    assert runtime.checkpoint_compatible(old[-1])
    card = json.loads(resources.get('strategy', '0')['content'])
    card['name'] = 'Updated rank strategy'
    update(resources, 'strategy', '0', json.dumps(card))
    assert not runtime.checkpoint_compatible(old[-1])
    runtime.client = client_for_pass()
    ctx, _, new = context()
    result = asyncio.run(runtime.run(ctx))
    assert runtime.checkpoint_compatible(new[-1])
    resumed, _, _ = context(checkpoint=new[-1], deadline=ctx.deadline_at)
    assert asyncio.run(runtime.run(resumed)).final_response == result.final_response
    assert len(runtime.client.calls) == 5
    restarted = LangGraphRuntime(client_for_pass(), config())
    restarted.resources = KnowledgeResources(resources.root)
    assert restarted.checkpoint_compatible(new[-1])
