# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
import threading
from Queue import Queue
from collections import defaultdict
import time

import zmq

from powerhose.exc import TimeoutError, ExecutionError
from powerhose.job import Job
from powerhose.util import send, recv, DEFAULT_FRONTEND, logger, extract_result


class Client(object):
    """Class to call a Powerhose cluster.

    Options:

    - **frontend**: ZMQ socket to call.
    - **timeout**: maximum allowed time for a job to run.
      Defaults to 5s.
    - **timeout_max_overflow**: maximum timeout overflow allowed
    - **timeout_overflows**: number of times in a row the timeout value
      can be overflowed per worker. The client keeps a counter of
      executions that were longer than the regular timeout but shorter
      than **timeout_max_overflow**. When the number goes over
    - **timeout_overflows**, the usual TimeoutError is raised.
      When a worker returns on time, the counter is reset.
    """
    def __init__(self, frontend=DEFAULT_FRONTEND, timeout=1.,
                 timeout_max_overflow=1.5, timeout_overflows=1,
                 iothreads=5):
        self.ctx = zmq.Context(io_threads=iothreads)
        self.master = self.ctx.socket(zmq.REQ)
        self.master.connect(frontend)
        logger.debug('Client connected to %s' % frontend)
        self.poller = zmq.Poller()
        self.poller.register(self.master, zmq.POLLIN)
        self.timeout = timeout * 1000
        self.lock = threading.Lock()
        self.timeout_max_overflow = timeout_max_overflow * 1000
        self.timeout_overflows = timeout_overflows
        self.timeout_counters = defaultdict(int)

    def execute(self, job, timeout=None):
        """Runs the job

        Options:

        - **job**: Job to be performed. Can be a :class:`Job`
          instance or a string. If it's a string a :class:`Job` instance
          will be automatically created out of it.
        - **timeout**: maximum allowed time for a job to run.
          If not provided, uses the one defined in the constructor.

        If the job fails after the timeout, raises a :class:`TimeoutError`.

        This method is thread-safe and uses a lock. If you need to execute a
        lot of jobs simultaneously on a broker, use the :class:`Pool` class.

        """
        if timeout is None:
            timeout = self.timeout_max_overflow

        # XXX this call is taking us time but we need it for the overflow
        start = time.time()
        try:
            worker_pid, res, data = extract_result(self._execute(job, timeout))

            # if we overflowed we want to increment the counter
            # if not we reset it
            duration = (time.time() - start) * 1000
            if duration > self.timeout:
                self.timeout_counters[worker_pid] += 1

                # XXX well, we have the result but we want to timeout
                # nevertheless because that's been too much overflow
                if self.timeout_counters[worker_pid] > self.timeout_overflows:
                    raise TimeoutError()
            else:
                self.timeout_counters[worker_pid] = 0

            if not res:
                raise ExecutionError(data)
        except Exception:
            duration = time.time() - start
            # logged, connector replaced.
            logger.exception('Failed to execute job in %.4f seconds.' %
                    duration)
            raise

        return data

    def _execute(self, job, timeout=None):
        if isinstance(job, str):
            job = Job(job)

        if timeout is None:
            timeout = self.timeout_max_overflow

        with self.lock:
            send(self.master, job.serialize())
            socks = dict(self.poller.poll(timeout))

        if socks.get(self.master) == zmq.POLLIN:
            return recv(self.master)

        raise TimeoutError()


class Pool(object):
    """The pool class manage several :class:`CLient` instances
    and publish the same interface,

    Options:

    - **size**: size of the pool. Defaults to 10.
    - **frontend**: ZMQ socket to call.
    - **timeout**: maximum allowed time for a job to run.
      Defaults to 5s.
    """
    def __init__(self, size=10, frontend=DEFAULT_FRONTEND, timeout=4.,
                 timeout_max_overflow=5., timeout_overflows=1):
        self._connectors = Queue()
        self.frontend = frontend
        self.timeout = timeout
        self.timeout_overflows = timeout_overflows
        self.timeout_max_overflow = timeout_max_overflow

        for i in range(size):
            self._connectors.put(self._create_client())

    def _create_client(self):
        return Client(self.frontend, self.timeout,
                      self.timeout_max_overflow, self.timeout_overflows)

    def execute(self, job, timeout=None):
        connector = self._connectors.get(timeout=timeout)
        try:
            res = connector.execute(job, timeout)
        except Exception:
            # connector replaced.
            self._connectors.put(self._create_client())
            raise
        else:
            self._connectors.put(connector)

        return res
