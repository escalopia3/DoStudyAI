import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

def configured(*, require_tool=True):
    raw=os.getenv('DOVIDEO_MCP_TOOLS','{}')
    data=json.loads(raw)
    if not isinstance(data,dict):raise ValueError('INVALID_MCP_CONFIGURATION')
    for name,item in data.items():
        if name not in ('external_search','video_search') or not isinstance(item,dict):
            raise ValueError('INVALID_MCP_CONFIGURATION')
        if 'command' in item:
            if ('url' in item or 'token_env' in item or not isinstance(item['command'],str)
                    or not item['command'].strip() or not isinstance(item.get('args',[]),list)
                    or not all(isinstance(arg,str) for arg in item.get('args',[]))):
                raise ValueError('INVALID_MCP_CONFIGURATION')
        else:
            url=urlsplit(item.get('url',''))
            if url.scheme!='https' or not url.hostname or url.username or url.password or url.fragment:
                raise ValueError('MCP_HTTPS_REQUIRED')
        if not isinstance(item.get('arguments',{}),dict):
            raise ValueError('INVALID_MCP_CONFIGURATION')
        if (require_tool or 'tool' in item) and (not isinstance(item.get('tool'),str) or not item['tool']):
            raise ValueError('INVALID_MCP_TOOL')
        for field,pattern in (('query_field',r'[A-Za-z_][A-Za-z0-9_]*'),('token_env',r'DOVIDEO_MCP_[A-Z0-9_]+')):
            if field in item and (not isinstance(item[field],str) or not re.fullmatch(pattern,item[field])):
                raise ValueError('INVALID_MCP_CONFIGURATION')
    return data

@asynccontextmanager
async def _connect(item):
    from mcp import Client
    if 'command' in item:
        from mcp.client.stdio import StdioServerParameters
        key = os.getenv('DOVIDEO_MCP_BRAVE_API_KEY') or os.getenv('BRAVE_API_KEY')
        env = {'BRAVE_API_KEY':key} if key else {}
        async with Client(StdioServerParameters(command=item['command'],args=item.get('args',[]),env=env)) as client:
            yield client
        return
    from mcp.client.streamable_http import streamable_http_client
    import httpx2
    headers={}
    if item.get('token_env'):
        token=os.getenv(item['token_env'])
        if not token:raise ValueError('MCP_TOKEN_NOT_CONFIGURED')
        headers['Authorization']='Bearer '+token
    async with httpx2.AsyncClient(headers=headers,trust_env=False,timeout=15) as http:
        async with Client(streamable_http_client(item['url'],http_client=http)) as client:
            yield client

async def _invoke(item,query=None,platform=None):
    async with _connect(item) as client:
        cursor = None
        tools = []
        while True:
            page = await client.list_tools(cursor=cursor)
            tools.extend(page.tools)
            cursor = page.next_cursor
            if cursor is None or (query is not None and any(tool.name == item['tool'] for tool in tools)):
                break
        if query is None:
            return [{'name':tool.name,'input_schema':tool.input_schema} for tool in tools]
        if not any(tool.name == item['tool'] for tool in tools):
            raise ValueError('MCP_TOOL_UNAVAILABLE')
        arguments = {**item.get('arguments',{}),item.get('query_field','query'):query}
        result = await client.call_tool(item['tool'],arguments)
        if result.is_error:
            raise ValueError('MCP_TOOL_FAILED')
        if platform:
            return _learning_links(result,platform)
        content = [{'type':'text','text':part.text[:1800]} for part in result.content
                   if part.type=='text' and part.text.strip()][:5]
        if not content and result.structured_content:
            content.append({'type':'text','text':json.dumps(result.structured_content,ensure_ascii=False)[:1800]})
        return content

LEARNING_DOMAINS = {'bilibili':'bilibili.com','mooc':'icourse163.org'}

def _learning_links(result,platform):
    domain = LEARNING_DOMAINS[platform]
    links = {}
    def collect(value):
        if len(links) >= 5:
            return
        if isinstance(value,list):
            for entry in value:
                collect(entry)
        elif isinstance(value,dict):
            url = value.get('url')
            title = value.get('title')
            if isinstance(url,str) and isinstance(title,str) and title.strip():
                try:
                    parsed = urlsplit(url)
                    host = parsed.hostname or ''
                    if (parsed.scheme in ('http','https') and not parsed.username and not parsed.password
                            and (host == domain or host.endswith('.'+domain))):
                        summary = value.get('description') or value.get('snippet') or ''
                        links.setdefault(url,{'title':title[:240],'url':url,'platform':platform,
                            'summary':summary[:500] if isinstance(summary,str) else ''})
                except ValueError:
                    pass
            for child in value.values():
                collect(child)
    collect(result.structured_content)
    for part in result.content:
        if part.type == 'text':
            try:
                collect(json.loads(part.text))
            except (ValueError, RecursionError):
                continue
    return list(links.values())

def discover_tools(name):
    item = configured(require_tool=False).get(name)
    if item is None:
        raise ValueError('MCP_TOOL_NOT_CONFIGURED')
    return asyncio.run(asyncio.wait_for(_invoke(item),timeout=20))

def invoke(name,query,platform=None):
    item=configured().get(name)
    if item is None:raise ValueError('MCP_TOOL_NOT_CONFIGURED')
    if platform:
        domain = LEARNING_DOMAINS[platform]
        query = f'site:{domain} {query}'
    return asyncio.run(asyncio.wait_for(_invoke(item,query,platform),timeout=20))
