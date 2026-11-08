"""Small, deterministic teaching policies and explicit memory candidate rules."""
import re
import hashlib

def teaching_policy(message):
    for words, policy in (
        (('考前','期末','复习计划'), '先确认范围和可用时间，再按课程覆盖安排复习，并安排一次自测。'),
        (('预习',), '先通览所选资料，梳理知识架构和前置知识，再沿框架讲解核心概念、例子和自检问题。'),
        (('出题','练习','测验','自测','主观题'), '先查询课程资料。用 create_practice_question 保存题目；题面和主观题参考答案使用 Markdown 和 LaTeX，多问分别用列表项，公式用 $...$ 或独立成段的 $$...$$。要求再出题时，避开对话中已有题目，改变考查角度或构造新的例子。客观短答使用唯一纯文本答案，主观题需要逐条评分标准。保存成功后，在对话中简短说明考查点并附来源，题面在自测区展示，暂不揭晓答案。'),
    ):
        if any(word in message for word in words):
            return policy
    return '按本轮要求选择讲解深度，优先讲清关键一步。'

def memory_candidate(message):
    facts=memory_facts(message)
    for fact in facts:
        if fact['kind'] in ('goal','difficulty'):return fact['kind'],fact['content']
    return None

def memory_facts(message):
    """Extract explicit first-person learning declarations; never infer mastery."""
    text=message.strip()
    if re.search(r'[？?]|假设|如果|例如|比如|请翻译|不要记录|请勿记录|不要记住|别记住|他说|她说|老师说',text):return []
    if text.startswith(('“','"','\'')):return []
    if re.match(r'(这次|本轮|本题|这道题|今天先|仅本次)',text):return []
    text=re.sub(r'^请记住\s*[，,:：]?\s*','',text)
    text=re.sub(r'^(?:刚才说错了|更正一下|更正)\s*[，,:：]\s*','',text)
    text=re.sub(r'[。\s]*以后请记住[。\s]*$','',text)
    patterns=[('goal',r'我(?:的(?:学习)?目标(?:是|改为|改成|现在是)|想在本课程中学会|想学会|想学|希望学会)[：:]?\s*(.+)'),
        ('difficulty',r'我(?:一直不理解|反复搞不懂|总是弄不懂|总是搞不懂|总是把|总把)[：:]?\s*(.+)'),
        ('progress',r'我(?:现在)?((?:已经|还没有|还没|尚未|已)?学(?:完|到|会).+)')]
    for kind,pattern in patterns:
        match=re.fullmatch(pattern,text.rstrip('。'))
        if not match:continue
        content=match[1].strip()
        if not 3<=len(content)<=500 or '\n' in content or '。' in content:return []
        key=kind+'.current' if kind in ('goal','progress') else 'difficulty.'+hashlib.sha256(content.encode()).hexdigest()[:24]
        return [{'kind':kind,'key':key,'content':content,'source':'explicit_user_statement'}]
    # Only persistent wording changes a saved presentation preference.
    match=re.fullmatch(r'(?:我希望)?(?:以后|今后)(?:都|请)?(.{3,200})[。]?',text)
    if match and any(w in match[1] for w in ('讲解','解释','结论','简短','详细','例子','中文','英文')):
        return [{'kind':'preference','key':'explanation_style','content':match[1].rstrip('。'),'source':'explicit_user_preference'}]
    return []
