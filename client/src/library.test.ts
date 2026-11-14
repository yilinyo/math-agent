import { afterEach, expect, it, vi } from 'vitest';
import { ApiError, deleteLibrary, errorMessage, getLibrary, saveLibrary, type LibraryDraft } from './api';

afterEach(() => { vi.unstubAllGlobals(); });

const draft: LibraryDraft = {
  kind: 'skill', title: 'Finite fields', category: 'Algebra', keywords: 'subfields',
  content: 'Check the extension degree.', enabled: true,
};

it('creates, updates and deletes with a revision to prevent stale writes', async () => {
  const fetch = vi.fn().mockImplementation(async () => new Response('{}'));
  vi.stubGlobal('fetch', fetch);
  await getLibrary();
  await saveLibrary(draft);
  const item = { ...draft, id: 'entry/id', revision: 3, updated_at: '' };
  await saveLibrary({ ...draft, enabled: false }, item);
  await deleteLibrary(item);
  expect(fetch.mock.calls[0][0]).toBe('/v1/library');
  expect(fetch.mock.calls[1][1].method).toBe('POST');
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual(draft);
  expect(fetch.mock.calls[2][0]).toBe('/v1/library/entry%2Fid');
  expect(fetch.mock.calls[2][1].method).toBe('PUT');
  expect(JSON.parse(fetch.mock.calls[2][1].body)).toEqual({ ...draft, enabled: false, revision: 3 });
  expect(fetch.mock.calls[3][0]).toBe('/v1/library/entry%2Fid?revision=3');
  expect(fetch.mock.calls[3][1].method).toBe('DELETE');
});

it('reports edit conflicts and capacity failures without exposing server text', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
    error: { code: 'library_conflict', detail: 'private data' },
  }), { status: 409 })));
  await expect(saveLibrary(draft)).rejects.toMatchObject({ code: 'library_conflict', status: 409 });
  expect(errorMessage(new ApiError('library_conflict', 409))).toContain('刷新列表');
  expect(errorMessage(new ApiError('library_capacity', 409))).toContain('500');
});
