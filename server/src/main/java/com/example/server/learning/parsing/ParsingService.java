package com.example.server.learning.parsing;

import com.example.server.learning.CourseRepository;
import com.example.server.service.AgentCheckpointService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

@Service
@ConditionalOnProperty(name="learning.parsing.enabled", havingValue="true")
public class ParsingService {
    private final CourseRepository db;
    private final TransactionTemplate tx;
    private final AgentCheckpointService checkpoints;
    private final ObjectMapper mapper;
    public ParsingService(CourseRepository db,TransactionTemplate tx,AgentCheckpointService checkpoints,ObjectMapper mapper) {
        this.db=db;this.tx=tx;this.checkpoints=checkpoints;this.mapper=mapper;
    }
    public Map<String,Object> resource(long user,long resource) {
        var rows=db.rows("SELECT r.*,cr.course_id FROM learning_resources r JOIN course_resources cr ON cr.resource_id=r.id JOIN courses c ON c.id=cr.course_id AND c.user_id=r.user_id WHERE r.id=? AND r.user_id=?",resource,user);
        if(rows.isEmpty()) throw new NoSuchElementException("资料不存在或无权访问");
        var row=rows.getFirst();
        if(row.get("media_id")!=null && db.rows("SELECT id FROM media_files WHERE id=? AND user_id=?",row.get("media_id"),user).isEmpty())
            throw new NoSuchElementException("视频来源已失效");
        return row;
    }
    public Map<String,Object> create(long user,long resourceId) {
        return create(user,resourceId,null);
    }
    public Map<String,Object> retry(long user,String id) {
        var j=owned(user,id);
        return create(user,((Number)j.get("resource_id")).longValue(),id);
    }
    private Map<String,Object> create(long user,long resourceId,String retryOf) {
        var resource=resource(user,resourceId);
        String type=resource.get("type").toString();
        if(!Set.of("PDF","DOCX","PPTX","VIDEO").contains(type)) throw new IllegalArgumentException("Unsupported source format");
        String context=null;
        if(type.equals("VIDEO")) {
            var value=checkpoints.loadContext(((Number)resource.get("media_id")).longValue());
            if(value==null) throw new IllegalStateException("视频上下文尚未就绪，请先完成视频转写/分析");
            try { context=mapper.writeValueAsString(value); } catch(Exception e) { throw new IllegalStateException("Context serialization failed",e); }
        }
        final String savedContext=context;
        String revision=hash(type.equals("VIDEO")?context:Objects.toString(resource.get("object_key"),"") + ":" + resource.get("size_bytes"));
        return tx.execute(status -> {
            db.rows("SELECT id FROM learning_resources WHERE id=? FOR UPDATE",resourceId);
            var current=resource(user,resourceId);
            if(!Objects.equals(current.get("object_key"),resource.get("object_key")) || !Objects.equals(current.get("course_id"),resource.get("course_id")))
                throw new IllegalStateException("资料已变化，请重试");
            if(current.get("parsing_job_id")!=null) {
                var existing=job(current.get("parsing_job_id").toString());
                if(retryOf!=null && !retryOf.equals(existing.get("id"))) return view(existing);
                if(revision.equals(existing.get("source_revision")) &&
                    (retryOf==null || !Set.of("FAILED","CANCELLED").contains(existing.get("state")))) return view(existing);
            }
            String id=UUID.randomUUID().toString();
            db.update("INSERT INTO learning_parse_jobs(id,resource_id,user_id,course_id,source_revision,source_type,video_context) VALUES(?,?,?,?,?,?,?)",id,resourceId,user,resource.get("course_id"),revision,type,savedContext);
            db.update("INSERT INTO learning_parse_outbox(job_id) VALUES(?)",id);
            db.update("UPDATE learning_resources SET parse_status='QUEUED',parsing_job_id=? WHERE id=?",id,resourceId);
            return view(job(id));
        });
    }
    public Map<String,Object> job(String id) {
        var rows=db.rows("SELECT * FROM learning_parse_jobs WHERE id=?",id);
        if(rows.isEmpty()) throw new NoSuchElementException("任务不存在");
        return rows.getFirst();
    }
    public Map<String,Object> owned(long user,String id) {
        var job=job(id);
        if(((Number)job.get("user_id")).longValue()!=user) throw new NoSuchElementException("任务不存在");
        resource(user,((Number)job.get("resource_id")).longValue());
        return job;
    }
    public Map<String,Object> payload(Map<String,Object> j) {
        return Map.of("schemaVersion","1","jobId",j.get("id"),"resourceId",j.get("resource_id").toString(),
            "userId",j.get("user_id").toString(),"courseId",j.get("course_id").toString(),
            "sourceRevision",j.get("source_revision"),"sourceType",j.get("source_type"));
    }
    public Map<String,Object> source(String id) {
        var j=job(id);
        if(Boolean.TRUE.equals(j.get("cancel_requested")) || "CANCELLED".equals(j.get("state"))) throw new IllegalStateException("任务已取消");
        var r=resource(((Number)j.get("user_id")).longValue(),((Number)j.get("resource_id")).longValue());
        if(!id.equals(r.get("parsing_job_id"))) throw new IllegalStateException("任务已被更新任务替代");
        if(!r.get("course_id").toString().equals(j.get("course_id").toString())) throw new IllegalStateException("资料归属已变化");
        var result=new HashMap<String,Object>(payload(j));
        if("VIDEO".equals(j.get("source_type"))) {
            try { result.put("videoContext",mapper.readTree(j.get("video_context").toString())); }
            catch(Exception e) { throw new IllegalStateException("Stored context invalid",e); }
        } else {
            if(!hash(Objects.toString(r.get("object_key"),"")+":"+r.get("size_bytes")).equals(j.get("source_revision")))
                throw new IllegalStateException("资料版本已变化");
            result.put("objectKey",r.get("object_key"));
        }
        return result;
    }
    public void event(Map<String,Object> event) {
        String id=Objects.toString(event.get("jobId"),"");
        String state=Objects.toString(event.get("state"),"");
        if(!Set.of("QUEUED","RUNNING","PARSED","INDEXING","READY","FAILED","CANCELLED").contains(state)) throw new IllegalArgumentException("Invalid state");
        if(!(event.get("sequence") instanceof Number n) || n.longValue()<1 || n.doubleValue()!=n.longValue() || n.longValue()>Integer.MAX_VALUE)
            throw new IllegalArgumentException("Invalid sequence");
        tx.executeWithoutResult(status -> {
            var rows=db.rows("SELECT * FROM learning_parse_jobs WHERE id=? FOR UPDATE",id);
            if(rows.isEmpty()) throw new NoSuchElementException("任务不存在");
            var j=rows.getFirst();
            if(!j.get("resource_id").toString().equals(event.get("resourceId")) || !j.get("source_revision").equals(event.get("sourceRevision")))
                throw new IllegalArgumentException("Event source mismatch");
            if(((Number)j.get("sequence_no")).longValue()>=n.longValue() || Set.of("READY","FAILED","CANCELLED").contains(j.get("state"))) return;
            if(Boolean.TRUE.equals(j.get("cancel_requested")) && !state.equals("CANCELLED")) return;
            String prefix=event.get("artifactPrefix")==null?null:event.get("artifactPrefix").toString();
            if(Set.of("PARSED","INDEXING","READY").contains(state)) {
                source(id);
                String expected="learning-artifacts/"+j.get("resource_id")+"/"+j.get("source_revision")+"/"+id+"/";
                if(prefix==null || !prefix.startsWith(expected) || !prefix.substring(expected.length()).matches("[1-9][0-9]*"))
                    throw new IllegalArgumentException("Invalid artifact prefix");
            }
            String error=event.get("errorCode")==null?null:event.get("errorCode").toString();
            if(error!=null && error.length()>64) throw new IllegalArgumentException("Invalid error code");
            db.update("UPDATE learning_parse_jobs SET state=?,sequence_no=?,artifact_prefix=?,error_code=? WHERE id=?",state,n.intValue(),prefix,error,id);
            db.update("UPDATE learning_resources SET parse_status=? WHERE id=? AND parsing_job_id=?",state,j.get("resource_id"),id);
        });
    }
    public void requestCancel(long user,String id) {
        tx.executeWithoutResult(status -> {
            db.rows("SELECT id FROM learning_parse_jobs WHERE id=? FOR UPDATE",id);
            var j=owned(user,id);
            if(!Set.of("READY","FAILED","CANCELLED").contains(j.get("state"))) {
                db.update("UPDATE learning_parse_jobs SET cancel_requested=TRUE,state='CANCELLED' WHERE id=?",id);
                db.update("UPDATE learning_resources SET parse_status='CANCELLED' WHERE id=? AND parsing_job_id=?",j.get("resource_id"),id);
            }
        });
    }
    public Map<String,Object> view(Map<String,Object> j) {
        var result=new LinkedHashMap<String,Object>();
        result.put("jobId",j.get("id"));result.put("resourceId",j.get("resource_id").toString());
        result.put("state",j.get("state"));result.put("sequence",j.get("sequence_no"));
        result.put("artifactPrefix",j.get("artifact_prefix"));result.put("errorCode",j.get("error_code"));
        result.put("cancelRequested",j.get("cancel_requested"));return result;
    }
    static String hash(String text) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8))); }
        catch(Exception e) { throw new IllegalStateException(e); }
    }
}
