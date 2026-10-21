package com.example.server.learning.progress;

import com.example.server.learning.CourseRepository;
import com.example.server.learning.agent.LearningAuthorizationService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.*;

@Service
public class LearningMemoryService {
    static final Set<String> TYPES=Set.of("PREFERENCE","WEAKNESS","MASTERY","LEARNING_GOAL");
    private final CourseRepository db;
    private final LearningAuthorizationService authorization;
    private final ObjectMapper mapper;

    public LearningMemoryService(CourseRepository db,LearningAuthorizationService authorization,ObjectMapper mapper){
        this.db=db;this.authorization=authorization;this.mapper=mapper;
    }

    public List<Map<String,Object>> list(long user,long course){
        authorization.course(user,course);
        return db.rows("SELECT id,memory_type,content,source_type,source_ref,confidence,status,user_confirmed,expires_at,created_at,updated_at FROM learning_memory_items WHERE user_id=? AND course_id=? AND status='ACTIVE' AND (expires_at IS NULL OR expires_at>CURRENT_TIMESTAMP(3)) ORDER BY user_confirmed DESC,updated_at DESC",user,course);
    }

    public Map<String,Object> create(long user,long course,String type,String content){
        authorization.course(user,course);String safeType=type(type),safeContent=content(content);String id=UUID.randomUUID().toString();
        db.update("INSERT INTO learning_memory_items(id,user_id,course_id,memory_type,content,source_type,confidence,status,user_confirmed) VALUES(?,?,?,?,?,'USER',1.0,'ACTIVE',1)",id,user,course,safeType,safeContent);
        event(id,user,course,"CREATED",Map.of("type",safeType,"content",safeContent,"sourceType","USER"));
        return owned(user,course,id);
    }

    public Map<String,Object> update(long user,long course,String id,String content){
        var existing=owned(user,course,id);String safe=content(content);
        db.update("UPDATE learning_memory_items SET content=?,user_confirmed=1,confidence=1.0,status='ACTIVE',expires_at=NULL WHERE id=? AND user_id=? AND course_id=?",safe,id,user,course);
        event(id,user,course,"UPDATED",Map.of("before",existing.get("content"),"content",safe));
        return owned(user,course,id);
    }

    public void delete(long user,long course,String id){
        var existing=owned(user,course,id);
        db.update("UPDATE learning_memory_items SET status='DELETED' WHERE id=? AND user_id=? AND course_id=?",id,user,course);
        event(id,user,course,"DELETED",Map.of("content",existing.get("content")));
    }

    public int clear(long user,long course){
        authorization.course(user,course);
        var active=db.rows("SELECT id,content FROM learning_memory_items WHERE user_id=? AND course_id=? AND status='ACTIVE'",user,course);
        int changed=db.update("UPDATE learning_memory_items SET status='DELETED' WHERE user_id=? AND course_id=? AND status='ACTIVE'",user,course);
        for(var item:active)event(item.get("id").toString(),user,course,"DELETED",Map.of("content",item.get("content"),"reason","USER_CLEAR"));
        return changed;
    }

    public List<Map<String,Object>> activeForAgent(long user,long course){
        authorization.course(user,course);
        return db.rows("SELECT memory_type AS type,content,CAST(confidence AS DOUBLE) AS confidence,user_confirmed AS userConfirmed FROM learning_memory_items WHERE user_id=? AND course_id=? AND status='ACTIVE' AND (expires_at IS NULL OR expires_at>CURRENT_TIMESTAMP(3)) ORDER BY user_confirmed DESC,confidence DESC,updated_at DESC LIMIT 20",user,course);
    }

    public void upsertSystem(long user,long course,String type,String sourceRef,String content,double confidence){
        String safeType=type(type),safeContent=content(content);double safeConfidence=Math.max(0,Math.min(1,confidence));
        var rows=db.rows("SELECT id FROM learning_memory_items WHERE user_id=? AND course_id=? AND memory_type=? AND source_type='MASTERY_RULE' AND source_ref=? LIMIT 1",user,course,safeType,sourceRef);
        if(rows.isEmpty()){
            String id=UUID.randomUUID().toString();
            db.update("INSERT INTO learning_memory_items(id,user_id,course_id,memory_type,content,source_type,source_ref,confidence,status,user_confirmed) VALUES(?,?,?,?,?,'MASTERY_RULE',?,?,'ACTIVE',0)",id,user,course,safeType,safeContent,sourceRef,safeConfidence);
            event(id,user,course,"CREATED",Map.of("type",safeType,"content",safeContent,"sourceType","MASTERY_RULE"));
        }else{
            String id=rows.getFirst().get("id").toString();
            db.update("UPDATE learning_memory_items SET content=?,confidence=?,status='ACTIVE' WHERE id=?",safeContent,safeConfidence,id);
            event(id,user,course,"REFRESHED",Map.of("type",safeType,"content",safeContent,"confidence",safeConfidence));
        }
    }

    public void retireSystem(long user,long course,String type,String sourceRef){
        var rows=db.rows("SELECT id FROM learning_memory_items WHERE user_id=? AND course_id=? AND memory_type=? AND source_type='MASTERY_RULE' AND source_ref=? AND status='ACTIVE'",user,course,type,sourceRef);
        for(var row:rows){String id=row.get("id").toString();db.update("UPDATE learning_memory_items SET status='RETIRED' WHERE id=?",id);event(id,user,course,"RETIRED",Map.of("reason","MASTERY_CHANGED"));}
    }

    private Map<String,Object> owned(long user,long course,String id){
        authorization.course(user,course);var rows=db.rows("SELECT id,memory_type,content,source_type,source_ref,confidence,status,user_confirmed,expires_at,created_at,updated_at FROM learning_memory_items WHERE id=? AND user_id=? AND course_id=?",id,user,course);
        if(rows.isEmpty())throw new NoSuchElementException("学习记忆不存在");return rows.getFirst();
    }
    static String type(String value){if(value==null||!TYPES.contains(value))throw new IllegalArgumentException("不支持的记忆类型");return value;}
    static String content(String value){if(value==null||value.isBlank()||value.strip().length()>1000)throw new IllegalArgumentException("记忆内容不能为空且不能超过1000字");return value.strip();}
    private void event(String id,long user,long course,String action,Object snapshot){db.update("INSERT INTO learning_memory_events(memory_id,user_id,course_id,action,snapshot_json) VALUES(?,?,?,?,?)",id,user,course,action,json(snapshot));}
    private String json(Object value){try{return mapper.writeValueAsString(value);}catch(Exception e){throw new IllegalStateException("JSON serialization failed",e);}}
}
