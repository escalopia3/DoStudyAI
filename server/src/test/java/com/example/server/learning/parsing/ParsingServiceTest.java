package com.example.server.learning.parsing;

import com.example.server.learning.CourseRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.transaction.*;
import org.springframework.transaction.support.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class ParsingServiceTest {
    static class Database extends CourseRepository {
        Map<String,Object> row;
        Map<String,Object> resourceRow;
        final Map<String,Map<String,Object>> jobRows=new HashMap<>();
        final List<List<Object>> writes=new ArrayList<>();
        Database(){super(null);}
        @Override public List<Map<String,Object>> rows(String sql,Object... args) {
            if(sql.startsWith("SELECT r.*") && resourceRow!=null) return List.of(resourceRow);
            if(sql.startsWith("SELECT * FROM learning_parse_jobs") && args.length>0 && jobRows.containsKey(args[0].toString())) return List.of(jobRows.get(args[0].toString()));
            return sql.startsWith("SELECT * FROM learning_parse_jobs") && row!=null ? List.of(row) : List.of();
        }
        @Override public int update(String sql,Object... args) {
            var values=new ArrayList<Object>();values.add(sql);values.addAll(Arrays.asList(args));writes.add(values);return 1;
        }
    }
    static class Transactions implements PlatformTransactionManager {
        int commits,rollbacks;
        public TransactionStatus getTransaction(TransactionDefinition definition){return new SimpleTransactionStatus();}
        public void commit(TransactionStatus status){commits++;}
        public void rollback(TransactionStatus status){rollbacks++;}
    }
    final Database db=new Database();
    final Transactions manager=new Transactions();
    final ParsingService service=new ParsingService(db,new TransactionTemplate(manager),null,new ObjectMapper());
    Map<String,Object> job(String state,int seq) {
        var j=new HashMap<String,Object>();
        j.put("id","job-00000001");j.put("resource_id",1L);j.put("user_id",2L);j.put("course_id",3L);
        j.put("source_revision","rev1");j.put("source_type","PDF");j.put("state",state);
        j.put("sequence_no",seq);j.put("cancel_requested",false);return j;
    }
    Map<String,Object> event(String state,int seq) {
        return Map.of("jobId","job-00000001","resourceId","1","sourceRevision","rev1","sequence",seq,"state",state);
    }
    @Test void deniesForeignResource() {
        assertThrows(NoSuchElementException.class,()->service.create(2,1));
        assertTrue(db.writes.isEmpty());
    }
    @Test void rejectsBadEventStateAndSequence() {
        assertThrows(IllegalArgumentException.class,()->service.event(event("UNKNOWN",1)));
        assertThrows(IllegalArgumentException.class,()->service.event(event("PARSED",0)));
        assertTrue(db.writes.isEmpty());
    }
    @Test void ignoresOutOfOrderCallbacks() {
        db.row=job("RUNNING",3);service.event(event("QUEUED",2));assertTrue(db.writes.isEmpty());
    }
    @Test void terminalStateCannotBeOverwritten() {
        db.row=job("READY",3);service.event(event("FAILED",4));assertTrue(db.writes.isEmpty());
    }
    @Test void rejectsMismatchedRevision() {
        db.row=job("RUNNING",2);db.row.put("source_revision","rev2");
        assertThrows(IllegalArgumentException.class,()->service.event(event("FAILED",3)));
        assertTrue(db.writes.isEmpty());assertEquals(1,manager.rollbacks);
    }
    @Test void cancelledRequestRejectsLateCompletion() {
        db.row=job("RUNNING",2);db.row.put("cancel_requested",true);
        service.event(event("PARSED",3));assertTrue(db.writes.isEmpty());
    }
    @Test void failureUpdatesJobAndResourceInTransaction() {
        db.row=job("RUNNING",2);service.event(event("FAILED",3));
        assertEquals(2,db.writes.size());assertEquals(1,manager.commits);
        assertEquals("FAILED",db.writes.getFirst().get(1));
        assertTrue(db.writes.get(1).getFirst().toString().contains("parsing_job_id=?"));
    }
    @Test void serviceAuthenticationFailsClosed() {
        var client=new PythonParsingClient("http://localhost:8091","x".repeat(32),new ObjectMapper());
        assertFalse(client.authenticated(null));assertFalse(client.authenticated("Bearer wrong"));
        assertTrue(client.authenticated("Bearer "+"x".repeat(32)));
        assertThrows(IllegalArgumentException.class,()->new PythonParsingClient("http://localhost","",new ObjectMapper()));
    }
    @Test void duplicateRetryOfOldJobReturnsAlreadyCreatedSuccessor() {
        var old=job("FAILED",3);
        var next=job("FAILED",3);next.put("id","job-00000002");
        db.jobRows.put("job-00000001",old);db.jobRows.put("job-00000002",next);
        db.resourceRow=new HashMap<>(Map.of("id",1L,"user_id",2L,"course_id",3L,"type","PDF",
            "object_key","learning/2/file.pdf","size_bytes",100L,"parsing_job_id","job-00000002"));
        assertEquals("job-00000002",service.retry(2L,"job-00000001").get("jobId"));
        assertTrue(db.writes.isEmpty());
    }
    @Test void internalControllerAuthenticatesBeforeReadingSource() {
        var client=new PythonParsingClient("http://localhost:8091","x".repeat(32),new ObjectMapper());
        var controller=new ParsingController(service,client,null);
        var error=assertThrows(com.example.server.exception.BusinessException.class,()->controller.source(null,"job-00000001"));
        assertEquals(com.example.server.common.ErrorCode.UNAUTHORIZED,error.errorCode());
    }
}
