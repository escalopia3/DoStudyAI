package com.example.server.learning.progress;

import com.example.server.learning.CourseRepository;
import com.example.server.learning.agent.LearningAuthorizationService;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.*;

@Service
public class LearningPracticeService {
    private static final Set<String> TYPES=Set.of("SINGLE_CHOICE","TRUE_FALSE","SHORT_ANSWER");
    private static final Set<String> DIFFICULTIES=Set.of("EASY","MEDIUM","HARD");
    private final CourseRepository db;
    private final LearningAuthorizationService authorization;
    private final LearningMemoryService memories;
    private final ObjectMapper mapper;
    private final TransactionTemplate tx;

    public LearningPracticeService(CourseRepository db,LearningAuthorizationService authorization,
        LearningMemoryService memories,ObjectMapper mapper,TransactionTemplate tx){
        this.db=db;this.authorization=authorization;this.memories=memories;this.mapper=mapper;this.tx=tx;
    }

    public void persistGenerated(Map<String,Object> run,Map<?,?> artifact,String requestText,String snapshot,Set<String> validCitations){
        long user=number(run.get("user_id")),course=number(run.get("course_id"));
        String assistant=text(run.get("assistant_message_id")),conversation=text(run.get("conversation_id"));
        if(!db.rows("SELECT id FROM learning_practice_sets WHERE assistant_message_id=?",assistant).isEmpty())return;
        String title=required(artifact.get("title"),200,"练习标题"),instructions=required(artifact.get("instructions"),1000,"练习说明");
        if(!(artifact.get("questions") instanceof List<?> questions)||questions.isEmpty()||questions.size()>12)throw new IllegalArgumentException("练习题数量必须为1到12题");
        String setId=UUID.randomUUID().toString();
        db.update("INSERT INTO learning_practice_sets(id,user_id,course_id,conversation_id,assistant_message_id,title,request_text,instructions,knowledge_snapshot_id) VALUES(?,?,?,?,?,?,?,?,?)",
            setId,user,course,conversation,assistant,title,requestText,instructions,snapshot);
        int ordinal=0;
        for(Object item:questions){
            if(!(item instanceof Map<?,?> question))throw new IllegalArgumentException("练习题结构无效");
            persistQuestion(user,course,setId,++ordinal,question,validCitations);
        }
    }

    public List<Map<String,Object>> sets(long user,long course){
        authorization.course(user,course);
        return db.rows("SELECT p.id,p.title,p.instructions,p.status,p.created_at,COUNT(q.id) AS question_count,COALESCE(MAX(a.submitted_at),NULL) AS last_submitted_at FROM learning_practice_sets p LEFT JOIN learning_questions q ON q.practice_set_id=p.id LEFT JOIN learning_attempts a ON a.practice_set_id=p.id AND a.user_id=p.user_id WHERE p.user_id=? AND p.course_id=? GROUP BY p.id,p.title,p.instructions,p.status,p.created_at ORDER BY p.created_at DESC",user,course);
    }

    public Map<String,Object> detail(long user,String setId,boolean answers){
        var set=ownedSet(user,setId);String sql=answers
            ?"SELECT id,ordinal_no,question_type,stem,options_json,correct_answers_json,explanation,rubric_keywords_json,difficulty,points,knowledge_points_json,citation_ids_json FROM learning_questions WHERE practice_set_id=? ORDER BY ordinal_no"
            :"SELECT id,ordinal_no,question_type,stem,options_json,difficulty,points,knowledge_points_json,citation_ids_json FROM learning_questions WHERE practice_set_id=? ORDER BY ordinal_no";
        set.put("questions",decodeRows(db.rows(sql,setId)));return set;
    }

    public Map<String,Object> submit(long user,String setId,Map<String,Object> answers){
        var set=ownedSet(user,setId);long course=number(set.get("course_id"));
        if(answers==null)answers=Map.of();Map<String,Object> submitted=answers;
        return tx.execute(status->submitInside(user,course,setId,submitted));
    }

