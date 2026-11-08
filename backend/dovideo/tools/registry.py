from dataclasses import dataclass
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal

class Args(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Search(Args):
    query:str=Field(min_length=1,max_length=500)
class Load(Args):
    names:list[str]=Field(min_length=1,max_length=5)
class Knowledge(Args):
    query:str=Field(default='',max_length=2000)
    intent:Literal['auto','detail','overview']='auto'
    resource_ids:list[str]=Field(default_factory=list,max_length=100)
    section_ids:list[str]=Field(default_factory=list,max_length=100)
    cursor:str|None=Field(default=None,max_length=4000)
class ExternalQuery(Args):
    query:str=Field(min_length=2,max_length=300)
class LearningResourceQuery(ExternalQuery):
    platform:Literal['bilibili','mooc']
class PracticeInput(Args):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    question:str=Field(min_length=1,max_length=2000,description='Markdown 题面，数学表达式用 $...$ 或独立成段的 $$...$$，多问各占一行。')
    expected_answer:str=Field(min_length=1,max_length=1000,description='客观短答填写可直接比对的纯文本答案；主观题参考答案中的数学表达式用 LaTeX 定界符。')
    source_ids:list[str]=Field(min_length=1,max_length=5)
    rubric:list[str]=Field(default_factory=list,max_length=6)
@dataclass(frozen=True)
class Spec:
    name:str
    summary:str
    arguments:type[BaseModel]
    def schema(self):
        return {'type':'function','function':{'name':self.name,'description':self.summary,'parameters':self.arguments.model_json_schema()}}
SPECS={s.name:s for s in [Spec('search_tools','查询可用工具摘要，不执行实际操作',Search),
    Spec('load_tools','加载工具定义供下一轮调用',Load),
    Spec('query_course_knowledge','课程知识查询：detail答疑，overview顺序读范围；next_cursor表示尚需继续读取，引用source_id。',Knowledge),
    Spec('get_resource_status','读取当前课程资料解析与索引状态',Args),
    Spec('create_practice_question','按学生要求及课件证据出题；客观短答 rubric 留空，主观题填 1 至 6 条可独立评分的标准',PracticeInput),
    Spec('external_search','通过已配置的MCP服务搜索外部网页，结果需与课程证据区分',ExternalQuery),
    Spec('search_learning_resources','推荐B站视频、中国大学MOOC课程或公开课件链接。选择平台，query只填公开主题关键词及资源类型。摘要仅用于判断相关性。',LearningResourceQuery),
    Spec('video_search','通过已配置的MCP服务搜索学习视频，只引用返回的真实信息',ExternalQuery)]}
# Course QA is the core capability, so it must not depend on tool discovery succeeding.
BASE=['search_tools','load_tools','query_course_knowledge','get_resource_status']

def available(context):
    from dovideo.mcp.client import configured
    names={'query_course_knowledge','get_resource_status'}
    if context.get('run_id'):
        names.add('create_practice_question')
    names.update(configured().keys())
    if 'external_search' in names:
        names.add('search_learning_resources')
    return names

def discover(query,context):
    names=available(context)
    terms={'query_course_knowledge':'课程 资料 知识 章节 课件 复习',
           'get_resource_status':'资料 解析 上传 索引 状态',
           'create_practice_question':'出题 练习 测验 自测',
           'external_search':'外部 网络 网页 搜索 最新',
           'video_search':'视频 观看 B站 慕课 课程',
           'search_learning_resources':'推荐 视频 B站 bilibili 慕课 mooc 课件 学习资源'}
    matched=[n for n in names if any(word in query.lower() for word in terms[n].lower().split())]
    if not matched:matched=sorted(names)
    return [{'name':n,'summary':SPECS[n].summary} for n in matched[:5]]
def execute(name,args,loaded,context):
    if name not in SPECS or name not in loaded:return {'status':'error','code':'TOOL_NOT_LOADED'}
    data=SPECS[name].arguments.model_validate(args).model_dump()
    if name=='search_tools':return {'status':'ok','tools':discover(data['query'],context)}
    if name=='load_tools':
        if any(n not in available(context) for n in data['names']):return {'status':'error','code':'TOOL_UNAVAILABLE'}
        loaded[:]=list(dict.fromkeys(loaded+data['names']))
        return {'status':'ok','loaded':data['names']}
    if name in ('external_search','video_search'):
        from dovideo.mcp.client import invoke
        return {'status':'ok','source':'external_mcp','data':invoke(name,data['query'])}
    if name=='search_learning_resources':
        from dovideo.mcp.client import invoke
        return {'status':'ok','source':'external_mcp',
                'data':invoke('external_search',data['query'],data['platform'])}
    if name=='create_practice_question':
        if name not in available(context):
            return {'status':'error','code':'TOOL_UNAVAILABLE'}
        import uuid
        from dovideo.db import session_scope
        from dovideo.models import AgentRun,PracticeQuestion
        refs=context.get('references',{})
        ids=list(dict.fromkeys(data['source_ids']))
        if any(not criterion.strip() or len(criterion)>300 for criterion in data['rubric']):
            return {'status':'error','code':'INVALID_RUBRIC'}
        if any(not refs.get(key,{}).get('resource_id') for key in ids):
            return {'status':'error','code':'COURSE_EVIDENCE_REQUIRED'}
        question_id=uuid.uuid5(context['run_id'],context['tool_call_id'])
        with session_scope(context['storage'].engine) as session:
            run=session.get(AgentRun,context['run_id'],with_for_update=True)
            if run.state!='RUNNING' or run.cancel_requested or run.lease_token!=context['lease_token']:
                return {'status':'error','code':'RUN_NOT_ACTIVE'}
            row=session.get(PracticeQuestion,question_id)
            if row is None:
                row=PracticeQuestion(id=question_id,run_id=run.id,question=data['question'],
                    expected_answer=data['expected_answer'],evidence=[refs[key] for key in ids],rubric=data['rubric'])
                session.add(row)
            return {'status':'ok','question_id':str(question_id),'question':row.question}
    from dovideo.db import session_scope
    from dovideo.models import User
    with session_scope(context['storage'].engine) as session:
        user=session.get(User,context['user_id'])
        if name=='get_resource_status':
            from dovideo.knowledge import status
            return {'status':'ok','data':status(session,user,context['course_id'])}
        from dovideo.course_knowledge import query_course_knowledge
        options={'debug':context['retrieval_trace']} if 'retrieval_trace' in context else {}
        return {'status':'ok','data':query_course_knowledge(session,context['storage'],user,context['course_id'],**data,token_budget=2048,page_units=4,**options)}
