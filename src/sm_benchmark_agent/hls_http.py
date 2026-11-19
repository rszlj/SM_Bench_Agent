"""Bounded synchronous HTTPS range reader for COGs (no full-tile fallback)."""
from collections import OrderedDict
import io
import re
from urllib.parse import urlsplit

BLOCK = 1024 * 1024


class RangeFS:
    def __init__(self, session):
        self.session = session
        self.sizes = {}
        self.bytes_received = 0
        self.requests = 0

    def range(self, url, start, end):
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname != 'data.lpdaac.earthdatacloud.nasa.gov'
                or parsed.query or not parsed.path.endswith('.tif')):
            raise FileNotFoundError('Not an allowed HLS COG')
        with self.session.get(url, headers={'Range':f'bytes={start}-{end}', 'Accept-Encoding':'identity'},
                              timeout=(20,60), stream=True) as response:
            self.requests += 1
            response.raise_for_status()
            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
            if response.status_code != 206 or not match:
                raise ValueError('Provider did not honor range; whole-tile fallback disabled')
            first,last,total=map(int,match.groups())
            if first != start or last != min(end,total-1) or not 0 <= first <= last < total:
                raise ValueError('Unexpected HTTP range response')
            payload=response.raw.read(last-first+2)
            if len(payload) != last-first+1:
                raise ConnectionError('Truncated range response; temporary transfer failure')
            self.bytes_received += len(payload)
            return payload,total

    def open(self, url, mode='rb', **kwargs):
        if mode not in ('r','rb'):
            raise ValueError('Read-only COG transport')
        if url not in self.sizes:
            _,self.sizes[url]=self.range(url,0,0)
        return RangeReader(self,url,self.sizes[url])


class RangeReader(io.RawIOBase):
    def __init__(self,fs,url,size):
        self.fs,self.url,self.size=fs,url,size
        self.position=0
        self.blocks=OrderedDict()

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.position

    def seek(self,offset,whence=0):
        base={0:0,1:self.position,2:self.size}.get(whence)
        if base is None or base+offset < 0:
            raise ValueError('Invalid COG seek')
        self.position=base+offset
        return self.position

    def read(self,size=-1):
        if self.closed:
            raise ValueError('Closed COG')
        count=max(0,self.size-self.position) if size is None or size<0 else min(size,max(0,self.size-self.position))
        if count>16*BLOCK:
            raise ValueError('Excessive COG read; whole-file reads disabled')
        chunks=[]
        while count:
            block=self.position//BLOCK
            if block not in self.blocks:
                payload,total=self.fs.range(self.url,block*BLOCK,min((block+1)*BLOCK,self.size)-1)
                if total != self.size:
                    raise ValueError('COG changed during read')
                self.blocks[block]=payload
                if len(self.blocks)>8:
                    self.blocks.popitem(last=False)
            self.blocks.move_to_end(block)
            offset=self.position%BLOCK
            piece=self.blocks[block][offset:offset+count]
            if not piece:
                raise ValueError('Invalid COG block')
            chunks.append(piece)
            self.position+=len(piece)
            count-=len(piece)
        return b''.join(chunks)

    def readinto(self,buffer):
        payload=self.read(len(buffer))
        buffer[:len(payload)]=payload
        return len(payload)
