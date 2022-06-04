import Orange.data
from orangewidget.widget import OWBaseWidget, Output, settings
from orangewidget import gui
from orangecontrib.text.corpus import Corpus

from elsapy.elsclient import ElsClient
from elsapy.elssearch import ElsSearch

import pandas as pd
pd.options.mode.chained_assignment = None 
import numpy as np
import datetime

METADATA_DOWNLOAD_PROGRESS = 30

from tldextract import extract
import requests
import time, PyPDF2
import pathlib, requests
from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager
import os
import tempfile
import shutil

"""
tandfonline does not issue api keys; rather uses cloudflare services as a means of protection from bots.
requests library would not work. neither would http2 or postman for example for the same reason.

two ways to watch for automated chrome file downloads since webdriver does not fire any native events to selenium.
    1. open chrome://downloads and watch progressbar for completion of download
    2. use filesystem observers like watchdog
"""
from watchdog.observers import Observer

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

class ArticleDownloader(Article):
    def __init__(self, springerApiKey, sciencedirectApiKey):
        self.springerApiKey = springerApiKey
        self.sciencedirectApiKey = sciencedirectApiKey

        self.springerClient = SpringerClient(springerApiKey)
        self.sciencedirectClient = SDClient(sciencedirectApiKey)

    def _mdpi_download(self, url):
        print("mdpi downloading", url)
        pdfUrl = url.strip("/") + "/pdf"
        res = requests.get(pdfUrl)
        return self._write_to_temp_file(res)

    def downloadArticle(self, doi):
        if doi == None:
            return ''
        print(f"downloading full text for {doi}")
        text = ''

        res = requests.get(f"https://www.doi.org/{doi}", allow_redirects=True)
        if res.status_code == 200:
            # check first for doi.org redirects to reduce worst case number of requests sent
            subdomain, domain, suffix = extract(res.url)

            print(res.url, domain)

            try:
                if domain == 'springer':
                    text = self.springerClient.exec_request(doi)
                elif domain == 'elsevier' or domain == 'sciencedirect':
                    text = self.sciencedirectClient.exec_request(doi)
                elif domain == 'tandfonline':
                    pass
                elif domain == 'mdpi':
                    text = self._mdpi_download(res.url)
            except:
                pass
        else:
            # try each manually
            text = self.springerClient.exec_request(doi)
            if text == None:
                text = self.sciencedirectClient.exec_request(doi)
            if text == None:
                text = ''

        if text != '':
            print(f"downloaded full text for {doi}")

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
            downloads abstract for each article and
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
