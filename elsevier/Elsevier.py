import Orange.data
from orangewidget.widget import OWBaseWidget, Output, settings
from orangewidget import gui
from orangecontrib.text.corpus import Corpus

from elsapy.elsclient import ElsClient
from elsapy.elssearch import ElsSearch

import numpy as np
import pandas as pd
pd.options.mode.chained_assignment = None 
import datetime

METADATA_DOWNLOAD_PROGRESS = 30

from tldextract import extract
import requests
import time
import PyPDF2
import pathlib
import requests
from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager
import os
import tempfile
import shutil
import pytz
import json

"""
tandfonline does not issue api keys; rather uses cloudflare services as a means of protection from bots.
requests library would not work. neither would http2 or postman for example for the same reason.

two ways to watch for automated chrome file downloads since webdriver does not fire any native events to selenium.
    1. open chrome://downloads and watch progressbar for completion of download
    2. use filesystem observers like watchdog
"""
from watchdog.observers import Observer

DOI_WAIT_TIME = 5
DOI_MAX_COUNT = 10

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
            print("sagepub API cannot be used on weekends")
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

    def __init__(self, springerApiKey, sciencedirectApiKey):
        self.springerApiKey = springerApiKey
        self.sciencedirectApiKey = sciencedirectApiKey

        self.springerClient = SpringerClient(springerApiKey)
        self.sciencedirectClient = SDClient(sciencedirectApiKey)

        # cache folder for full text
        local_folder = os.getenv('LOCALAPPDATA')
        self.cache_folder = os.path.join(local_folder, "elsevier")

        if not os.path.exists(self.cache_folder):
            try:
                os.mkdir(self.cache_folder)
            except:
                print("error creating cache folder")

        self.jsonFilePath = os.path.join(self.cache_folder, self.CACHE_PATH_FILENAME)
        if os.path.isfile(self.jsonFilePath):
            with open(self.jsonFilePath, 'r') as f:
                self.cacheFilepaths = json.load(f)

    def __del__(self):
        with open(self.jsonFilePath, 'w') as f:
            json.dump(self.cacheFilepaths, f, indent=4)

    def _mdpi_download(self, url):
        pdfUrl = url.strip("/") + "/pdf"
        print("mdpi downloading", pdfUrl)
        
        res = requests.get(pdfUrl)
        if res.status_code == 200:
            return self._write_to_temp_file(res)

        return None

    def _get_domain(self, doi):
        # doi request
        count = 0
        while count < DOI_MAX_COUNT:
            if count > 1:
                print('retrying doi.org request for', doi)
            count += 1
            res = requests.get(f"https://www.doi.org/{doi}", allow_redirects=True)
            if res.status_code == 200:
                print(res.url)
                _, domain, _ = extract(res.url)
                res.close()
                return domain, res.url
            else:
                _, domain, _ = extract(res.url)
                print(res.status_code, res.reason, res.url, domain)
                if res.status_code in self.STOP_HTTP_CODES:
                    # authorization issues
                    res.close()
                    return domain, res.url
                res.close()
                time.sleep(DOI_WAIT_TIME)

        return None, None

    def _cache_full_text(self, doi, text):
        if doi in self.cacheFilepaths:
            return

        filename = f"{len(self.cacheFilepaths) + 1}.txt"
        filepath = os.path.join(self.cache_folder, filename)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(text)
        except Exception as ex:
            print(f"could not write text to file {filepath}. {ex}")
        else:            
            self.cacheFilepaths[doi] = filepath

    def downloadArticle(self, doi):
        if doi is None or doi == '':
            return None

        print(f"downloading full text for {doi}")
        text = ''

        # check if doi already exists in cache
        if doi in self.cacheFilepaths:
            filename = self.cacheFilepaths[doi]
            filepath = os.path.join(self.cache_folder, filename)

            if os.path.isfile(filepath):
                try:
                    with open(filepath) as f:
                        text = f.read()
                except:
                    print(f"doi: {doi} full-text not found in cache")
                else:
                    print(f"fetched {doi} from cache")
                    return text
        

        # doi request
        domain, url = self._get_domain(doi)

        if domain != None:
            if domain in self.articleDomainCount:
                self.articleDomainCount[domain] += 1
            else:
                self.articleDomainCount[domain] = 1

            if domain not in self.articleDownloadCount:
                self.articleDownloadCount[domain] = 0

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
                    self.articleDownloadCount[domain] += 1
                    self.downloadCount += 1
            except:
                pass
        else:
            pass

        if text != '':
            print(f"downloaded full text for {doi}")
            # cache
            self._cache_full_text(doi, text)
        else:
            print(f"could not download full text for {doi}")

        return text


