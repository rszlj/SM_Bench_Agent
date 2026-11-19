"""Opt-in transport retry layer; scientific HLS processing is unchanged."""
import time
import os
from pathlib import Path
from .hls_http import RangeFS
from .hls import EarthdataHLS


def failure_kind(exc):
    import requests
    from urllib3.exceptions import ProtocolError, ReadTimeoutError, IncompleteRead
    code=getattr(getattr(exc,'response',None),'status_code',None)
    if code in (401,403,429):return 'review_required'
    if code in (408,500,502,503,504):return 'transient'
    if isinstance(exc,(requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError,
                       ConnectionError, TimeoutError, ProtocolError, ReadTimeoutError, IncompleteRead)):
        return 'transient'
    return 'review_required'


class ResilientRangeFS(RangeFS):
    """Retry the SAME bounded HTTP range, never redownload a whole COG tile."""
    def __init__(self, session, *, retries=4, sleep=time.sleep, report=None):
        if type(retries) is not int or not 0<=retries<=6:raise ValueError('Invalid retry bound')
        super().__init__(session)
        self.retries,self.sleep,self.report=retries,sleep,report
        self.last_failure=None

    def range(self,url,start,end):
        self.last_failure=None
        for attempt in range(self.retries+1):
            try:
                result=super().range(url,start,end)
                self.last_failure=None
                return result
            except Exception as exc:
                kind=failure_kind(exc)
                self.last_failure=dict(kind=kind,error_type=type(exc).__name__,
                    http_status=getattr(getattr(exc,'response',None),'status_code',None),
                    attempt=attempt+1)
                if self.report:self.report(dict(self.last_failure))
                if kind!='transient' or attempt==self.retries:raise
                # Deterministic capped backoff; responses/auth data are never logged.
                self.sleep(min(5*2**attempt,60))


class ResilientEarthdataHLS(EarthdataHLS):
    """Optional provider injection preserving existing scientific checkpoint hashes."""
    def __init__(self, *, report=None):self.report=report

    def fetch(self,unit,item):
        if not hasattr(self,'fs'):
            import earthaccess
            from .earthdata_setup import check_local
            if check_local()['status']!='configured':raise ValueError('Earthdata credentials require setup')
            previous=os.environ.get('NETRC');os.environ['NETRC']=str(Path.home()/'.netrc')
            try:auth=earthaccess.login(strategy='netrc',persist=False)
            finally:
                if previous is None:os.environ.pop('NETRC',None)
                else:os.environ['NETRC']=previous
            if not auth.authenticated:raise ValueError('Earthdata authentication failed')
            self.fs=ResilientRangeFS(earthaccess.get_requests_https_session(),report=self.report)
        return super().fetch(unit,item)