    public List<Map<String,Object>> attempts(long user,long course){
        authorization.course(user,course);
        return db.rows("SELECT a.id,a.practice_set_id,p.title,a.state,a.score,a.max_score,a.started_at,a.submitted_at FROM learning_attempts a JOIN learning_practice_sets p ON p.id=a.practice_set_id WHERE a.user_id=? AND a.course_id=? ORDER BY a.started_at DESC",user,course);
    }

    public Map<String,Object> attempt(long user,String id){
        var rows=db.rows("SELECT a.id,a.practice_set_id,p.title,a.state,a.score,a.max_score,a.started_at,a.submitted_at FROM learning_attempts a JOIN learning_practice_sets p ON p.id=a.practice_set_id WHERE a.id=? AND a.user_id=?",id,user);
        if(rows.isEmpty())throw new NoSuchElementException("练习记录不存在");var result=rows.getFirst();
        var answers=db.rows("SELECT a.question_id,q.ordinal_no,q.stem,q.question_type,a.answer_json,a.is_correct,a.score,a.max_score,a.feedback,q.correct_answers_json,q.explanation,q.citation_ids_json FROM learning_answers a JOIN learning_questions q ON q.id=a.question_id WHERE a.attempt_id=? ORDER BY q.ordinal_no",id);
        result.put("answers",decodeRows(answers));return result;
    }

    public List<Map<String,Object>> wrongQuestions(long user,long course){
        authorization.course(user,course);
        return decodeRows(db.rows("SELECT w.question_id,w.wrong_count,w.correct_streak,w.status,w.last_wrong_answer_json,w.first_wrong_at,w.last_practiced_at,w.mastered_at,q.stem,q.question_type,q.options_json,q.correct_answers_json,q.explanation,q.knowledge_points_json,q.citation_ids_json FROM learning_wrong_questions w JOIN learning_questions q ON q.id=w.question_id WHERE w.user_id=? AND w.course_id=? ORDER BY (w.status='ACTIVE') DESC,w.last_practiced_at DESC",user,course));
    }

    public List<Map<String,Object>> mastery(long user,long course){
        authorization.course(user,course);
        return db.rows("SELECT k.id AS knowledge_point_id,k.name,CAST(m.mastery_score AS DOUBLE) AS mastery_score,m.confidence_count,m.correct_count,m.wrong_count,m.last_practiced_at,m.updated_at FROM learning_mastery_states m JOIN learning_knowledge_points k ON k.id=m.knowledge_point_id WHERE m.user_id=? AND m.course_id=? ORDER BY m.mastery_score,k.name",user,course);
    }

    private Map<String,Object> submitInside(long user,long course,String setId,Map<String,Object> submitted){
        var questions=decodeRows(db.rows("SELECT * FROM learning_questions WHERE practice_set_id=? ORDER BY ordinal_no",setId));
        if(questions.isEmpty())throw new IllegalStateException("练习题为空");
        String attemptId=UUID.randomUUID().toString();double total=0,max=0;
        db.update("INSERT INTO learning_attempts(id,user_id,course_id,practice_set_id,state) VALUES(?,?,?,?,'SUBMITTING')",attemptId,user,course,setId);
        for(var question:questions){
            String questionId=text(question.get("id"));Object raw=submitted.get(questionId);
            Score score=grade(question,raw);total+=score.score();max+=score.max();
            db.update("INSERT INTO learning_answers(id,attempt_id,question_id,answer_json,is_correct,score,max_score,feedback) VALUES(?,?,?,?,?,?,?,?)",
                UUID.randomUUID().toString(),attemptId,questionId,json(raw==null?List.of():raw),score.correct(),score.score(),score.max(),score.feedback());
            updateWrong(user,course,questionId,raw,score.correct());
            updateMastery(user,course,attemptId,question,score);
        }
        db.update("UPDATE learning_attempts SET state='SUBMITTED',score=?,max_score=?,submitted_at=CURRENT_TIMESTAMP(3) WHERE id=?",round(total),round(max),attemptId);
        return attempt(user,attemptId);
    }

