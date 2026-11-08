"""Token-aware input bounding while preserving original source locators."""
from dataclasses import replace
import re
from knowledge_service.indexing.chunking import HierarchicalChunker

def build_chunks(document, tokenizer, child_tokens=600, parent_tokens=1800):
    def count(text):
        return len(tokenizer.encode(text, add_special_tokens=False, truncation=False))
    elements, original_ids, spans = [], {}, {}
    for element in document['elements']:
        text = str(element.get('markdown') or '').strip()
        if element.get('type')=='FORMULA' and count(text)>child_tokens:
            raise ValueError('FORMULA_EXCEEDS_TOKEN_LIMIT_REVIEW_REQUIRED')
        table = element.get('data',{}).get('table') if element.get('type')=='TABLE' else None
        table_parts = None
        if table and table.get('table_cells'):
            cells=table['table_cells']
            headers=[c for c in cells if c.get('column_header')]
            header=' | '.join(c.get('text','') for c in headers)
            rows=[]
            for row in range(table.get('num_rows',0)):
                values=[c.get('text','') for c in cells if c.get('start_row_offset_idx')==row and not c.get('column_header')]
                if values: rows.append(' | '.join(values))
            table_parts=[]
            group=[]
            prefix='表头：'+header+'\n' if header else ''
            for row in rows:
                if group and count(prefix+'\n'.join(group+[row]))>child_tokens:
                    table_parts.append(prefix+'\n'.join(group));group=[]
                group.append(row)
            if group: table_parts.append(prefix+'\n'.join(group))
            if any(count(p)>child_tokens for p in table_parts):
                raise ValueError('TABLE_ROW_OR_HEADER_EXCEEDS_TOKEN_LIMIT')
            if table_parts: text=table_parts.pop(0)
        part = 0
        offset = len(str(element.get('markdown') or ''))-len(str(element.get('markdown') or '').lstrip())
        while text:
            # Binary search also handles a very long sentence, table or code
            # block; the old semantic splitter intentionally kept those atomic.
            low, high = 1, min(len(text),child_tokens*8)
            while low < high:
                middle = (low+high+1)//2
                if count(text[:middle]) <= child_tokens:
                    low = middle
                else:
                    high = middle-1
            end = low
            if element.get('type')=='FORMULA':end=len(text)
            if end < len(text):
                boundaries = [m.end() for m in re.finditer(r'\n\n|[。！？.!?](?:\s|$)', text[:end])]
                if boundaries and boundaries[-1] >= end // 2:
                    end = boundaries[-1]
            identifier = str(element['id']) + f':part:{part}'
            piece=text[:end]
            if table and part and header and not piece.startswith('表头：'):
                prefix='表头：'+header+'\n'
                while end>1 and count(prefix+text[:end])>child_tokens: end-=1
                piece=prefix+text[:end]
            elements.append(dict(element,id=identifier,markdown=piece))
            original_ids[identifier] = str(element['id'])
            spans[identifier] = {'element_id':str(element['id']),
                'text':piece.strip(),'locators':element.get('locators',[]),
                'element_type':element.get('type'), **(
                {'kind':'TABLE_ELEMENT'} if table else {'start':offset,'end':offset+end})}
            offset += end
            text = text[end:]
            if not text and table_parts:
                text=table_parts.pop(0)
            part += 1
    bundle = HierarchicalChunker(child_tokens,parent_tokens,count).build(dict(document,elements=elements))
    def restore(chunk):
        from dovideo.knowledge_artifacts import section_id
        return replace(chunk, sourceElementIds=list(dict.fromkeys(original_ids[i] for i in chunk.sourceElementIds)),
            sourceSpans=[spans[i] for i in chunk.sourceElementIds],sectionId=section_id(chunk.titlePath),
            resourceRevisionId=document['resourceRevisionId'],chunkingVersion='structure-v4')
    children = [restore(c) for c in bundle.children]
    parents = []
    for parent in bundle.parents:
        members = [c for c in children if c.parentId == parent.chunkId]
        content = '\n\n'.join(c.content for c in members)
        parents.append(replace(restore(parent),content=content,tokenCount=count(content)))
        if count(content)>2000:
            raise ValueError('PARENT_TOKEN_LIMIT_EXCEEDED')
    return replace(bundle, chunkerVersion='structure-v4', parents=parents, children=children)
