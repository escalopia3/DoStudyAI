package com.example.server.learning.parsing;

import com.example.server.common.Result;
import com.example.server.service.AuthService;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import java.util.Map;

@RestController
@ConditionalOnProperty(name="learning.parsing.enabled", havingValue="true")
public class ParsingController {
    private final ParsingService service;
    private final PythonParsingClient client;
    private final com.example.server.utils.MinioUtils storage;
    public ParsingController(ParsingService service,PythonParsingClient client,com.example.server.utils.MinioUtils storage) {this.service=service;this.client=client;this.storage=storage;}
    @PostMapping("/learn/resources/{id}/parse")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Result<Map<String,Object>> create(@RequestAttribute(AuthService.REQUEST_USER_ID) Long user,@PathVariable long id) {
        return Result.ok(service.create(user,id));
    }
    @GetMapping("/learn/parse-jobs/{id}")
    public Result<Map<String,Object>> status(@RequestAttribute(AuthService.REQUEST_USER_ID) Long user,@PathVariable String id) {
        return Result.ok(service.view(service.owned(user,id)));
    }
    @PostMapping("/learn/parse-jobs/{id}/cancel")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Result<Map<String,Object>> cancel(@RequestAttribute(AuthService.REQUEST_USER_ID) Long user,@PathVariable String id) {
        service.requestCancel(user,id);return Result.ok(service.view(service.owned(user,id)));
    }
    @PostMapping("/learn/parse-jobs/{id}/retry")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Result<Map<String,Object>> retry(@RequestAttribute(AuthService.REQUEST_USER_ID) Long user,@PathVariable String id) {
        return Result.ok(service.retry(user,id));
    }
    @GetMapping("/learn/parse-jobs/{id}/artifacts/{filename}")
    public Result<Map<String,Object>> artifact(@RequestAttribute(AuthService.REQUEST_USER_ID) Long user,@PathVariable String id,@PathVariable String filename) {
        if(!java.util.Set.of("document.json","content.md","manifest.json").contains(filename))
            throw new IllegalArgumentException("Unknown artifact");
        var job=service.owned(user,id);
        if(!java.util.Set.of("PARSED","INDEXING","READY").contains(job.get("state")) || job.get("artifact_prefix")==null)
            throw new com.example.server.exception.BusinessException(com.example.server.common.ErrorCode.CONFLICT,"解析产物尚未就绪");
        return Result.ok(Map.of("url",storage.readableSource(storage.objectUrl(job.get("artifact_prefix")+"/"+filename))));
    }
    @GetMapping("/internal/learning/jobs/{id}/source")
    public Map<String,Object> source(@RequestHeader(value="Authorization",required=false) String auth,@PathVariable String id) {
        authenticate(auth);return service.source(id);
    }
    @PostMapping("/internal/learning/knowledge-events")
    public Map<String,Object> event(@RequestHeader(value="Authorization",required=false) String auth,@RequestBody Map<String,Object> event) {
        authenticate(auth);service.event(event);return Map.of("accepted",true);
    }
    private void authenticate(String auth) {
        if(!client.authenticated(auth)) throw new com.example.server.exception.BusinessException(com.example.server.common.ErrorCode.UNAUTHORIZED,"Service authentication required");
    }
}
