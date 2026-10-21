import unittest

from knowledge_service.indexing.chunking import HierarchicalChunker


def element(identifier, kind, text, path, page):
    return {"id": identifier, "type": kind, "markdown": text, "titlePath": path,
            "locators": [{"type": "PAGE", "pageIndex": page}]}


class ChunkingTests(unittest.TestCase):
    def test_parent_child_metadata_and_stable_ids(self):
        document = {"resourceRevisionId": "rev1", "name": "数据库原理", "elements": [
            element("e1", "HEADING", "# 第三章 数据库索引", ["第三章 数据库索引"], 2),
            element("e2", "PARAGRAPH", "B+树叶子节点通过链表连接。", ["第三章 数据库索引"], 2),
            element("e3", "HEADING", "## 聚簇索引", ["第三章 数据库索引", "聚簇索引"], 3),
            element("e4", "PARAGRAPH", "数据行与索引顺序一致。", ["第三章 数据库索引", "聚簇索引"], 3),
        ]}
        chunker = HierarchicalChunker(child_max_tokens=64, parent_max_tokens=128)
        first, second = chunker.build(document), chunker.build(document)
        self.assertEqual([x.chunkId for x in first.children], [x.chunkId for x in second.children])
        self.assertEqual(len(first.parents), 2)
        self.assertTrue(all(x.parentId for x in first.children))
        self.assertIn("数据库原理", first.children[0].embeddingText)
        self.assertEqual(first.children[0].locators[0]["pageIndex"], 2)
        self.assertEqual(first.parents[0].childIds, [first.children[0].chunkId])

    def test_atomic_table_is_not_split(self):
        text = "| 字段 | 含义 |\n|---|---|\n" + "\n".join(f"| {i} | 内容 |" for i in range(100))
        document = {"resourceRevisionId": "rev1", "name": "表格", "elements": [
            element("t1", "TABLE", text, ["数据字典"], 0)]}
        bundle = HierarchicalChunker(child_max_tokens=64, parent_max_tokens=128).build(document)
        self.assertEqual(len(bundle.children), 1)
        self.assertEqual(bundle.children[0].elementType, "TABLE")
        self.assertEqual(bundle.children[0].content, text)


if __name__ == "__main__": unittest.main()

