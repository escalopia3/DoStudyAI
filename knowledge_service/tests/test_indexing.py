import unittest

from knowledge_service.indexing.embedding import LocalBgeM3Config, validate_vectors
from knowledge_service.indexing.pipeline import BuildRequest, IndexPipeline
from knowledge_service.indexing.store import IndexStore, metadata


class FakeEmbeddings:
    version = "fake__d3__tpl1"
    dimension = 3
    def embed_documents(self, texts): return [[1.0, 0.0, 0.0] for _ in texts]
    def embed_query(self, text): return [1.0, 0.0, 0.0]


class FakeQdrant:
    def __init__(self): self.points = []
    def ensure_schema(self): pass
    def upsert(self, owner_id, resource_id, source_revision, index_revision,
               embedding_version, chunks, vectors):
        self.points = [{"payload": chunk.to_dict() | {"resourceId": resource_id,
            "indexRevision": index_revision}} for chunk in chunks]
    def count(self, resource_id, index_revision): return len(self.points)
    def sample(self, resource_id, index_revision, limit=10): return self.points[:limit]
    def manifest_hash(self, chunks): return "manifest-hash"


class IndexingTests(unittest.TestCase):
    def setUp(self):
        self.store = IndexStore("sqlite:///:memory:")
        metadata.create_all(self.store.engine)
    def tearDown(self):
        self.store.engine.dispose()

    def test_build_verify_and_publish(self):
        document = {"schemaVersion": "1", "resourceRevisionId": "src1", "name": "课程", "elements": [
            {"id": "e1", "type": "PARAGRAPH", "markdown": "向量数据库保存向量。",
             "titlePath": ["向量检索"], "locators": [{"type": "PAGE", "pageIndex": 0}]}]}
        manifest = IndexPipeline(self.store, FakeQdrant(), FakeEmbeddings()).build_and_publish(
            document, BuildRequest("u1", "r1", "src1", "idx1"))
        self.assertEqual(manifest["generation"], 1)
        self.assertEqual(self.store.active(["r1"])[0]["index_revision"], "idx1")
        self.assertGreater(manifest["expectedChildCount"], 0)

    def test_publication_fence_keeps_verified_revision_inactive(self):
        document = {"schemaVersion": "1", "resourceRevisionId": "src1", "name": "课程", "elements": [
            {"id": "e1", "type": "PARAGRAPH", "markdown": "发布前必须复核来源。",
             "titlePath": ["安全"], "locators": [{"type": "PAGE", "pageIndex": 0}]}]}
        def reject(): raise ValueError("SOURCE_CHANGED")
        with self.assertRaisesRegex(ValueError, "SOURCE_CHANGED"):
            IndexPipeline(self.store, FakeQdrant(), FakeEmbeddings()).build_and_publish(
                document, BuildRequest("u1", "r1", "src1", "idx-fenced"), before_publish=reject)
        self.assertEqual(self.store.active(["r1"]), [])

    def test_publish_is_cas_protected(self):
        self.store.begin("r1", "src1", "idx1", "v1")
        self.store.mark_verified("idx1", {})
        with self.assertRaisesRegex(ValueError, "CAS"):
            self.store.publish("r1", "src1", "idx1", "missing")

    def test_vector_validation(self):
        with self.assertRaisesRegex(ValueError, "DIMENSION"):
            validate_vectors([[1.0]], 1, 3)

    def test_local_model_requires_existing_directory_without_loading_dependency(self):
        with self.assertRaisesRegex(ValueError, "DIRECTORY"):
            from knowledge_service.indexing.embedding import LocalBgeM3Provider
            LocalBgeM3Provider(LocalBgeM3Config("Z:/missing-model", "rev"))


if __name__ == "__main__": unittest.main()

