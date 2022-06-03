import requests
import pathlib
import os, json, time
from article import Article

class SDClient(Article):
    """a class that implements a Python interface to elsevier article retrieval api"""
    __url_base = "https://api.elsevier.com/content/article/doi/"            # base url
    __elsapy_version  = '0.5.0'                                             # version of elsapy
    __user_agent = "elsapy-v%s" % __elsapy_version                       

    def __init__(self, api_key, inst_token=None, local_dir=None):
        super().__init__()
        self.api_key = api_key
        self.inst_token = inst_token
        if not local_dir:
            self.local_dir = pathlib.Path.cwd() / 'data'
        else:
            self.local_dir = pathlib.Path(local_dir)
        if not self.local_dir.exists():
            self.local_dir.mkdir()

    # properties
    @property
    def api_key(self):
        """Get the apiKey for the client instance"""
        return self._api_key
    @api_key.setter
    def api_key(self, api_key):
        """Set the apiKey for the client instance"""
        self._api_key = api_key

    @property
    def inst_token(self):
        """Get the instToken for the client instance"""
        return self._inst_token
    @inst_token.setter
    def inst_token(self, inst_token):
        """Set the instToken for the client instance"""
        self._inst_token = inst_token

    def exec_request(self, doi):
        # throttle if needed
        interval = time.time() - self._Article__last_request_timestamp
        if interval < self._Article__min_req_interval:
            time.sleep(self._Article__min_req_interval - interval)

        # contruct request params
        self.URL = f"{self.__url_base}{doi}"
        headers = {
            "X-ELS-APIKey"  : self.api_key,
            "User-Agent"    : self.__user_agent,
            "Accept"        : 'application/pdf'
        }
        if self.inst_token:
            headers["X-ELS-Insttoken"] = self.inst_token

        # send request
        res = requests.get(
            self.URL,
            headers = headers
        )
        
        # TODO: add support for downloading files in future
        # filepath = os.path.join(self.local_dir, f"{scopus_id}.pdf")

        # process response
        if res.status_code == 200:
            return self._write_to_temp_file(res)
        
        return None
    
client = SDClient("d3fe5ee3d9159e15b538f681578c385b")
r = client.exec_request("10.1016/j.jheap.2022.04.002")
