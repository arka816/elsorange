import Orange.data
from orangecontrib.text.corpus import Corpus

from PyQt5.QtCore import QObject, pyqtSignal

import pandas as pd
pd.options.mode.chained_assignment = None 
import numpy as np

from elsapy.elsclient import ElsClient
from elsapy.elssearch import ElsSearch

import os
import sys

sys.path.append(os.path.dirname(__file__))

from fulltext import ArticleDownloader

METADATA_DOWNLOAD_PROGRESS = 10
FULLTEXT_DOWNLOAD_PROGRESS = 60

MAX_FULLTEXT_PER_KEYWORD = 50

class Worker(QObject):
    finished = pyqtSignal(Corpus)
    progress = pyqtSignal(int)
    message = pyqtSignal(str)
    error = pyqtSignal(str)

    metadataCodes = [
        ('title', 'dc:title'),
        ('author', 'dc:creator'),
        ('date', 'prism:coverDate'),
        ('abstract', 'abstract'),
        ('DOI', 'prism:doi')
    ]

    fieldTypeCodes = {
        'Abstract Title, Abstract, Keyword': 'TITLE-ABS-KEY',
        'Abstract': 'ABS',
        'Keyword': 'KEY',
        'Article Title': 'TITLE',
        'DOI': 'DOI',
        'ISSN': 'ISSN',
        'All fields': 'ALL'
    }

    def __init__(self, scopusApiKey, springerApiKey, sciencedirectApiKey, fieldType, searchText, recordCount, startDate, endDate, logging, downloadFullText):
        global METADATA_DOWNLOAD_PROGRESS, FULLTEXT_DOWNLOAD_PROGRESS

        QObject.__init__(self)

        self.scopusApiKey = scopusApiKey
        self.springerApiKey = springerApiKey
        self.sciencedirectApiKey = sciencedirectApiKey

        self.fieldType = fieldType
        self.searchText = searchText
        self.recordCount = recordCount

        self.startYear = startDate[:4]
        self.endYear = endDate[:4]

        self.logging = logging

        self.downloadFullText = downloadFullText

        if self.downloadFullText:
            self.metadataCodes.append(('full text', 'full_text'))
        else:
            METADATA_DOWNLOAD_PROGRESS = 70
            FULLTEXT_DOWNLOAD_PROGRESS = 0

    def __del__(self):
        self.logging.info('worker object deleted')

    def _fetch_results(self):
        """
            - captures input data
            - generates and executes scopus query
        """

        # check api key
        if self.scopusApiKey == "":
            self.error.emit('scopus api key empty')
            return pd.DataFrame()

        if self.springerApiKey == "":
            self.error.emit('springer api key empty')
            return pd.DataFrame()

        if self.sciencedirectApiKey == "":
            self.error.emit('sciencedirect api key empty')
            return pd.DataFrame()
        

        # generate scopus query
        query = f'{self.fieldTypeCodes[self.fieldType]}({self.searchText}) AND PUBYEAR > {self.startYear} AND PUBYEAR < {self.endYear}'

        # execute scopus query
        try:
            self.client = ElsClient(self.scopusApiKey)
        except:
            self.error.emit('api key invalid')
            return pd.DataFrame()

        self.doc_srch = ElsSearch(query,'scopus')
        
        try:
            self.doc_srch.execute(self.client, get_all = True)
        except:
            self.error.emit('could not execute scopus query. check internet.')
            return pd.DataFrame()

        results = self.doc_srch.results_df

        # limit results shown
        if len(results) > self.recordCount:
            results = results[:self.recordCount]
            self.logging.info(f"showing {len(results)} results")

        # check for error
        if 'error' in results.columns:
            self.message.emit(f"no articles found")
            self.error.emit('error fetching results')
            return pd.DataFrame()

        # update progressbar
        self.progress.emit(METADATA_DOWNLOAD_PROGRESS)
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
            self.message.emit(f"no articles found")
            self.error.emit('no records found')
            return pd.DataFrame()
        else:
            self.message.emit(f"{totalCount} articles")

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
            except Exception as ex:
                abstract = 'n/a'

            abstractDownloadCount += 1
            progress  = int(METADATA_DOWNLOAD_PROGRESS + (100 - METADATA_DOWNLOAD_PROGRESS - FULLTEXT_DOWNLOAD_PROGRESS) * abstractDownloadCount / totalCount)

            self.progress.emit(progress)
            self.message.emit(f"{abstractDownloadCount}/{totalCount} abstracts")

            return abstract

        # download abstracts
        final_df['abstract'] = results['link'].apply(get_abstract)
        del results

        # download full text
        # TODO: fix full text downloader
        if self.downloadFullText:
            final_df['prism:doi'] = final_df['prism:doi'].replace({np.nan: None})
            available_doi = final_df[final_df['prism:doi'] != None].shape[0]
            final_df.drop_duplicates(subset=['prism:doi'], inplace=True)

            self.message.emit(f"{final_df[final_df['abstract'] != None].shape[0]} abstracts downloaded")

            articleDownloader = ArticleDownloader(
                self.springerApiKey, 
                self.sciencedirectApiKey, 
                self.searchText, 
                min(available_doi, MAX_FULLTEXT_PER_KEYWORD), 
                self.logging,
                self.message,
                self.progress
            )
            # get publisher information
            final_df[['domain', 'url']] = final_df['prism:doi'].apply(lambda doi: pd.Series(articleDownloader.getPublisher(doi)))

            fullTextDict = articleDownloader.downloadArticles(final_df[['prism:doi', 'domain', 'url']])
            final_df['full_text'] = final_df['prism:doi'].apply(lambda doi: fullTextDict[doi] if doi in fullTextDict else '')

            self.message.emit(f"{final_df[final_df['full_text'] != ''].shape[0]} full texts downloaded")

            self.logging.info(f"scraper worked for {articleDownloader.articleDomainCount} domains")
            self.logging.info(f"downloaded full text for {articleDownloader.downloadCount} articles")

            final_df.drop(columns=['domain', 'url'], inplace=True)

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

    def run(self):
        print('worker started')
        self.message.emit('worker started')
        df = self._extract_data()
        if df.shape[0] != 0:
            meta_values, class_values = self._dataframe_to_corpus_entries(df)
            corpus = self._corpus_from_records(meta_values, class_values)
            self.finished.emit(corpus)
        else:
            self.error.emit("aborting...")
