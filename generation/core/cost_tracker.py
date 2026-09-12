from core.clients.ddb import put_item, incrby


def init_cost(pk, sk):
    data = {
        'prompt': 0,
        'completion': 0
    }
    put_item(pk, sk, data)


def update_cost(pk, sk, prompt_cost, completion_cost):
    key = {
        'pk': pk,
        'sk': sk
    }

    incrby(key, "prompt", prompt_cost)
    incrby(key, "completion", completion_cost)
