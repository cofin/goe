# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for PollingThread background polling and queue draining."""

import time
from random import randint
from unittest import TestCase, main

from goe.offload.transport.spark.polling import PollingThread


class TestPollingThread(TestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.interval = 0.25
        self.values = []

    def polling_fn(self):
        i = randint(0, 100)
        self.values.append(i)
        return i

    def exception_fn(self):
        time.sleep(self.interval / 2)
        raise RuntimeError("Error raised in exception_fn")

    def test_polling_thread(self):
        self.values = []
        pt = PollingThread(run_function=self.polling_fn, name="test_polling_thread", interval=self.interval)
        pt.start()
        time.sleep(self.interval * 5)
        pt.stop()
        items = pt.drain_queue()
        self.assertListEqual(items, self.values)

    def test_polling_thread_exception(self):
        pt = PollingThread(
            run_function=self.exception_fn,
            name="test_polling_thread_exception",
            interval=self.interval,
        )
        pt.start()
        time.sleep(self.interval * 2)
        pt.stop()
        self.assertIsNotNone(pt.exception)


if __name__ == "__main__":
    main()