    private void persistQuestion(long user,long course,String setId,int ordinal,Map<?,?> q,Set<String> validCitations){
        String type=enumValue(q.get("type"),TYPES,"题型"),difficulty=enumValue(q.get("difficulty"),DIFFICULTIES,"难度");
        String stem=required(q.get("stem"),1200,"题干"),explanation=required(q.get("explanation"),2000,"解析");
        int points=(int)number(q.get("points"));if(points<1||points>20)throw new IllegalArgumentException("题目分值无效");
        List<?> options=list(q.get("options")),correct=list(q.get("correctAnswers")),rubric=list(q.get("rubricKeywords")),knowledge=list(q.get("knowledgePoints")),citations=list(q.get("citationIds"));
        if(knowledge.isEmpty()||knowledge.size()>4||citations.isEmpty()||citations.size()>4)throw new IllegalArgumentException("题目知识点或引用无效");
        for(Object citation:citations)if(!validCitations.contains(text(citation)))throw new IllegalArgumentException("练习题引用不在本次检索证据中");
        validateAnswers(type,options,correct,rubric);
        String questionId=UUID.randomUUID().toString();
        db.update("INSERT INTO learning_questions(id,practice_set_id,ordinal_no,question_type,stem,options_json,correct_answers_json,explanation,rubric_keywords_json,difficulty,points,knowledge_points_json,citation_ids_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            questionId,setId,ordinal,type,stem,json(options),json(correct),explanation,json(rubric),difficulty,points,json(knowledge),json(citations));
        for(Object value:knowledge){
            String name=required(value,160,"知识点"),normalized=normalizeKnowledge(name);
            db.update("INSERT INTO learning_knowledge_points(user_id,course_id,name,normalized_name) VALUES(?,?,?,?) ON DUPLICATE KEY UPDATE name=VALUES(name)",user,course,name,normalized);
            long kp=number(db.rows("SELECT id FROM learning_knowledge_points WHERE user_id=? AND course_id=? AND normalized_name=?",user,course,normalized).getFirst().get("id"));
            db.update("INSERT IGNORE INTO learning_question_knowledge_points(question_id,knowledge_point_id) VALUES(?,?)",questionId,kp);
        }
    }

    private void updateWrong(long user,long course,String question,Object answer,boolean correct){
        var rows=db.rows("SELECT wrong_count,correct_streak FROM learning_wrong_questions WHERE user_id=? AND course_id=? AND question_id=? FOR UPDATE",user,course,question);
        if(!correct){
            if(rows.isEmpty())db.update("INSERT INTO learning_wrong_questions(user_id,course_id,question_id,wrong_count,last_wrong_answer_json) VALUES(?,?,?,1,?)",user,course,question,json(answer));
            else db.update("UPDATE learning_wrong_questions SET wrong_count=wrong_count+1,correct_streak=0,status='ACTIVE',last_wrong_answer_json=?,last_practiced_at=CURRENT_TIMESTAMP(3),mastered_at=NULL WHERE user_id=? AND course_id=? AND question_id=?",json(answer),user,course,question);
        }else if(!rows.isEmpty()){
            int streak=((Number)rows.getFirst().get("correct_streak")).intValue()+1;
            db.update("UPDATE learning_wrong_questions SET correct_streak=?,status=?,last_practiced_at=CURRENT_TIMESTAMP(3),mastered_at=IF(?='MASTERED',CURRENT_TIMESTAMP(3),mastered_at) WHERE user_id=? AND course_id=? AND question_id=?",streak,streak>=2?"MASTERED":"ACTIVE",streak>=2?"MASTERED":"ACTIVE",user,course,question);
        }
    }

    private void updateMastery(long user,long course,String attempt,Map<String,Object> question,Score result){
        var points=db.rows("SELECT k.id,k.name FROM learning_question_knowledge_points q JOIN learning_knowledge_points k ON k.id=q.knowledge_point_id WHERE q.question_id=?",question.get("id"));
        double performance=result.max()==0?0:result.score()/result.max();double weight=switch(text(question.get("difficulty"))){case "EASY"->.08;case "HARD"->.16;default->.12;};
        double delta=weight*(2*performance-1);if(performance<.5)delta*=1.25;
        for(var point:points){
            long id=number(point.get("id"));var rows=db.rows("SELECT mastery_score,confidence_count,correct_count,wrong_count FROM learning_mastery_states WHERE user_id=? AND course_id=? AND knowledge_point_id=? FOR UPDATE",user,course,id);
            double before=rows.isEmpty()?.5:((Number)rows.getFirst().get("mastery_score")).doubleValue(),after=clamp(before+delta);
            int count=rows.isEmpty()?1:((Number)rows.getFirst().get("confidence_count")).intValue()+1;
            if(rows.isEmpty())db.update("INSERT INTO learning_mastery_states(user_id,course_id,knowledge_point_id,mastery_score,confidence_count,correct_count,wrong_count,last_practiced_at) VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP(3))",user,course,id,after,1,result.correct()?1:0,result.correct()?0:1);
            else db.update("UPDATE learning_mastery_states SET mastery_score=?,confidence_count=confidence_count+1,correct_count=correct_count+?,wrong_count=wrong_count+?,last_practiced_at=CURRENT_TIMESTAMP(3) WHERE user_id=? AND course_id=? AND knowledge_point_id=?",after,result.correct()?1:0,result.correct()?0:1,user,course,id);
            db.update("INSERT INTO learning_mastery_events(user_id,course_id,knowledge_point_id,attempt_id,question_id,event_type,delta_value,score_after,detail_json) VALUES(?,?,?,?,?,'PRACTICE_GRADED',?,?,?)",user,course,id,attempt,question.get("id"),round(delta),round(after),json(Map.of("performance",round(performance),"difficulty",question.get("difficulty"))));
            updateMemory(user,course,id,text(point.get("name")),after,count);
        }
    }

    private void updateMemory(long user,long course,long id,String name,double score,int count){
        String ref=Long.toString(id);
        if(score<.4){memories.upsertSystem(user,course,"WEAKNESS",ref,"知识点「"+name+"」当前掌握较弱，后续讲解应增加基础例子和练习。",1-score);memories.retireSystem(user,course,"MASTERY",ref);}
        else if(score>.8&&count>=3){memories.upsertSystem(user,course,"MASTERY",ref,"知识点「"+name+"」已较熟练，可增加综合题并减少基础重复。",score);memories.retireSystem(user,course,"WEAKNESS",ref);}
        else {memories.retireSystem(user,course,"WEAKNESS",ref);memories.retireSystem(user,course,"MASTERY",ref);}
    }

    static Score grade(Map<String,Object> question,Object answer){
        String type=text(question.get("question_type"));double max=((Number)question.get("points")).doubleValue();
        List<String> expected=strings(question.get("correct_answers_json"));
        if(!"SHORT_ANSWER".equals(type)){
            List<String> actual=normalizeAnswers(answer);boolean correct=actual.size()==expected.size()&&new LinkedHashSet<>(actual).equals(new LinkedHashSet<>(expected));
            return new Score(correct,correct?max:0,max,correct?"回答正确":"回答错误，请结合解析重新理解。 ");
        }
        String response=answer instanceof String s?s.strip():"";List<String> rubric=strings(question.get("rubric_keywords_json"));
        long hits=rubric.stream().filter(word->!word.isBlank()&&response.toLowerCase(Locale.ROOT).contains(word.toLowerCase(Locale.ROOT))).count();
        double ratio=rubric.isEmpty()?0:(double)hits/rubric.size(),score=round(max*ratio);boolean correct=ratio>=.8;
        return new Score(correct,score,max,"评分关键词覆盖 "+hits+"/"+rubric.size()+"；简答题为规则辅助评分，请结合参考解析自查。");
    }

    static List<String> normalizeAnswers(Object value){
        if(value instanceof List<?> list)return list.stream().map(LearningPracticeService::text).map(String::strip).filter(s->!s.isEmpty()).distinct().sorted().toList();
        if(value instanceof String s&&!s.isBlank())return List.of(s.strip());return List.of();
    }
    private static void validateAnswers(String type,List<?> options,List<?> correct,List<?> rubric){
        Set<String> ids=new LinkedHashSet<>();for(Object option:options){if(!(option instanceof Map<?,?> m))throw new IllegalArgumentException("选项结构无效");String id=text(m.get("id"));if(!id.matches("[A-H]")||!ids.add(id)||required(m.get("text"),500,"选项").isBlank())throw new IllegalArgumentException("选项无效");}
        if("SHORT_ANSWER".equals(type)){if(!options.isEmpty()||rubric.isEmpty())throw new IllegalArgumentException("简答题结构无效");return;}
        if(ids.size()<2||correct.size()!=1||!ids.contains(text(correct.getFirst())))throw new IllegalArgumentException("客观题答案无效");
        if("TRUE_FALSE".equals(type)&&!ids.equals(new LinkedHashSet<>(List.of("A","B"))))throw new IllegalArgumentException("判断题必须使用A、B两个选项");
    }
    private Map<String,Object> ownedSet(long user,String id){var rows=db.rows("SELECT id,user_id,course_id,conversation_id,assistant_message_id,title,request_text,instructions,knowledge_snapshot_id,status,created_at FROM learning_practice_sets WHERE id=? AND user_id=?",id,user);if(rows.isEmpty())throw new NoSuchElementException("练习不存在");return rows.getFirst();}
    private List<Map<String,Object>> decodeRows(List<Map<String,Object>> rows){for(var row:rows)for(String key:List.of("options_json","correct_answers_json","rubric_keywords_json","knowledge_points_json","citation_ids_json","answer_json","last_wrong_answer_json"))if(row.containsKey(key))row.put(key.replace("_json",""),read(row.remove(key)));return rows;}
    private Object read(Object value){if(value==null)return null;try{return mapper.readValue(value.toString(),Object.class);}catch(Exception e){throw new IllegalStateException("Stored JSON invalid",e);}}
    private static List<String> strings(Object value){try{Object parsed=value;if(value instanceof String s)parsed=new ObjectMapper().readValue(s,new TypeReference<List<String>>(){});if(parsed instanceof List<?> list)return list.stream().map(LearningPracticeService::text).toList();}catch(Exception ignored){}return List.of();}
    private static List<?> list(Object value){return value instanceof List<?> result?result:List.of();}
    private static String enumValue(Object value,Set<String> allowed,String label){String result=text(value);if(!allowed.contains(result))throw new IllegalArgumentException(label+"无效");return result;}
    private static String required(Object value,int max,String label){String result=text(value).strip();if(result.isEmpty()||result.length()>max)throw new IllegalArgumentException(label+"不能为空且长度不能超过"+max);return result;}
    private static String normalizeKnowledge(String value){return value.strip().toLowerCase(Locale.ROOT).replaceAll("\\s+","");}
    private static String text(Object value){return Objects.toString(value,"");}
    private static long number(Object value){return value instanceof Number n?n.longValue():Long.parseLong(text(value));}
    private String json(Object value){try{return mapper.writeValueAsString(value);}catch(Exception e){throw new IllegalStateException("JSON serialization failed",e);}}
    private static double clamp(double value){return round(Math.max(0,Math.min(1,value)));}
    private static double round(double value){return BigDecimal.valueOf(value).setScale(4,RoundingMode.HALF_UP).doubleValue();}
    record Score(boolean correct,double score,double max,String feedback){}
}
