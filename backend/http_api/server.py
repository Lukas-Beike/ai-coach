from http.server import ThreadingHTTPServer


class CoachHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32
