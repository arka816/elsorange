import requests
import time
import datetime
import PyPDF2
import pathlib
import os
import tempfile
import shutil
import pytz
import json
from tldextract import extract
import requests
from threading import Thread
import queue


"""
tandfonline does not issue api keys; rather uses cloudflare services as a means of protection from bots.
requests library would not work. neither would http2 or postman for example for the same reason.

two ways to watch for automated chrome file downloads since webdriver does not fire any native events to selenium.
    1. open chrome://downloads and watch progressbar for completion of download
    2. use filesystem observers like watchdog
"""
from watchdog.observers import Observer

from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager


DOI_WAIT_TIME = 5
DOI_MAX_COUNT = 10

MAX_THREADS = 4

logging = None

class Article:
    """base class for article downloaders""" 
    __chunk_size = 4096                                                 # chunk size of file to write in every iteration
    __last_request_timestamp = time.time()                              # timestamp of last request made to elsevier api
    __min_req_interval = 1                                              # minimum interval between requests : 1 second

    def __init__(self):
        pass

    def _write_to_temp_file(self, res):
        f = tempfile.TemporaryFile()
        for chunk in res.iter_content(self.__chunk_size):
            f.write(chunk)
        del res
        # convert pdf to text
        text = self._pdf_to_text(f)
        return text

    def _pdf_to_text(self, f):
        pdfReader = PyPDF2.PdfFileReader(f)
        text = ''

        for i in range(pdfReader.numPages):
            # extract text from page
            text += pdfReader.getPage(i).extractText()
        f.close()
        return text

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

class TFClient(Article):
    def __init__(self):
        # create temporary directory
        self.dirpath = tempfile.mkdtemp()

        op = webdriver.ChromeOptions()
        # op.add_argument('headless')
        op.add_experimental_option(
            'prefs', 
            {
                "download.default_directory": self.dirpath, #Change default directory for downloads
                "download.prompt_for_download": False, #To auto download the file
                "download.directory_upgrade": True,
                "plugins.always_open_pdf_externally": True #It will not show PDF directly in chrome
            }
        )
        self.driver = webdriver.Chrome(ChromeDriverManager().install(), options=op)

        # register filesystem observer
        self.observer = Observer()
        self.observer.schedule(self._handle_download, self.dirpath, recursive=False)
        self.observer.start()

    def cleanup(self):
        # remove temporary directory
        shutil.rmtree(self.dirpath)
        self.driver.close()
        self.driver.quit()
        self.observer.stop()
        self.observer.join()

    def _handle_download(self):
        f = open(self._get_filename())
        text = self._pdf_to_text(f)

    def _get_filename(self):
        # fetches last created file in specified directory
        filename = max([os.path.join(self.dirpath, f) for f in os.listdir(self.dirpath)], key=os.path.getctime)
        return filename

    def exec_request(self, doi):
        self.doi = doi
        url = f"https://www.tandfonline.com/doi/pdf/{doi}?download=true"
        self.driver.get(url)

