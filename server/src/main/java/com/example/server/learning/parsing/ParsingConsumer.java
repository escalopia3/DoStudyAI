package com.example.server.learning.parsing;

import org.apache.rocketmq.spring.annotation.RocketMQMessageListener;
import org.apache.rocketmq.spring.core.RocketMQListener;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(name="learning.parsing.enabled", havingValue="true")
@RocketMQMessageListener(topic="${learning.parsing.topic:learning-parse}", consumerGroup="${learning.parsing.group:learning-parse-java}", maxReconsumeTimes=3)
public class ParsingConsumer implements RocketMQListener<String> {
    private final ParsingService service;
    private final PythonParsingClient python;
    public ParsingConsumer(ParsingService service,PythonParsingClient python) {this.service=service;this.python=python;}
    public void onMessage(String id) {
        var j=service.job(id);
        python.submit(service.payload(j));
        if(Boolean.TRUE.equals(j.get("cancel_requested"))) python.cancel(id);
    }
}
