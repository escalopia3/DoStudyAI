package com.example.server.learning.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Map;

@Component
@ConditionalOnProperty(name="learning.parsing.enabled",havingValue="true")
public class PythonLearningAgentClient {
    private final String base,token; private final ObjectMapper mapper;
    private static final HttpClient HTTP=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    public PythonLearningAgentClient(@Value("${learning.python.url:http://127.0.0.1:8091}") String base,
        @Value("${learning.service.token:}") String token,ObjectMapper mapper) {
        if(token.length()<32)throw new IllegalArgumentException("Learning service token must have at least 32 characters");
        URI uri=URI.create(base);if(!java.util.Set.of("http","https").contains(uri.getScheme())||uri.getHost()==null||uri.getUserInfo()!=null)
            throw new IllegalArgumentException("Invalid Python service URL");
        this.base=base.replaceAll("/+$","");this.token=token;this.mapper=mapper;
    }
    public boolean authenticated(String value){return value!=null&&MessageDigest.isEqual(("Bearer "+token).getBytes(StandardCharsets.UTF_8),value.getBytes(StandardCharsets.UTF_8));}
    public Map<String,Object> submit(Map<String,Object> payload){return request("POST","/internal/learning-agent/runs",payload);}
    public Map<String,Object> cancel(String id){return request("POST","/internal/learning-agent/runs/"+valid(id)+"/cancel",Map.of());}
    private String valid(String id){if(id==null||!id.matches("[A-Za-z0-9_-]{8,64}"))throw new IllegalArgumentException("Invalid run ID");return id;}
    @SuppressWarnings("unchecked") private Map<String,Object> request(String method,String path,Map<String,Object> payload){
        try{var request=HttpRequest.newBuilder(URI.create(base+path)).timeout(Duration.ofSeconds(15))
            .header("Authorization","Bearer "+token).header("Content-Type","application/json")
            .method(method,HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(payload))).build();
            var response=HTTP.send(request,HttpResponse.BodyHandlers.ofString());
            if(response.statusCode()/100!=2)throw new IllegalStateException("Python service HTTP "+response.statusCode());
            return mapper.readValue(response.body(),Map.class);
        }catch(InterruptedException e){Thread.currentThread().interrupt();throw new IllegalStateException("Python request interrupted",e);
        }catch(java.io.IOException e){throw new IllegalStateException("Python service unavailable",e);}
    }
}
