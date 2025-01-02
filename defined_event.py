from livekit.agents.llm import LLM


@LLM.on("chat_generate_ttbt")
def say_hello(content:str):
    print(f"response text:{content}")