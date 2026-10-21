import unittest

from knowledge_service.indexing.retrieval import KnowledgeRetriever


class Store:
    def active(self, ids):
        return [{"resource_id": "r1", "index_revision": "i1"},
                {"resource_id": "r2", "index_revision": "i2"}]


class Embeddings:
    def embed_query(self, text): return [1.0, 0.0]


class Qdrant:
    def __init__(self): self.calls = []
    def query(self, vector, text, owner, pairs, **options):
        self.calls.append((owner, pairs, options["chunk_type"]))
        return [{"payload": {"chunkType": options["chunk_type"]}}]


class RetrievalTests(unittest.TestCase):
    def test_empty_authorization_never_queries(self):
        qdrant = Qdrant()
        result = KnowledgeRetriever(Store(), qdrant, Embeddings()).search("u1", [], "问题")
        self.assertEqual(result.childHits, [])
        self.assertEqual(qdrant.calls, [])

    def test_active_resource_versions_remain_paired(self):
        qdrant = Qdrant()
        result = KnowledgeRetriever(Store(), qdrant, Embeddings()).search("u1", ["r1", "r2"], "问题")
        self.assertEqual(qdrant.calls[0][1], [("r1", "i1"), ("r2", "i2")])
        self.assertEqual(len(result.parentHits), 1)
        self.assertNotEqual(result.knowledgeSnapshotId, "empty")


if __name__ == "__main__": unittest.main()
