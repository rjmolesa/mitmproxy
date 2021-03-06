import cStringIO, urllib, time, sys, traceback
import version, flow

def date_time_string():
    """Return the current date and time formatted for a message header."""
    WEEKS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    MONTHS = [None,
                 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    now = time.time()
    year, month, day, hh, mm, ss, wd, y, z = time.gmtime(now)
    s = "%s, %02d %3s %4d %02d:%02d:%02d GMT" % (
            WEEKS[wd],
            day, MONTHS[month], year,
            hh, mm, ss)
    return s


class WSGIAdaptor:
    def __init__(self, app, domain, port):
        self.app, self.domain, self.port = app, domain, port

    def make_environ(self, request, errsoc):
        if '?' in request.path:
            path_info, query = request.path.split('?', 1)
        else:
            path_info = request.path
            query = ''
        environ = {
            'wsgi.version':         (1, 0),
            'wsgi.url_scheme':      request.scheme,
            'wsgi.input':           cStringIO.StringIO(request.content),
            'wsgi.errors':          errsoc,
            'wsgi.multithread':     True,
            'wsgi.multiprocess':    False,
            'wsgi.run_once':        False,
            'SERVER_SOFTWARE':      version.NAMEVERSION,
            'REQUEST_METHOD':       request.method,
            'SCRIPT_NAME':          '',
            'PATH_INFO':            urllib.unquote(path_info),
            'QUERY_STRING':         query,
            'CONTENT_TYPE':         request.headers.get('Content-Type', [''])[0],
            'CONTENT_LENGTH':       request.headers.get('Content-Length', [''])[0],
            'SERVER_NAME':          self.domain,
            'SERVER_PORT':          self.port,
            # FIXME: We need to pick up the protocol read from the request.
            'SERVER_PROTOCOL':      "HTTP/1.1",
        }
        if request.client_conn.address:
            environ["REMOTE_ADDR"], environ["REMOTE_PORT"] = request.client_conn.address

        for key, value in request.headers.items():
            key = 'HTTP_' + key.upper().replace('-', '_')
            if key not in ('HTTP_CONTENT_TYPE', 'HTTP_CONTENT_LENGTH'):
                environ[key] = value
        return environ

    def error_page(self, soc, headers_sent, s):
        """
            Make a best-effort attempt to write an error page. If headers are
            already sent, we just bung the error into the page.
        """
        c = """
            <html>
                <h1>Internal Server Error</h1>
                <pre>%s"</pre>
            </html>
        """%s
        if not headers_sent:
            soc.write("HTTP/1.1 500 Internal Server Error\r\n")
            soc.write("Content-Type: text/html\r\n")
            soc.write("Content-Length: %s\r\n"%len(c))
            soc.write("\r\n")
        soc.write(c)

    def serve(self, request, soc):
        state = dict(
            response_started = False,
            headers_sent = False,
            status = None,
            headers = None
        )
        def write(data):
            if not state["headers_sent"]:
                soc.write("HTTP/1.1 %s\r\n"%state["status"])
                h = state["headers"]
                if 'server' not in h:
                    h["Server"] = [version.NAMEVERSION]
                if 'date' not in h:
                    h["Date"] = [date_time_string()]
                soc.write(str(h))
                soc.write("\r\n")
                state["headers_sent"] = True
            soc.write(data)
            soc.flush()

        def start_response(status, headers, exc_info=None):
            if exc_info:
                try:
                    if state["headers_sent"]:
                        raise exc_info[0], exc_info[1], exc_info[2]
                finally:
                    exc_info = None
            elif state["status"]:
                raise AssertionError('Response already started')
            state["status"] = status
            state["headers"] = flow.ODictCaseless(headers)
            return write

        errs = cStringIO.StringIO()
        try:
            dataiter = self.app(self.make_environ(request, errs), start_response)
            for i in dataiter:
                write(i)
            if not state["headers_sent"]:
                write("")
        except Exception, v:
            try:
                s = traceback.format_exc()
                self.error_page(soc, state["headers_sent"], s)
            # begin nocover
            except Exception, v:
                pass
            # end nocover
        return errs.getvalue()


class AppRegistry:
    def __init__(self):
        self.apps = {}

    def add(self, app, domain, port):
        """
            Add a WSGI app to the registry, to be served for requests to the
            specified domain, on the specified port.
        """
        self.apps[(domain, port)] = WSGIAdaptor(app, domain, port)

    def get(self, request):
        """
            Returns an WSGIAdaptor instance if request matches an app, or None.
        """
        return self.apps.get((request.host, request.port), None)
