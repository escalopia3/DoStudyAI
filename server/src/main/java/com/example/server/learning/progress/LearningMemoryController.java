package com.example.server.learning.progress;

import com.example.server.common.Result;
import com.example.server.service.AuthService;
import org.springframework.web.bind.annotation.*;

import java.util.*;

@RestController
public class LearningMemoryController {
    private final LearningMemoryService service;
    public LearningMemoryController(LearningMemoryService service){this.service=service;}
    public record MemoryInput(String type,String content){}
    public record MemoryUpdate(String content){}

    @GetMapping("/learn/courses/{course}/memories")
    public Result<List<Map<String,Object>>> list(@RequestAttribute(AuthService.REQUEST_USER_ID)Long user,@PathVariable long course){return Result.ok(service.list(user,course));}
    @PostMapping("/learn/courses/{course}/memories")
    public Result<Map<String,Object>> create(@RequestAttribute(AuthService.REQUEST_USER_ID)Long user,@PathVariable long course,@RequestBody MemoryInput input){return Result.ok(service.create(user,course,input.type(),input.content()));}
    @PutMapping("/learn/courses/{course}/memories/{id}")
    public Result<Map<String,Object>> update(@RequestAttribute(AuthService.REQUEST_USER_ID)Long user,@PathVariable long course,@PathVariable String id,@RequestBody MemoryUpdate input){return Result.ok(service.update(user,course,id,input.content()));}
    @DeleteMapping("/learn/courses/{course}/memories/{id}")
    public Result<Void> delete(@RequestAttribute(AuthService.REQUEST_USER_ID)Long user,@PathVariable long course,@PathVariable String id){service.delete(user,course,id);return Result.ok();}
    @DeleteMapping("/learn/courses/{course}/memories")
    public Result<Map<String,Object>> clear(@RequestAttribute(AuthService.REQUEST_USER_ID)Long user,@PathVariable long course){return Result.ok(Map.of("deleted",service.clear(user,course)));}
}
