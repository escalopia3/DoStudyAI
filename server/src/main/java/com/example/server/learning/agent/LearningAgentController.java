package com.example.server.learning.agent;

import com.example.server.common.Result;
import com.example.server.service.AuthService;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.*;
import java.util.*;

@RestController
@ConditionalOnProperty(name="learning.parsing.enabled",havingValue="true")
public class LearningAgentController {
    private final LearningAgentService service;private final PythonLearningAgentClient python;
    public LearningAgentController(LearningAgentService service,PythonLearningAgentClient python){this.service=service;this.python=python;}
    public record ConversationInput(String title){}
    public record MessageInput(String question,String mode,List<String> resourceIds){}
    @PostMapping("/learn/courses/{course}/conversations") public Result<Map<String,Object>> create(@RequestAttribute(AuthService.REQUEST_USER_ID)Long user,@PathVariable long course,@RequestBody(required=false)ConversationInput input){return Result.ok(service.createConversation(user,course,input==null?null:input.title()));}
    @GetMapping("/learn/courses/{course}/conversations") public Result<List<Map<String,Object>>> conversations(@RequestAttribute(AuthService.REQUEST_USER_ID)Long user,@PathVariable long course){return Result.ok(service.conversations(user,course));}
    @GetMapping("/learn/conversations/{id}/messages") public Result<List<Map<String,Object>>> messages(@RequestAttribute(AuthService.REQUEST_USER_ID)Long user,@PathVariable String id){return Result.ok(service.messages(user,id));}
    @PostMapping("/learn/conversations/{id}/messages") public Result<Map<String,Object>> ask(@RequestAttribute(AuthService.REQUEST_USER_ID)Long user,@PathVariable String id,@RequestBody MessageInput input){return Result.ok(service.ask(user,id,input.question(),input.mode(),input.resourceIds()));}
    @GetMapping("/learn/agent-runs/{id}") public Result<Map<String,Object>> run(@RequestAttribute(AuthService.REQUEST_USER_ID)Long user,@PathVariable String id){return Result.ok(service.run(user,id));}
    @PostMapping("/learn/agent-runs/{id}/cancel") public Result<Void> cancel(@RequestAttribute(AuthService.REQUEST_USER_ID)Long user,@PathVariable String id){service.cancel(user,id);return Result.ok();}
    @PostMapping("/internal/learning/agent-events") public Map<String,Object> event(@RequestHeader(value="Authorization",required=false)String auth,@RequestBody Map<String,Object> event){if(!python.authenticated(auth))throw new com.example.server.exception.BusinessException(com.example.server.common.ErrorCode.UNAUTHORIZED,"Service authentication required");service.event(event);return Map.of("accepted",true);}
}
