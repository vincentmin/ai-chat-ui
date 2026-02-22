import pydantic_ai


agent = pydantic_ai.Agent(
    model='openai-responses:gpt-5-nano',
    instructions='You are an expert assistant.',
)


@agent.tool_plain
def weather(location: str):
    """Get the current weather for a location."""
    return f'The weather in {location} is sunny and 75 degrees.'


if __name__ == '__main__':
    agent.to_cli_sync()
