import Orange.data
from orangewidget.widget import OWBaseWidget, Output, settings
from orangewidget import gui
from orangecontrib.text.corpus import Corpus

from elsapy.elsclient import ElsClient
from elsapy.elssearch import ElsSearch

import pandas as pd
import numpy as np

import datetime


class Elsevier(OWBaseWidget):
    name = "Elsevier"
    description = "Downloads elsevier article abstracts using scopus and renders them usable for viewing as a corpus in orange3."
    icon = "icons/elsevier.svg"
    priority = 10

    class Outputs:
        articles = Output("Articles", Corpus)

    want_main_area = False
    resizing_enabled = False

    apiKey = settings.Setting("")
    searchText = settings.Setting("")
    fieldType = settings.Setting("")
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
            ('DOI', 'prism:doi')
        ]

    def __init__(self):
        super().__init__()

        # GUI
        self.apiKeyBox = gui.widgetBox(self.controlArea, "API key")
        gui.lineEdit(self.apiKeyBox, self, 'apiKey', 'api key', valueType=str)

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
        gui.button(self.controlBox, self, 'START', callback=self._send_article)
        gui.button(self.controlBox, self, 'STOP')

        self.info.set_input_summary(self.info.NoInput)

    def _fetch_results(self):
        # generate scopus query
        fieldType = self.fieldTypeItems[self.fieldType]
        searchText = self.searchText
        recordCount = self.recordCount

        startDate = self.startCalendar.textFromDateTime(self.startCalendar.dateTime())
        endDate = self.endCalendar.textFromDateTime(self.endCalendar.dateTime())

        self.startDate = startDate
        self.endDate = endDate

        startYear = startDate[:4]
        endYear = endDate[:4]
        
        # print('field type:', fieldType)
        # print('search text:', searchText)
        # print('start year:', startYear)
        # print('end year:', endYear)

        query = f'{self.fieldTypeCodes[fieldType]}({searchText}) AND PUBYEAR > {startYear} AND PUBYEAR < {endYear}'

        # execute scopus query
        self.client = ElsClient(self.apiKey)
        doc_srch = ElsSearch(query,'scopus')
        doc_srch.execute(self.client, get_all = True)

        results = doc_srch.results_df

        if len(results) > recordCount:
            results = results[:recordCount]

        # check for error
        if 'error' in results.columns:
            self.info.set_output_summary(f"no articles found")
            self.error('error fetching results')
            return pd.DataFrame()

        self.progressBarSet(30)
        return results

    def _extract_data(self):
        """
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
            return pd.DataFrame()

        self.info.set_output_summary(f"{totalCount} articles")

        final_df = results[['dc:title', 'dc:creator', 'prism:coverDate', 'prism:doi']]

        final_df['prism:coverDate'] = final_df['prism:coverDate'].apply(lambda d: d.strftime('%d-%m-%Y'))

        abstractDownloadCount = 0
        progress = 30

        def get_abstract(link):
            nonlocal abstractDownloadCount, progress, self
            scopus_link = link['self']

            rawdata = self.client.exec_request(scopus_link)
            response = rawdata['abstracts-retrieval-response']

            abstract = response['coredata']['dc:description']

            abstractDownloadCount += 1
            progress  = int(progress + 70 * abstractDownloadCount / totalCount)
            self.progressBarSet(progress)
            return abstract

        final_df['abstract'] = results['link'].apply(get_abstract)

        return final_df

    def _dataframe_to_corpus_entries(self, df):
        """
            create corpus entries from dataframe records
        """
        class_values = []
        metadata = np.empty((len(df), len(df.columns)), dtype=object)

        for index, row in df.iterrows():
            fields = []

            for _, field_key in self.metadataCodes:
                fields.append(row[field_key])

            metadata[index] = np.array(fields, dtype=object)[None, :]

        return metadata, class_values

    def _corpus_from_records(self, df):
        meta_values, class_values = self._dataframe_to_corpus_entries(df)

        meta_vars = []

        for field_name, _ in self.metadataCodes:
            if field_name == 'dat':
                time_var = Orange.data.TimeVariable(field_name)
                meta_vars.append(time_var)
            else:
                meta_vars.append(Orange.data.StringVariable.make(field_name))
                if field_name == 'title':
                    meta_vars[-1].attributes['title'] = True

        domain = Orange.data.Domain([], metas = meta_vars)

        return Corpus(domain=domain, metas=meta_values)

    def _send_article(self):
        self.progress = Orange.widgets.gui.ProgressBar(self, 1)
        self.progressBarInit()
        df = self._extract_data()
        corpus = self._corpus_from_records(df)
        self.progressBarFinished()
        self.Outputs.articles.send(corpus)
