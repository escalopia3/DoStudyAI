package com.example.server.learning.agent;

import com.example.server.learning.CourseRepository;
import com.example.server.learning.progress.LearningMemoryService;
import com.example.server.learning.progress.LearningPracticeService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import java.time.*;
import java.util.*;

@Service
@ConditionalOnProperty(name="learning.parsing.enabled",havingValue="true")
public class LearningAgentService {
    static final Set<String> SUPPORTED_MODES=Set.of(
        "QA","TUTORING","NOTES","KEY_POINTS","REVIEW","PRACTICE","MOCK_EXAM");
    private final CourseRepository db;private final TransactionTemplate tx;private final ObjectMapper mapper;
    private final LearningAuthorizationService authorization;private final PythonLearningAgentClient python;
    private final LearningMemoryService memories;private final LearningPracticeService practices;
    public LearningAgentService(CourseRepository db,TransactionTemplate tx,ObjectMapper mapper,
        LearningAuthorizationService authorization,PythonLearningAgentClient python,LearningMemoryService memories,
        LearningPracticeService practices){this.db=db;this.tx=tx;this.mapper=mapper;this.authorization=authorization;this.python=python;this.memories=memories;this.practices=practices;}
    public Map<String,Object> createConversation(long user,long course,String title){
        authorization.course(user,course);String id=UUID.randomUUID().toString();String safe=title==null||title.isBlank()?"新学习会话":title.strip();
        if(safe.length()>200)safe=safe.substring(0,200);db.update("INSERT INTO learning_conversations(id,user_id,course_id,title) VALUES(?,?,?,?)",id,user,course,safe);
        return Map.of("conversationId",id,"courseId",Long.toString(course),"title",safe);
    }
    public List<Map<String,Object>> conversations(long user,long course){authorization.course(user,course);return db.rows("SELECT id,title,created_at,updated_at FROM learning_conversations WHERE user_id=? AND course_id=? ORDER BY updated_at DESC",user,course);}
    public List<Map<String,Object>> messages(long user,String conversation){
        owned(user,conversation);var messages=db.rows("SELECT id,role,mode,content,status,created_at FROM learning_messages WHERE conversation_id=? ORDER BY created_at,id",conversation);
        for(var message:messages)message.put("citations",db.rows("SELECT ordinal_no,source_id,resource_id,index_revision,chunk_id,parent_id,content_hash,title_path_json,locator_json,quote_text FROM learning_message_citations WHERE message_id=? ORDER BY ordinal_no",message.get("id")));
        return messages;
    }
    public Map<String,Object> ask(long user,String conversation,String question,String mode,List<String> selected){
        if(question==null||question.isBlank()||question.length()>4000)throw new IllegalArgumentException("问题长度无效");
        var c=owned(user,conversation);long course=((Number)c.get("course_id")).longValue();
        String agentMode=normalizeMode(mode);
        var resources=authorization.readyResources(user,course,selected);if(resources.isEmpty())throw new IllegalStateException("当前课程没有可检索的就绪资料");
        String run=UUID.randomUUID().toString(),userMessage=UUID.randomUUID().toString(),assistant=UUID.randomUUID().toString();
        double deadline=Instant.now().plusSeconds(90).toEpochMilli()/1000.0;
        Map<String,Object> payload;
        try{payload=tx.execute(status->{
            db.rows("SELECT id FROM learning_conversations WHERE id=? AND user_id=? FOR UPDATE",conversation,user);
            if(!db.rows("SELECT id FROM learning_agent_runs WHERE conversation_id=? AND state IN ('QUEUED','RUNNING') LIMIT 1",conversation).isEmpty())
                throw new IllegalStateException("当前会话已有回答正在生成");
            db.update("INSERT INTO learning_messages(id,conversation_id,role,mode,content,status) VALUES(?,?,'user',?,?,'COMPLETED')",userMessage,conversation,agentMode,question.strip());
            db.update("INSERT INTO learning_messages(id,conversation_id,role,mode,content,status) VALUES(?,?,'assistant',?,'','QUEUED')",assistant,conversation,agentMode);
            db.update("INSERT INTO learning_agent_runs(id,conversation_id,user_message_id,assistant_message_id,user_id,course_id,state,authorized_resources_json,deadline_at) VALUES(?,?,?,?,?,?,'QUEUED',?,FROM_UNIXTIME(?))",
                run,conversation,userMessage,assistant,user,course,json(resources),deadline);
            return requestPayload(run,conversation,user,course,agentMode,question.strip(),resources,deadline,userMessage);
        });}catch(RuntimeException e){throw e;}
        try{python.submit(payload);}catch(RuntimeException error){
            tx.executeWithoutResult(status->{db.update("UPDATE learning_agent_runs SET state='FAILED',error_code='AGENT_DISPATCH_FAILED' WHERE id=? AND state='QUEUED'",run);db.update("UPDATE learning_messages SET status='FAILED' WHERE id=? AND status='QUEUED'",assistant);});
            throw error;
        }
        return Map.of("runId",run,"assistantMessageId",assistant,"state","QUEUED");
    }
    public Map<String,Object> run(long user,String id){var rows=db.rows("SELECT * FROM learning_agent_runs WHERE id=? AND user_id=?",id,user);if(rows.isEmpty())throw new NoSuchElementException("运行不存在");return rows.getFirst();}
    public void cancel(long user,String id){var row=run(user,id);if(!Set.of("COMPLETED","FAILED","CANCELLED","TIMED_OUT","BUDGET_EXCEEDED").contains(row.get("state"))){python.cancel(id);db.update("UPDATE learning_agent_runs SET state='CANCELLED' WHERE id=? AND user_id=?",id,user);db.update("UPDATE learning_messages SET status='CANCELLED' WHERE id=?",row.get("assistant_message_id"));}}
    public void event(Map<String,Object> event){
        String id=Objects.toString(event.get("runId"),"");Object sequence=event.get("sequence");if(!(sequence instanceof Number n))throw new IllegalArgumentException("Invalid sequence");
        tx.executeWithoutResult(status->{var rows=db.rows("SELECT * FROM learning_agent_runs WHERE id=? FOR UPDATE",id);if(rows.isEmpty())throw new NoSuchElementException("运行不存在");var run=rows.getFirst();
            if(((Number)run.get("sequence_no")).longValue()>=n.longValue()||Set.of("COMPLETED","FAILED","CANCELLED","TIMED_OUT","BUDGET_EXCEEDED").contains(run.get("state")))return;
            String state=Objects.toString(event.get("state"),"");if(!Set.of("QUEUED","RUNNING","COMPLETED","FAILED","CANCELLED","TIMED_OUT","BUDGET_EXCEEDED").contains(state))throw new IllegalArgumentException("Invalid state");
            db.update("UPDATE learning_agent_runs SET state=?,sequence_no=?,error_code=? WHERE id=?",state,n.intValue(),event.get("errorCode"),id);
            if("COMPLETED".equals(state))complete(run,event.get("result"));
            if(Set.of("FAILED","CANCELLED","TIMED_OUT","BUDGET_EXCEEDED").contains(state))db.update("UPDATE learning_messages SET status=? WHERE id=?",state,run.get("assistant_message_id"));
        });
    }
    @SuppressWarnings("unchecked") private void complete(Map<String,Object> run,Object raw){
        if(!(raw instanceof Map<?,?> value))throw new IllegalArgumentException("Missing agent result");
        String answer=Objects.toString(value.get("answer"),"");if(answer.isBlank())throw new IllegalArgumentException("Empty agent answer");
        String assistant=run.get("assistant_message_id").toString();
        List<String> authorized;try{authorized=mapper.readValue(run.get("authorized_resources_json").toString(),List.class);}catch(Exception e){throw new IllegalStateException("Stored authorization invalid",e);}
        db.update("DELETE FROM learning_message_citations WHERE message_id=?",assistant);
        Object rawCitations=value.get("citations");int ordinal=1;Set<String> validSources=new LinkedHashSet<>();
        if(rawCitations instanceof List<?> citations)for(Object item:citations){
            if(!(item instanceof Map<?,?> citation))throw new IllegalArgumentException("Invalid citation");
            String resource=Objects.toString(citation.get("resourceId"),""),revision=Objects.toString(citation.get("indexRevision"),"");
            if(!authorized.contains(resource)||db.rows("SELECT r.id FROM learning_resources r JOIN course_resources cr ON cr.resource_id=r.id JOIN ai_active_knowledge_indexes a ON CAST(a.resource_id AS UNSIGNED)=r.id AND a.index_revision=? WHERE r.id=? AND r.user_id=? AND cr.course_id=? AND r.parse_status='READY'",revision,resource,run.get("user_id"),run.get("course_id")).isEmpty())
                throw new IllegalArgumentException("Citation authorization or version mismatch");
            String source=Objects.toString(citation.get("sourceId"),"");if(!source.matches("S[1-9][0-9]*"))throw new IllegalArgumentException("Invalid citation source ID");
            if(!validSources.add(source))throw new IllegalArgumentException("Duplicate citation source ID");
            db.update("INSERT INTO learning_message_citations(message_id,ordinal_no,source_id,resource_id,index_revision,chunk_id,parent_id,content_hash,title_path_json,locator_json,quote_text) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                assistant,ordinal++,source,resource,revision,citation.get("chunkId"),citation.get("parentId"),citation.get("contentHash"),json(citation.get("titlePath")),json(citation.get("locators")),Objects.toString(citation.get("content"),""));
        }
        if(value.get("practice") instanceof Map<?,?> practice){
            var questions=db.rows("SELECT content FROM learning_messages WHERE id=?",run.get("user_message_id"));
            String request=questions.isEmpty()?"":Objects.toString(questions.getFirst().get("content"),"");
            practices.persistGenerated(run,practice,request,Objects.toString(value.get("knowledgeSnapshotId"),""),validSources);
        }
        Map<String,Object> usage=value.get("usage") instanceof Map<?,?> u?(Map<String,Object>)u:Map.of();
        db.update("UPDATE learning_messages SET content=?,status='COMPLETED' WHERE id=?",answer,assistant);
        db.update("UPDATE learning_agent_runs SET knowledge_snapshot_id=?,model=?,input_tokens=?,output_tokens=?,completed_at=CURRENT_TIMESTAMP(3) WHERE id=?",
            value.get("knowledgeSnapshotId"),usage.get("model"),number(usage.get("inputTokens")),number(usage.get("outputTokens")),run.get("id"));
    }
    private int number(Object value){return value instanceof Number n?n.intValue():0;}
    static String normalizeMode(String mode){return mode!=null&&SUPPORTED_MODES.contains(mode)?mode:"QA";}
    private Map<String,Object> owned(long user,String id){var rows=db.rows("SELECT * FROM learning_conversations WHERE id=? AND user_id=?",id,user);if(rows.isEmpty())throw new NoSuchElementException("会话不存在");return rows.getFirst();}
    private Map<String,Object> requestPayload(String run,String conversation,long user,long course,String mode,String question,List<String> resources,double deadline,String currentMessage){
        var history=db.rows("SELECT role,content FROM learning_messages WHERE conversation_id=? AND id<>? AND status='COMPLETED' ORDER BY created_at DESC LIMIT 12",conversation,currentMessage);Collections.reverse(history);
        var payload=new LinkedHashMap<String,Object>();
        payload.put("schemaVersion","1");payload.put("runId",run);payload.put("conversationId",conversation);
        payload.put("userId",Long.toString(user));payload.put("courseId",Long.toString(course));payload.put("mode",mode);
        payload.put("question",question);payload.put("authorizedResourceIds",resources);payload.put("history",history);
        payload.put("memories",memories.activeForAgent(user,course));payload.put("deadlineAt",deadline);
        return payload;
    }
    private String json(Object value){try{return mapper.writeValueAsString(value);}catch(Exception e){throw new IllegalStateException("JSON serialization failed",e);}}
}
