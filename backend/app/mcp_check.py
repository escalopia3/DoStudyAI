"""Explicit smoke test for an operator-configured MCP search endpoint."""
import argparse
import json
from dovideo.config import load_local_environment
from dovideo.mcp.client import discover_tools, invoke

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tool',choices=['external_search','video_search'])
    parser.add_argument('--query',default='学习资料')
    parser.add_argument('--list-tools',action='store_true')
    parser.add_argument('--platform',choices=['bilibili','mooc'])
    args=parser.parse_args()
    load_local_environment()
    try:
        if args.list_tools:
            print(json.dumps(discover_tools(args.tool),ensure_ascii=False,indent=2))
            return
        results=invoke(args.tool,args.query,args.platform)
    except ValueError as exc:
        code=str(exc)
        parser.exit(1,f'MCP check failed: {code if code.startswith(("MCP_", "INVALID_MCP_")) else "invalid configuration"}\n')
    except Exception as exc:
        parser.exit(1,f'MCP check failed: {type(exc).__name__}\n')
    if not results:
        parser.exit(1,'MCP call returned no usable results. Try a query known to match.\n')
    print(f'{args.tool}: connected, {len(results)} usable results')

if __name__=='__main__':main()