class Elsevier(OWBaseWidget):
    name = "Elsevier"
    description = "Downloads elsevier article abstracts using scopus and renders them usable for viewing as a corpus in orange3."
    icon = "icons/elsevier.svg"
    priority = 10

    class Outputs:
        articles = Output("Articles", Corpus)

    want_main_area = False
    resizing_enabled = False

    scopusApiKey = settings.Setting("")
    springerApiKey = settings.Setting("")
    sciencedirectApiKey = settings.Setting("")
    searchText = settings.Setting("")
    fieldType = settings.Setting(0)
    recordCount = settings.Setting(100)
    startDate = settings.Setting('1991-08-15')
    endDate = settings.Setting('2000-02-24')

    fieldTypeItems = (
        'Abstract Title, Abstract, Keyword',
        'Abstract',
        'Keyword',
        'Article Title',
        'DOI',
        'ISSN',
        'All fields'
    )

    fieldTypeCodes = {
        'Abstract Title, Abstract, Keyword': 'TITLE-ABS-KEY',
        'Abstract': 'ABS',
        'Keyword': 'KEY',
        'Article Title': 'TITLE',
        'DOI': 'DOI',
        'ISSN': 'ISSN',
        'All fields': 'ALL'
    }

    metadataCodes = [
            ('title', 'dc:title'),
            ('author', 'dc:creator'),
            ('date', 'prism:coverDate'),
            ('abstract', 'abstract'),
            ('DOI', 'prism:doi'),
            ('full text', 'full_text')
        ]


    def __init__(self):
        super().__init__()

        # GUI
        self.apiKeyBox = gui.widgetBox(self.controlArea, "API key")
        gui.lineEdit(self.apiKeyBox, self, 'scopusApiKey', 'scopus api key', valueType=str)
        gui.lineEdit(self.apiKeyBox, self, 'springerApiKey', 'springer api key', valueType=str)
        gui.lineEdit(self.apiKeyBox, self, 'sciencedirectApiKey', 'sciencedirect api key', valueType=str)

        gui.separator(self.controlArea)

        self.searchBox = gui.widgetBox(self.controlArea, "Search", orientation=2)
        gui.comboBox(self.searchBox, self, 'fieldType', 'choose field', items=self.fieldTypeItems)
        gui.lineEdit(self.searchBox, self, 'searchText', 'enter keyword', valueType=str)
        gui.spin(self.searchBox, self, 'recordCount', minv=0, maxv=5000, step=1, label='number of records')

        gui.separator(self.controlArea)

        self.dateBox = gui.widgetBox(self.controlArea, "date", orientation=1)

        self.startCalendar = gui.DateTimeEditWCalendarTime(self.dateBox, format='yyyy-MM-dd')
        self.startCalendar.move(20, 20)
        self.startCalendar.set_datetime(datetime.datetime.strptime(self.startDate, "%Y-%m-%d"))

        self.endCalendar = gui.DateTimeEditWCalendarTime(self.dateBox, format='yyyy-MM-dd')
        self.endCalendar.move(20, 60)
        self.endCalendar.set_datetime(datetime.datetime.strptime(self.endDate, "%Y-%m-%d"))

        self.dateBox.setMinimumHeight(100)

        gui.separator(self.controlArea)

        self.controlBox = gui.widgetBox(self.controlArea, orientation=1)
        gui.button(self.controlBox, self, 'SEARCH', callback=self._start_download)

        self.info.set_input_summary(self.info.NoInput)

    def _fetch_results(self):
        """
            - captures input data
            - generates and executes scopus query
        """

        # check api key
        if self.scopusApiKey == "":
            self.error('scopus api key empty')
            self.progressBarFinished()

        if self.springerApiKey == "":
            self.error('springer api key empty')
            self.progressBarFinished()

        if self.sciencedirectApiKey == "":
            self.error('sciencedirect api key empty')
            self.progressBarFinished()

        # capture input data
        fieldType = self.fieldTypeItems[self.fieldType]
        searchText = self.searchText
        recordCount = self.recordCount

        startDate = self.startCalendar.textFromDateTime(self.startCalendar.dateTime())
        endDate = self.endCalendar.textFromDateTime(self.endCalendar.dateTime())

        self.startDate = startDate
        self.endDate = endDate

        startYear = startDate[:4]
        endYear = endDate[:4]

        # generate scopus query
        query = f'{self.fieldTypeCodes[fieldType]}({searchText}) AND PUBYEAR > {startYear} AND PUBYEAR < {endYear}'

        # execute scopus query
        try:
            self.client = ElsClient(self.scopusApiKey)
        except:
            self.error('api key invalid')
            self.progressBarFinished()

        self.doc_srch = ElsSearch(query,'scopus')
        
        try:
            self.doc_srch.execute(self.client, get_all = True)
        except:
            self.error('could not execute scopus query. check internet.')
            self.progressBarFinished()

        results = self.doc_srch.results_df

        # limit results shown
        if len(results) > recordCount:
            results = results[:recordCount]
            print("showing", len(results), "results")

        # check for error
        if 'error' in results.columns:
            self.info.set_output_summary(f"no articles found")
            self.error('error fetching results')
            self.progressBarFinished()
            return pd.DataFrame()

        # update progressbar
        self.progressBarSet(METADATA_DOWNLOAD_PROGRESS)

        return results

    def _extract_data(self):
        """
            downloads abstract and full text (if available) for each article and
            returns dataframe with columns
            1. title
            2. author(/s)
            3. date of publication
            4. DOI
            5. abstract
        """

        results = self._fetch_results()
        totalCount = len(results)

        if totalCount == 0:
            self.info.set_output_summary(f"no articles found")
            self.warning('no records found')
            self.progressBarFinished()
            return pd.DataFrame()
        else:
            self.info.set_output_summary(f"{totalCount} articles")

        final_df = results[['dc:title', 'dc:creator', 'prism:coverDate', 'prism:doi']]
        final_df['prism:coverDate'] = results['prism:coverDate'].apply(lambda d: d.strftime('%d-%m-%Y'))

        abstractDownloadCount = 0
        progress = METADATA_DOWNLOAD_PROGRESS

        # function for downloading abstracts
        def get_abstract(link):
            nonlocal abstractDownloadCount, progress, self
            scopus_link = link['self']

            try:
                rawdata = self.client.exec_request(scopus_link)
            except:
                self.error('could not fetch abstract. check internet.')
            
            try:
                response = rawdata['abstracts-retrieval-response']
                abstract = response['coredata']['dc:description']
            except:
                abstract = 'n/a'

            abstractDownloadCount += 1
            progress  = int(METADATA_DOWNLOAD_PROGRESS + (100 - METADATA_DOWNLOAD_PROGRESS) * abstractDownloadCount / totalCount)
            self.progressBarSet(progress)
            return abstract

        # download abstracts
        final_df['abstract'] = results['link'].apply(get_abstract)
        del results

        # download full text
        articleDownloader = ArticleDownloader(self.springerApiKey, self.sciencedirectApiKey)
        final_df['prism:doi'] = final_df['prism:doi'].replace({np.nan: None})
        final_df['full_text'] = final_df['prism:doi'].apply(articleDownloader.downloadArticle)

        print(articleDownloader.articleDomainCount)
        print("downloaded full text for", articleDownloader.downloadCount, "articles")

        return final_df

    def _dataframe_to_corpus_entries(self, df):
        """
            create corpus entries from dataframe records

            Args:
                - df : dataframe containing columns :- title, author, date of publication, DOI, abstract

            Returns:
                - metadata: an n*m array where n is the number of articles and m is the number of 
                            attributes (title, author...) for each article
                - class_values: list where elements are class values for each article (empty in our case)
        """
        class_values = []
        metadata = np.empty((len(df), len(df.columns)), dtype=object)

        for index, row in df.iterrows():
            fields = []

            for _, field_key in self.metadataCodes:
                fields.append(row[field_key])

            metadata[index] = np.array(fields, dtype=object)[None, :]

        return metadata, class_values

    def _corpus_from_records(self, meta_values, class_values):
        """
            converts records to a corpus

            Args:
                - metadata: an n*m array where n is the number of articles and m is the number of 
                            attributes (title, author...) for each article
                - class_values: list where elements are class values for each article (empty in our case)

            Returns:
                - corpus: the output corpus suitable for a corpus viewer
        """

        meta_vars = []

        for field_name, _ in self.metadataCodes:
            meta_vars.append(Orange.data.StringVariable.make(field_name))
            if field_name == 'title':
                meta_vars[-1].attributes['title'] = True
                

        domain = Orange.data.Domain([], metas = meta_vars)

        return Corpus(domain=domain, metas=meta_values)

    def _send_article(self):
        """
            the handler for the search button

            - extracts data from scopus query result
            - converts extracted data to metadata and class values
            - generates corpus from said metadata and class values
            - signals the corpus to the output stream
        """

        self.progress = Orange.widgets.gui.ProgressBar(self, 1)
        self.progressBarInit()
        df = self._extract_data()
        meta_values, class_values = self._dataframe_to_corpus_entries(df)
        corpus = self._corpus_from_records(meta_values, class_values)
        self.progressBarFinished()
        self.Outputs.articles.send(corpus)

    def _start_download(self):
        self._send_article()
