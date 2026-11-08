import os
import json
import httpx
import copy
import time
from urllib.parse import urlsplit
from dovideo.agents.reliability import invoke
class ChatModel:
    def __init__(self,requested=None):
        self.model=os.getenv('DOVIDEO_CHAT_MODEL','')
        self.url=os.getenv('DOVIDEO_CHAT_BASE_URL','').rstrip('/')
        self.key=os.getenv('DOVIDEO_CHAT_API_KEY','')
        if not all((self.model,self.url,self.key)):raise ValueError('CHAT_MODEL_NOT_CONFIGURED')
        if requested and requested!=self.model:raise ValueError('CHAT_MODEL_NOT_AVAILABLE')

    def final_answer_model(self):
        """Avoid spending the final answer allowance on another reasoning-only response.

        DeepSeek requires reasoning replay during thinking tool calls. Keep that intact;
        only the separate, tool-free final synthesis disables thinking via its native API.
        Other OpenAI-compatible providers do not receive an unsupported vendor parameter.
        """
        model=copy.copy(self)
        model.final_answer=True
        return model

    def thinking_options(self):
        if urlsplit(self.url).hostname!='api.deepseek.com':return {}
        mode=os.getenv('DOVIDEO_CHAT_FINAL_THINKING','disabled') if getattr(self,'final_answer',False) else os.getenv('DOVIDEO_CHAT_THINKING','auto')
        if mode not in ('auto','enabled','disabled'):raise ValueError('INVALID_THINKING_MODE')
        return {'thinking':{'type':mode}} if mode!='auto' else {}
    def __call__(self,messages,tools):
        return invoke(lambda remaining:self._request(messages,tools,remaining),
            model_id=self.model,
            attempts=max(1,min(3,int(os.getenv('DOVIDEO_MODEL_ATTEMPTS','3')))),
            budget=float(os.getenv('DOVIDEO_MODEL_DEADLINE_SECONDS','120')))

    def _request(self,messages,tools,remaining):
        payload={'model':self.model,'messages':messages,
                 'max_tokens':int(os.getenv('DOVIDEO_CHAT_OUTPUT_TOKENS','2048'))}
        payload.update(self.thinking_options())
        if tools:payload['tools']=tools
        with httpx.Client(timeout=httpx.Timeout(min(90,remaining),connect=min(10,remaining)),trust_env=False) as client:
            response=client.post(self.url+'/chat/completions',headers={'Authorization':'Bearer '+self.key},
                json=payload)
            response.raise_for_status(); result=response.json()
        return result['choices'][0]['message'],result.get('usage',{})

    def stream(self,messages,tools,on_text,check):
        shown=False
        def output(text):
            nonlocal shown
            # Once handed to the worker, treat buffered text as potentially visible.
            shown=True
            on_text(text)
        return invoke(lambda remaining:self._stream_request(messages,tools,output,check,remaining),
            model_id=self.model,
            check=check,emitted=lambda:shown,
            attempts=max(1,min(3,int(os.getenv('DOVIDEO_MODEL_ATTEMPTS','3')))),
            budget=float(os.getenv('DOVIDEO_MODEL_DEADLINE_SECONDS','120')))

    def _stream_request(self,messages,tools,on_text,check,remaining):
        deadline=time.monotonic()+remaining
        payload={'model':self.model,'messages':messages,
                 'max_tokens':int(os.getenv('DOVIDEO_CHAT_OUTPUT_TOKENS','2048')),
                 'stream':True,'stream_options':{'include_usage':True}}
        payload.update(self.thinking_options())
        if tools:payload['tools']=tools
        parts,calls,usage,reasoning=[],{},{},[]
        done=False
        with httpx.Client(timeout=httpx.Timeout(min(90,remaining),connect=min(10,remaining)),trust_env=False) as client:
            with client.stream('POST',self.url+'/chat/completions',
                    headers={'Authorization':'Bearer '+self.key},json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    check()
                    if time.monotonic()>=deadline:
                        from dovideo.agents.reliability import AgentFailure
                        raise AgentFailure('MODEL_DEADLINE_EXCEEDED')
                    if not line.startswith('data:'):continue
                    raw=line[5:].strip()
                    if raw=='[DONE]':
                        done=True
                        break
                    check()
                    event=json.loads(raw)
                    usage=event.get('usage') or usage
                    for choice in event.get('choices',[]):
                        if choice.get('index',0)!=0:continue
                        delta=choice.get('delta',{})
                        if delta.get('reasoning_content'):reasoning.append(delta['reasoning_content'])
                        if delta.get('content'):
                            parts.append(delta['content'])
                            on_text(delta['content'])
                        for call in delta.get('tool_calls',[]):
                            item=calls.setdefault(call['index'],{'id':'','type':'function',
                                'function':{'name':'','arguments':''}})
                            item['id']+=call.get('id') or ''
                            for key in ('name','arguments'):
                                item['function'][key]+=call.get('function',{}).get(key) or ''
        if not done:raise ValueError('MODEL_STREAM_INTERRUPTED')
        message={'role':'assistant','content':''.join(parts)}
        if reasoning:message['reasoning_content']=''.join(reasoning)
        if calls:message['tool_calls']=[calls[i] for i in sorted(calls)]
        return message,usage
