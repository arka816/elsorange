import time, pathlib, requests
from article import Article

class SpringerClient(Article):
    """a class that implements a Python interface to elsevier article retrieval api"""
    __url_base = "http://api.springer.com/metadata/json"                    # base url
    __content_url_base = "https://link.springer.com/content/pdf/"           # base url for pdf
    
    def __init__(self, api_key, local_dir=None):
        super().__init__()
        self.api_key = api_key
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

    def exec_request(self, doi):
        # throttle if needed
        interval = time.time() - self._Article__last_request_timestamp
        if interval < self._Article__min_req_interval:
            time.sleep(self._Article__min_req_interval - interval)

        # contruct request params
        params = {
            'q': f"doi:{doi}",
            'api_key': self.api_key
        }

        # send request
        res = requests.get(
            self.__url_base,
            params=params
        )
        
        # TODO: add support for downloading files in future

        # process response
        if res.status_code == 200:
            jsonResponse = res.json()
            totalCount = len(jsonResponse['records'])

            if totalCount > 0:
                # result exists; download pdf
                contentUrl = f"{self.__content_url_base}{doi}.pdf"
                contentRes = requests.get(contentUrl)
                if contentRes.status_code == 200:
                    return self._write_to_temp_file(contentRes)
        return None


client = SpringerClient("0c2ad3a03343222e1b2df1d081da604f")
text = client.exec_request("10.1007/s10404-009-0428-3")
