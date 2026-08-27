# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from multiprocessing import Process

import redis

redis_conn = redis.Redis(charset="utf-8", decode_responses=True)


def sub(name: str):
    pubsub = redis_conn.pubsub()
    pubsub.subscribe("goe_log")
    for message in pubsub.listen():
        print(message)


if __name__ == "__main__":
    Process(target=sub, args=("reader1",)).start()
