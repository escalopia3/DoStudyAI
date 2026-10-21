package com.example.server.learning.agent;

import com.example.server.learning.CourseRepository;
import org.springframework.stereotype.Service;
import java.util.*;

@Service
public class LearningAuthorizationService {
    private final CourseRepository db;
    public LearningAuthorizationService(CourseRepository db){this.db=db;}
    public void course(long user,long course){
        if(db.rows("SELECT id FROM courses WHERE id=? AND user_id=?",course,user).isEmpty())throw new NoSuchElementException("课程不存在或无权访问");
    }
    public List<String> readyResources(long user,long course,List<String> selected){
        course(user,course);
        var rows=db.rows("SELECT r.id FROM learning_resources r JOIN course_resources cr ON cr.resource_id=r.id WHERE r.user_id=? AND cr.course_id=? AND r.parse_status='READY' ORDER BY r.id",user,course);
        var allowed=new LinkedHashSet<String>();for(var row:rows)allowed.add(row.get("id").toString());
        if(selected==null||selected.isEmpty())return new ArrayList<>(allowed);
        var result=new ArrayList<String>();for(String id:selected)if(allowed.contains(id)&&!result.contains(id))result.add(id);
        return result;
    }
}