class SPClient(Article):
    # SagePub client
    __metadata_url_base = "http://dx.doi.org"                    # base url
    __allowed = True

    # __rate_limit_reset = 0
    # __rate_limit = 0
    # __rate_limit_remaining = 0

    __RATE_LIMIT = 'CR-TDM-Rate-Limit'
    __RATE_LIMIT_REMAINING = 'CR-TDM-Rate-Limit-Remaining'
    __RATE_LIMIT_RESET = 'CR-TDM-Rate-Limit-Reset'

    __rate_limit_dict = dict()
    __TDM_headers = [
        __RATE_LIMIT,                # Maximum number of full-text downloads that are allowed to be performed in the defined rate limit window
        __RATE_LIMIT_REMAINING,      # Number of downloads left for the current rate limit window
        __RATE_LIMIT_RESET           # Remaining time (in UTC epoch seconds) before the rate limit resets and a new rate limit window is started
    ]
    __MAX_RESET_WAITING_TIME = 5            # waiting for more than 5 seconds for the rate limit window to reset does not make sense

    def __init__(self):
        now_utc = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)

        la_timezone = pytz.timezone('America/Los_Angeles')
        la_local_time = la_timezone.normalize(now_utc.astimezone(la_timezone))

        if 0 <= la_local_time.weekday() <= 4:
            # if la time is between monday and friday (both inclusive)
            self.la_local_time = la_local_time
        else:
            self.__allowed = False
            return

    def exec_request(self, doi):
        if not self.__allowed:
            logging.warning("sagepub API cannot be used on weekends")
            return

        if 0 <= self.la_local_time.hour < 12:
            # between 12 am and 12 pm ()
            self._Article__min_req_interval = 6
        else:
            # between 12 pm and 12 am
            self._Article__min_req_interval = 2

        interval = time.time() - self._Article__last_request_timestamp
        if interval < self._Article__min_req_interval:
            time.sleep(self._Article__min_req_interval - interval)

        headers = {
            'Accept': 'application/json'
        }
        url = f"{self.__metadata_url_base}/{doi}"

        # Step 1: make request for metadata at dx.doi.org
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            # metadata received
            metadata = r.json()
            # TODO: check if license is in whitelist (accepted list of licenses)
            if "link" in metadata:
                # Step 2: full text link available, download full text
                for link in metadata["link"]:
                    if link["content-type"] == "application/pdf":
                        # Step 3: check if member domain server has already been requested
                        # if so then check for rate limit data
                        _, domain, _ = extract(link['URL'])
                        if domain in self.__rate_limit_dict:
                            rate_limit_data = self.__rate_limit_dict[domain]
                            if 'timestamp' in rate_limit_data and \
                                self.__RATE_LIMIT_RESET in rate_limit_data:
                                # check if last rate limit window is over
                                next_reset_time = rate_limit_data['timestamp'] + rate_limit_data[self.__RATE_LIMIT_RESET]
                                if time.time() >= next_reset_time:
                                    # last rate limit window is over
                                    pass
                                else:
                                    # last rate limit window is not over
                                    if rate_limit_data[self.__RATE_LIMIT_REMAINING] > 0:
                                        pass
                                    else:
                                        # no more requests in current rate limit window
                                        # wait if waiting is logically plausible
                                        wait_time = next_reset_time - time.time()
                                        if wait_time < self.__MAX_RESET_WAITING_TIME:
                                            time.sleep(wait_time)
                                        else:
                                            return None

                        # Step 4: if new domain or if requests left in current request window
                        # make request for full text pdf
                        contentRes = requests.get(link['URL'])
                        if contentRes.status_code == 200:
                            # full text available at link
                            # Step5: check for TDM headers and store or update them
                            if domain not in self.__rate_limit_dict:
                                self.__rate_limit_dict[domain] = dict()

                            headers = contentRes.headers
                            for header in self.__TDM_headers:
                                if header in headers.keys():
                                    self.__rate_limit_dict[domain][header] = headers[header]
                            self.__rate_limit_dict[domain]["timestamp"] = time.time()

                            # Step 6: extract text from downloaded pdf
                            return self._write_to_temp_file(contentRes)

        return None

