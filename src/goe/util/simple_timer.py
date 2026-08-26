# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""SimpleTimer: Library for providing simple elapsed times for logging"""

import time


class SimpleTimer:
    """Library for providing simple elapsed times for logging"""

    def __init__(self, name="timer"):
        self.name = name
        self.start = None
        self.last_call = None
        self.duration = None
        self.reset()

    @property
    def elapsed(self):
        return self.duration or (time.time() - self.start)

    def reset(self):
        self.start = time.time()
        self.last_call = self.start
        self.duration = 0

    def show(self):
        return f"{self.name} elapsed: {self.elapsed:5.3f} seconds"

    def stop(self):
        self.duration = self.elapsed
        return f"{self.name} elapsed: {self.duration:5.3f} seconds"
