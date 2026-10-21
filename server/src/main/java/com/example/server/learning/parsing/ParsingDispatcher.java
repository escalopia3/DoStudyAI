package com.example.server.learning.parsing;

import com.example.server.learning.CourseRepository;
import org.apache.rocketmq.spring.core.RocketMQTemplate;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import java.util.HashMap;

@Component
@ConditionalOnProperty(name="learning.parsing.enabled", havingValue="true")
public class ParsingDispatcher {
    private static final Logger log=LoggerFactory.getLogger(ParsingDispatcher.class);
    private final CourseRepository db;
    private final ParsingService service;
    private final PythonParsingClient python;
    private final RocketMQTemplate mq;
    private final String topic;
    private final boolean autoEnqueue;
    public ParsingDispatcher(CourseRepository db,ParsingService service,PythonParsingClient python,RocketMQTemplate mq,
        @Value("${learning.parsing.topic:learning-parse}") String topic,
        @Value("${learning.parsing.auto-enqueue:true}") boolean autoEnqueue) {
        this.db=db;this.service=service;this.python=python;this.mq=mq;this.topic=topic;this.autoEnqueue=autoEnqueue;
    }
    // Uploaded resources are durable pending work: scanning also repairs a crash after upload commit.
    @Scheduled(fixedDelayString="${learning.parsing.scan-ms:5000}")
    public void enqueueUploads() {
        if (!autoEnqueue) return;
        for(var r:db.rows("SELECT r.id,r.user_id FROM learning_resources r JOIN course_resources cr ON cr.resource_id=r.id WHERE r.type IN ('PDF','DOCX','PPTX') AND r.parse_status='UPLOADED' AND NOT EXISTS (SELECT 1 FROM learning_parse_jobs j WHERE j.resource_id=r.id) ORDER BY r.id LIMIT 20")) {
            try {service.create(((Number)r.get("user_id")).longValue(),((Number)r.get("id")).longValue());}
            catch(RuntimeException e) {log.warn("parse_enqueue_failed resourceId={}",r.get("id"),e);}
        }
    }
    @Scheduled(fixedDelayString="${learning.parsing.dispatch-ms:3000}")
    public void dispatch() {
        for(var out:db.rows("SELECT job_id,attempts FROM learning_parse_outbox WHERE delivered=FALSE AND attempts<20 AND next_attempt_at<=CURRENT_TIMESTAMP(3) ORDER BY next_attempt_at LIMIT 20")) {
            String id=out.get("job_id").toString();
            try {
                mq.syncSend(topic,id,5000);
                db.update("UPDATE learning_parse_outbox SET delivered=TRUE WHERE job_id=?",id);
            } catch(RuntimeException e) {
                int attempts=((Number)out.get("attempts")).intValue()+1;
                db.update("UPDATE learning_parse_outbox SET attempts=attempts+1,next_attempt_at=TIMESTAMPADD(SECOND,?,CURRENT_TIMESTAMP(3)) WHERE job_id=?",Math.min(3600,1<<Math.min(attempts,12)),id);
                log.warn("parse_delivery_failed jobId={}",id,e);
            }
        }
    }
    // Reconcile lost callbacks and MQ delivery failures; Python submit is idempotent.
    @Scheduled(fixedDelayString="${learning.parsing.reconcile-ms:30000}")
    public void reconcile() {
        for(var j:db.rows("SELECT * FROM learning_parse_jobs WHERE (state IN ('QUEUED','RUNNING','PARSED','INDEXING') OR cancel_requested=TRUE) AND updated_at<TIMESTAMPADD(SECOND,-20,CURRENT_TIMESTAMP(3)) ORDER BY updated_at LIMIT 20")) {
            String id=j.get("id").toString();
            try {
                var result=python.submit(service.payload(j));
                if(Boolean.TRUE.equals(j.get("cancel_requested"))) {
                    python.cancel(id);
                    db.update("UPDATE learning_parse_jobs SET cancel_requested=FALSE WHERE id=? AND state='CANCELLED'",id);
                    continue;
                }
                var event=new HashMap<String,Object>(result);
                event.put("resourceId",j.get("resource_id").toString());event.put("sourceRevision",j.get("source_revision"));
                service.event(event);
                db.update("UPDATE learning_parse_jobs SET updated_at=CURRENT_TIMESTAMP(3) WHERE id=?",id);
            } catch(RuntimeException e) {log.warn("parse_reconcile_failed jobId={}",id,e);}
        }
    }
}