class ArticleDownloader(Article):
    articleDomainCount = dict()
    articleDownloadCount = dict()
    downloadCount = 0

    cacheFilepaths = dict()
    CACHE_PATH_FILENAME = "filepaths.json"

    STOP_HTTP_CODES = [403, 401, 404, 503]

    def __init__(self, springerApiKey, sciencedirectApiKey, keyword, downloadCap, logger):
        self.springerApiKey = springerApiKey
        self.sciencedirectApiKey = sciencedirectApiKey
        self.keyword = keyword
        self.downloadCap = downloadCap

        global logging
        logging = logger

        # cache folder for full text
        local_folder = os.getenv('LOCALAPPDATA')
        self.cache_folder = os.path.join(local_folder, "elsevier")

        if not os.path.exists(self.cache_folder):
            try:
                os.mkdir(self.cache_folder)
            except:
                logging.error("error creating cache folder")

        self.jsonFilePath = os.path.join(self.cache_folder, self.CACHE_PATH_FILENAME)
        if os.path.isfile(self.jsonFilePath):
            try:
                with open(self.jsonFilePath, 'r') as f:
                    self.cacheFilepaths = json.load(f)
            except Exception as ex:
                logging.error("error loading filepath caches.")

    def __del__(self):
        self.__cleanup__()

    def __cleanup__(self):
        with open(self.jsonFilePath, 'w') as f:
            json.dump(self.cacheFilepaths, f, indent=4)

    def _mdpi_download(self, url):
        pdfUrl = url.strip("/") + "/pdf"
        logging.info(f"mdpi downloading {pdfUrl}")
        
        res = requests.get(pdfUrl)
        if res.status_code == 200:
            return self._write_to_temp_file(res)

        return None

    def _get_domain(self, doi):
        # doi request
        count = 0
        while count < DOI_MAX_COUNT:
            if count > 1:
                logging.info(f"retrying doi.org request for {doi}")
            count += 1
            res = requests.get(f"https://www.doi.org/{doi}", allow_redirects=True)
            if res.status_code == 200:
                _, domain, _ = extract(res.url)
                res.close()
                return domain, res.url
            else:
                _, domain, _ = extract(res.url)
                if res.status_code in self.STOP_HTTP_CODES:
                    # authorization issues
                    res.close()
                    return domain, res.url
                res.close()
                time.sleep(DOI_WAIT_TIME)

        return None, None

    def __json_length__(self, dict):
        return sum([len(dict[keyword]) for keyword in dict])

    def _cache_full_text(self, doi, text):
        if self.keyword in self.cacheFilepaths:
            if doi in self.cacheFilepaths[self.keyword]:
                return
        else:
            # mutex issue
            self.cacheFilepaths[self.keyword] = dict()

        filename = f"{self.__json_length__(self.cacheFilepaths) + 1}.txt"
        filepath = os.path.join(self.cache_folder, filename)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(text)
        except Exception as ex:
            logging.error(f"could not write text to file {filepath}. {ex}")
        else:      
            # mutex issue      
            self.cacheFilepaths[doi] = filepath

    def getPublisher(self, doi):
        if doi is None or doi == '':
            return [None, None]

        # doi request
        domain, url = self._get_domain(doi)

        if domain != None:
            if domain in self.articleDomainCount:
                self.articleDomainCount[domain] += 1
            else:
                self.articleDomainCount[domain] = 1

            if domain not in self.articleDownloadCount:
                self.articleDownloadCount[domain] = 0

        return [domain, url]
        
    def downloadArticles(self, data):
        fullTextQueue = queue.Queue()
        fullTextDict = dict()

        for _, row in data.iterrows():
            fullTextQueue.put((row['prism:doi'], row['domain'], row['url']))

        workers = [
            Thread(target=self.downloadArticleEventLoop, args=(fullTextQueue, fullTextDict)) 
            for _ in range(MAX_THREADS)
        ]

        for _ in workers:
            fullTextQueue.put((None, None, None))

        for worker in workers:
            worker.start()

        for worker in workers:
            worker.join()

        return fullTextDict

    def downloadArticleEventLoop(self, fullTextQueue, fullTextDict):
        while True:
            doi, domain, url = fullTextQueue.get()

            if doi is None or domain is None or url is None:
                break

            fullText = self.downloadArticle(doi, domain, url)
            fullTextDict[doi] = fullText

    def downloadArticle(self, doi, domain, url):
        '''
            runs on a single thread
            global values updated:
                - self.articleDownloadCount
                - self.downloadCount
                - self.cacheFilepaths
                - self.logger (in future updates)
        '''
        if self.downloadCount > self.downloadCap:
            return None

        if doi is None or doi == '':
            return None

        logging.info(f"downloading full text for {doi}")
        text = ''

        # check if doi already exists in cache
        if self.keyword in self.cacheFilepaths:
            if doi in self.cacheFilepaths[self.keyword]:
                filename = self.cacheFilepaths[doi]
                filepath = os.path.join(self.cache_folder, filename)

                if os.path.isfile(filepath):
                    try:
                        with open(filepath) as f:
                            text = f.read()
                    except:
                        logging.warning(f"doi: {doi} full-text not found in cache")
                    else:
                        logging.info(f"fetched {doi} from cache")
                        return text
                else:
                    logging.warning(f"{filepath} is not a file")
            else:
                logging.warning(f"{doi} not in cache for {self.keyword}")
        else:
            logging.warning(f"search prompt {self.keyword} not in cache")
            

        self.springerClient = SpringerClient(self.springerApiKey)
        self.sciencedirectClient = SDClient(self.sciencedirectApiKey)

        if domain != None:
            try:
                if domain == 'springer':
                    text = self.springerClient.exec_request(doi)
                elif domain == 'elsevier' or domain == 'sciencedirect':
                    text = self.sciencedirectClient.exec_request(doi)
                elif domain == 'tandfonline':
                    pass
                elif domain == 'mdpi':
                    text = self._mdpi_download(url)

                if text != '' and text != None:
                    # mutex issue
                    self.articleDownloadCount[domain] += 1
                    self.downloadCount += 1
            except:
                pass
        else:
            pass

        if text != '':
            logging.info(f"downloaded full text for {doi}")
            # cache
            self._cache_full_text(doi, text)
        else:
            logging.warning(f"could not download full text for {doi}")

        return text
