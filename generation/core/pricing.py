

GPT4_PROMPT_COST_PER_TOKEN = 0.01/1000
GPT4_COMPLETION_COST_PER_TOKEN = 0.03/1000


def gpt4_cost(prompt_tokens, completion_tokens):
    prompt_cost = prompt_tokens * GPT4_PROMPT_COST_PER_TOKEN
    completion_cost = completion_tokens * GPT4_COMPLETION_COST_PER_TOKEN

    return prompt_cost, completion_cost
