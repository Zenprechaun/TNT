"""Settings for Gunicorn, the program that runs the Django site on the live server.

Nginx receives visitors and passes their requests to Gunicorn on 127.0.0.1:8000.
"""

import multiprocessing

bind = "127.0.0.1:8000"
workers = min(4, multiprocessing.cpu_count() * 2 + 1)
timeout = 60
graceful_timeout = 30
worker_tmp_dir = "/dev/shm"
accesslog = "-"
errorlog = "-"
