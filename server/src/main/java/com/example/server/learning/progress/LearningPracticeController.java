package com.example.server.learning.progress;

import com.example.server.common.Result;
import com.example.server.service.AuthService;
import org.springframework.web.bind.annotation.*;

import java.util.*;

@RestController
public class LearningPracticeController {
    private final LearningPracticeService service;
    public LearningPracticeController(LearningPracticeService service){this.service=service;}
    public record Submission(Map<String,Object> answers){}

    @GetMapping("/learn/courses/{course}/practice-sets")
    public Result<List<Map<String,Object>>> sets(@RequestAttribute(AuthService.REQUEST_USER_ID)Long user,@PathVariable long course){return Result.ok(service.sets(user,course));}
    @GetMapping("/learn/practice-sets/{id}")
    public Result<Map<String,Object>> detail(@RequestAttribute(AuthService.REQUEST_USER_ID)Long user,@PathVariable String id){return Result.ok(service.detail(user,id,false));}
    @PostMapping("/learn/practice-sets/{id}/submit")
    public Result<Map<String,Object>> submit(@RequestAttribute(AuthService.REQUEST_USER_ID)Long user,@PathVariable String id,@RequestBody Submission input){return Result.ok(service.submit(user,id,input==null?Map.of():input.answers()));}
    @GetMapping("/learn/courses/{course}/attempts")
    public Result<List<Map<String,Object>>> attempts(@RequestAttribute(AuthService.REQUEST_USER_ID)Long user,@PathVariable long course){return Result.ok(service.attempts(user,course));}
    @GetMapping("/learn/attempts/{id}")
    public Result<Map<String,Object>> attempt(@RequestAttribute(AuthService.REQUEST_USER_ID)Long user,@PathVariable String id){return Result.ok(service.attempt(user,id));}
    @GetMapping("/learn/courses/{course}/wrong-questions")
    public Result<List<Map<String,Object>>> wrong(@RequestAttribute(AuthService.REQUEST_USER_ID)Long user,@PathVariable long course){return Result.ok(service.wrongQuestions(user,course));}
    @GetMapping("/learn/courses/{course}/mastery")
    public Result<List<Map<String,Object>>> mastery(@RequestAttribute(AuthService.REQUEST_USER_ID)Long user,@PathVariable long course){return Result.ok(service.mastery(user,course));}
}
