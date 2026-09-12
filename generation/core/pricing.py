MILLION = 1000000

CLAUDE2_PROMPT_COST_PER_TOKEN = 8/MILLION
CLAUDE2_COMPLETION_COST_PER_TOKEN = 24/MILLION

GPT4_PROMPT_COST_PER_TOKEN = 0.01/1000
GPT4_COMPLETION_COST_PER_TOKEN = 0.03/1000


def claude2_cost(prompt_tokens, completion_tokens):
    prompt_cost = prompt_tokens * CLAUDE2_PROMPT_COST_PER_TOKEN
    completion_cost = completion_tokens * CLAUDE2_COMPLETION_COST_PER_TOKEN

    return prompt_cost, completion_cost


def gpt4_cost(prompt_tokens, completion_tokens):
    prompt_cost = prompt_tokens * GPT4_PROMPT_COST_PER_TOKEN
    completion_cost = completion_tokens * GPT4_COMPLETION_COST_PER_TOKEN

    return prompt_cost, completion_cost
