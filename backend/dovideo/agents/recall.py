"""Local, deterministic lexical recall and source-preserving excerpts."""
import math
import re
import unicodedata
from datetime import timezone

STOP={'我的','我们','什么','怎么','哪些','这个','那个','之前','刚才','请问','回答','解释','学习','课程','保存','记录','输出','只有','只输','出代','代号','本次','问题','信息','进行','一个'}

def chronological(value):
    return value.replace(tzinfo=timezone.utc).timestamp() if value.tzinfo is None else value.timestamp()

def terms(text):
    text=unicodedata.normalize('NFKC',str(text)).lower()
    result=set(re.findall(r'[a-z0-9][a-z0-9_-]{1,}',text))
    for word in re.findall(r'[\u3400-\u9fff]+',text):
        result.update(word[i:i+2] for i in range(len(word)-1))
    return result-STOP

def relevance(query,text):
    wanted=terms(query);found=terms(text)
    overlap=wanted&found
    return len(overlap)/math.sqrt(max(1,len(wanted))*max(1,len(found)))

def excerpt(text,query='',limit=700):
    """Return original substrings, including relevant middle/tail sentences."""
    text=str(text)
    if len(text)<=limit:return text
    pieces=[s for s in re.split(r'(?<=[。！？；\n])',text) if s.strip()]
    ranked=sorted(enumerate(pieces),key=lambda p:(relevance(query,p[1]),p[0]),reverse=True)
    chosen=[];used=0
    for index,piece in ranked:
        if used+len(piece)<=limit:
            chosen.append((index,piece));used+=len(piece)
    if chosen:return ' […] '.join(p for _,p in sorted(chosen))
    # One very long sentence: centre an exact source window on a query match.
    matches=[text.lower().find(t) for t in terms(query) if t in text.lower()]
    start=max(0,(min(matches) if matches else 0)-limit//3)
    return ('[…] ' if start else '')+text[start:start+limit]+(' […]' if start+limit<len(text) else '')
