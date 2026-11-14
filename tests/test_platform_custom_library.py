import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from agent_platform.app import create_app
from agent_platform.custom_library import CustomLibrary, LibraryEntry
from agent_platform.graph_runtime import LangGraphRuntime
from agent_platform.models import PlatformError
from agent_platform.runtime import CheckpointIncompatible
from test_platform_graph import client_for_pass, config, context


def entry(**updates):
    return LibraryEntry.model_validate({
        'kind': 'strategy', 'title': 'Bijection method', 'category': 'combinatorics',
        'keywords': 'bijection graph counting', 'content': 'original technique: prove both directions of the bijection.',
        'enabled': True, **updates,
    })


def test_crud_persists_and_rejects_stale_writes(tmp_path):
    library = CustomLibrary(tmp_path)
    created = library.save(entry())
    assert CustomLibrary(tmp_path).list() == [created]
    updated = library.save(entry(content='updated method'), created['id'], created['revision'])
    assert updated['revision'] == 2
    with pytest.raises(PlatformError, match='library_conflict'):
        library.save(entry(), created['id'], created['revision'])
    with pytest.raises(PlatformError, match='library_conflict'):
        library.delete(created['id'], created['revision'])
    library.delete(updated['id'], updated['revision'])
    assert library.list() == []


def test_only_enabled_matching_material_is_selected_and_bounded(tmp_path):
    library = CustomLibrary(tmp_path)
    chosen = library.save(entry())
    library.save(entry(title='Disabled bijection', enabled=False, content='disabled technique'))
    library.save(entry(title='Unrelated', keywords='ocean', category='ocean', content='ocean tides'))
    selected = json.loads(library.select('Find a bijection for graph counting.'))
    assert [item['id'] for item in selected] == [chosen['id']]
    assert library.select('zzzzzzzz') == ''
    for number in range(6):
        library.save(entry(title=f'Bijection {number}', content='bijection ' * 900))
    material = library.select('bijection')
    assert len(material) <= 12000 and len(json.loads(material)) <= 4


def test_library_api_validates_sanitizes_and_hides_paths(tmp_path):
    with TestClient(create_app(library=CustomLibrary(tmp_path), rate_limits=False)) as client:
        assert client.get('/health/ready').json()['custom_library'] is True
        body = entry(content='Check definitions. api_key=private-value').model_dump()
        response = client.post('/v1/library', json=body)
        assert response.status_code == 201
        created = response.json()
        assert 'private-value' not in response.text and str(tmp_path) not in response.text
        assert client.get('/v1/library').json()['items'] == [created]
        assert client.post('/v1/library', json={**body, 'title': ' '}).status_code == 400
        assert client.post('/v1/library', json={**body, 'content': 'x' * 10001}).status_code == 400
        assert client.post('/v1/library', json={**body, 'kind': 'executable'}).status_code == 400
        url = '/v1/library/' + created['id']
        changed = client.put(url, json={**body, 'enabled': False, 'revision': 1})
        assert changed.status_code == 200 and not changed.json()['enabled']
        assert client.put(url, json={**body, 'revision': 1}).status_code == 409
        assert client.delete(url, params={'revision': 2}).status_code == 200


def test_library_routes_are_unavailable_without_explicit_bootstrap():
    with TestClient(create_app()) as client:
        assert client.get('/health/ready').json()['custom_library'] is False
        assert client.get('/v1/library').status_code == 503


def test_material_reaches_solver_and_resume_retains_snapshot(tmp_path):
    library = CustomLibrary(tmp_path)
    created = library.save(entry(keywords='compute definition'))
    client = client_for_pass()
    runtime = LangGraphRuntime(client, config(), library=library)
    ctx, _, checkpoints = context()
    result = asyncio.run(runtime.run(ctx))
    assert 'original technique' in json.dumps(client.calls)
    assert all('original technique' in checkpoint['custom_material'] for checkpoint in checkpoints)
    assert 'untrusted_reference_only' in json.dumps(client.calls)
    library.save(entry(content='replacement technique'), created['id'], 1)
    resumed, _, _ = context(checkpoint=checkpoints[-1], deadline=ctx.deadline_at)
    assert asyncio.run(runtime.run(resumed)).final_response == result.final_response
    assert 'original technique' in resumed.checkpoint['custom_material']
    assert len(client.calls) == 5


def test_disabling_or_deleting_material_changes_only_new_tasks(tmp_path):
    library = CustomLibrary(tmp_path)
    created = library.save(entry(keywords='compute definition'))
    model = client_for_pass()
    runtime = LangGraphRuntime(model, config(), library=library)
    ctx, _, checkpoints = context()
    asyncio.run(runtime.run(ctx))
    disabled = library.save(entry(enabled=False), created['id'], created['revision'])
    assert library.select(ctx.problem) == ''
    library.delete(disabled['id'], disabled['revision'])
    assert library.list() == []
    resumed, _, _ = context(checkpoint=checkpoints[2], deadline=ctx.deadline_at)
    resumed_model = client_for_pass()
    resumed_model.responses = resumed_model.responses[2:]
    asyncio.run(LangGraphRuntime(resumed_model, config(), library=library).run(resumed))
    assert 'original technique' in json.dumps(resumed_model.calls)
    new_model = client_for_pass()
    fresh, _, _ = context()
    asyncio.run(LangGraphRuntime(new_model, config(), library=library).run(fresh))
    assert 'user_library_material' not in json.dumps(new_model.calls)


def test_material_snapshot_is_bounded_and_old_checkpoints_remain_valid(tmp_path):
    library = CustomLibrary(tmp_path)
    runtime = LangGraphRuntime(client_for_pass(), config(), library=library)
    ctx, _, checkpoints = context()
    asyncio.run(runtime.run(ctx))
    previous = dict(checkpoints[-1])
    previous.pop('custom_material')
    resumed, _, _ = context(checkpoint=previous, deadline=ctx.deadline_at)
    assert asyncio.run(runtime.run(resumed)).final_response
    invalid = {**checkpoints[-1], 'custom_material': 'x' * 12001}
    resumed, _, _ = context(checkpoint=invalid, deadline=ctx.deadline_at)
    with pytest.raises(CheckpointIncompatible):
        asyncio.run(runtime.run(resumed))


def test_library_sql_failures_are_public_codes_without_paths(tmp_path):
    library = CustomLibrary(tmp_path)
    library.path = tmp_path / 'nonexistent' / 'private.sqlite'
    with TestClient(create_app(library=library, rate_limits=False)) as client:
        response = client.get('/v1/library')
        assert response.status_code == 503
        assert response.json() == {'error': {'code': 'library_unavailable'}}
        assert str(tmp_path) not in response.text
