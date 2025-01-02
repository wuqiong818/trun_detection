# 比较好的办法就是改造这一层的代码
# 利用特定服务的事件，进行服务之间的耗时统计。
# 具体服务处理的耗时，由utils.py进行统计。
import logging
import time

from livekit.agents import metrics
from livekit.agents.metrics.base import (
    LLMMetrics,
    PipelineEOUMetrics,
    PipelineLLMMetrics,
    PipelineSTTMetrics,
    PipelineTTSMetrics,
    STTMetrics,
    TTSMetrics,
)
from livekit.agents.pipeline.pipeline_agent import VoicePipelineAgent
from livekit.agents.stt import SpeechEvent
from livekit.agents.tts.stream_adapter import StreamAdapter
from livekit.agents.vad import VADEvent
from livekit.plugins.deepgram.tts import TTS as DeepgramTTS

logger = logging.getLogger("services-between-time-consume")





class TimeConsumStatistics:
    # VAD
    user_start_speaking:float
    user_stop_speaking:float
    user_speaking_duration:float
    vad_metrics:float
    
    # STT
    generate_transcription_time:float
    stt_metrics:float
    userStopSpeaking_to_generateTranscription:float

    # LLM
    llm_ttft:float
    llm_first_return:float
    sttTranscription_to_llmGenerate:float

    # TTS
    tts_ttfb:float
    tts_first_return:float
    llmGenerate_to_ttsGenerate:float

    # playout
    agent_start_speaking:float
    ttsGenerate_to_agentStartSpeaking:float

    total_consume:float
    

    def __init__(self,agent:VoicePipelineAgent):
        self.agent = agent
        # 初始化所有可能用到的属性
        # VAD
        self.user_start_speaking = 0.0
        self.user_stop_speaking = 0.0
        self.user_speaking_duration = 0.0
        self.vad_metrics = 0.0
        
        # STT
        self.generate_transcription_time = 0.0
        self.stt_metrics = 0.0
        self.userStopSpeaking_to_generateTranscription = 0.0

        # LLM
        self.llm_ttft = 0.0
        self.llm_first_return = 0.0
        self.sttTranscription_to_llmGenerate = 0.0

        # TTS
        self.tts_ttfb = 0.0
        self.tts_first_return = 0.0
        self.llmGenerate_to_ttsGenerate = 0.0

        # playout
        self.agent_start_speaking = 0.0
        self.ttsGenerate_to_agentStartSpeaking = 0.0

        self.total_consume = 0.0
        
        self.agent = agent
        self._add_statistics_event()
        

    def __str__(self) -> str:
        return (
            f"\n===== Time Consumption Statistics =====\n"
            f"User_speaking_duration: {self.user_speaking_duration:.2f}s (Start: {self.user_start_speaking:.2f}, Stop: {self.user_stop_speaking:.2f})\n"
            f"VAD Metrics: {self.vad_metrics:.2f}s\n"
            f"UserStop->STT: {self.userStopSpeaking_to_generateTranscription:.2f}s (STT duration: {self.stt_metrics:.2f}s)\n"
            f"STT->LLM: {self.sttTranscription_to_llmGenerate:.2f}s (LLM_ttft: {self.llm_ttft:.2f}s)\n"
            f"LLM->TTS: {self.llmGenerate_to_ttsGenerate:.2f}s (TTS_ttfb: {self.tts_ttfb:.2f}s)\n"
            f"TTS->Agent_started_speaking: {self.ttsGenerate_to_agentStartSpeaking:.2f}s\n"
            f"Total Time: {self.total_consume:.2f}s\n"
            f"=========================="
        )
    

    def _add_statistics_event(self):
        @self.agent._human_input.on("start_of_speech")
        def user_start_of_speech(ev:VADEvent):
            self.user_start_speaking = time.perf_counter()
            logger.info(f"User speaking started,current_time={time.time()}")
            

        @self.agent._human_input.on("end_of_speech")
        def _on_end_of_speech(ev:VADEvent):
            self.user_stop_speaking = time.perf_counter()
            # 用于转录的时间，会在这段音频的最前面追加 0.5 S
            self.user_speaking_duration = self.user_stop_speaking - self.user_start_speaking
            self.vad_metrics = ev.inference_duration
            logger.info(f"user speaking stopped, duration = {self.user_stop_speaking - self.user_start_speaking},vad_metrics = {self.vad_metrics}")
            
        @self.agent._llm.on("llm_ttft_responsed")
        def llm_ttfb_responsed(current_time):
            self.llm_first_return = time.perf_counter()
            logger.info(f"llm_first_return{current_time}")
        
        
        def tts_ttfb_responsed(current_time):
            self.tts_first_return = time.perf_counter()
            logger.info(f"tts_first_return{current_time}")

        if isinstance(self.agent._tts, DeepgramTTS):
            self.agent._tts.on("tts_ttfb_responsed",tts_ttfb_responsed)
        elif isinstance(self.agent._tts, StreamAdapter):
            self.agent._tts._tts.on("tts_ttfb_responsed",tts_ttfb_responsed)

        @self.agent.on("agent_started_speaking")
        def agent_started_speaking():
            self.agent_start_speaking = time.perf_counter()
            self.ttsGenerate_to_agentStartSpeaking = self.agent_start_speaking - self.tts_first_return
            self.total_consume = self.agent_start_speaking - self.user_stop_speaking
            

        @self.agent.on("agent_stopped_speaking")
        def agent_stopped_speaking():
            logger.info(f"{self}")

        @self.agent.on("metrics_collected")
        def services_metrics_collected(metrics: metrics.AgentMetrics):
            if isinstance(metrics, PipelineEOUMetrics):
                print(self.agent._tts)
                logger.info(
                    f"Pipeline EOU metrics: sequence_id={metrics.sequence_id}, end_of_utterance_delay={metrics.end_of_utterance_delay:.2f}, transcription_delay={metrics.transcription_delay:.2f}"
                )

            elif isinstance(metrics, PipelineSTTMetrics):
                self.stt_metrics = metrics.duration
                self.generate_transcription_time = time.perf_counter()
                self.userStopSpeaking_to_generateTranscription = self.generate_transcription_time - self.user_stop_speaking

            elif isinstance(metrics, PipelineLLMMetrics):
                self.llm_ttft = metrics.ttft
                self.sttTranscription_to_llmGenerate = self.llm_first_return - self.generate_transcription_time

            elif isinstance(metrics, PipelineTTSMetrics):
                self.tts_ttfb = metrics.ttfb
                self.llmGenerate_to_ttsGenerate = self.tts_first_return - self.llm_first_return
                

