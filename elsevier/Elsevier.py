from orangewidget.widget import OWBaseWidget, Output, settings
from orangewidget import gui
from orangecontrib.text.corpus import Corpus

import datetime

import os
import sys

from decouple import config

import logging

LOCAL_FOLDER = os.getenv('LOCALAPPDATA')
CACHE_FOLDER = os.path.join(LOCAL_FOLDER, "elsevier")

if not os.path.exists(CACHE_FOLDER):
    try:
        os.mkdir(CACHE_FOLDER)
    except:
        pass

sys.path.append(os.path.dirname(__file__))
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(os.path.join(CACHE_FOLDER, ".log"))

for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)


logging.basicConfig(
    filename=os.path.join(os.getenv('LOCALAPPDATA'), "elsevier", ".log"),
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='a',
    level=logging.INFO,
    force=True
)

from worker import Worker

from PyQt5.QtCore import QThread



class Elsevier(OWBaseWidget):
    name = "Elsevier"
    description = "Downloads elsevier article abstracts using scopus and renders them usable for viewing as a corpus in orange3."
    icon = "icons/elsevier.svg"
    priority = 10

    class Outputs:
        articles = Output("Articles", Corpus)

    want_main_area = False
    resizing_enabled = True

    scopusApiKey = settings.Setting(config('SCOPUS_API_KEY'))
    springerApiKey = settings.Setting(config('SPRINGER_API_KEY'))
    sciencedirectApiKey = settings.Setting(config('SCIENCEDIRECT_API_KEY'))
    searchText = settings.Setting("")
    fieldType = settings.Setting(0)
    recordCount = settings.Setting(100)
    startDate = settings.Setting('2020-01-01')
    endDate = settings.Setting('2022-01-01')

    fieldTypeItems = (
        'Abstract Title, Abstract, Keyword',
        'Abstract',
        'Keyword',
        'Article Title',
        'DOI',
        'ISSN',
        'All fields'
    )


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

        self.isDownloading = False


    def _start_download(self):
        """
            the handler for the search button

            - extracts data from scopus query result
            - converts extracted data to metadata and class values
            - generates corpus from said metadata and class values
            - signals the corpus to the output strea
        """
        if not self.isDownloading:
            self.isDownloading = True

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

            self.progress = gui.ProgressBar(self, 1)
            self.progressBarInit()
            
            # create thread handler
            self.thread = QThread()

            # create worker
            self.worker = Worker(self.scopusApiKey, self.springerApiKey, self.sciencedirectApiKey, fieldType, searchText, recordCount, startDate, endDate, logging)
            self.worker.moveToThread(self.thread)

            self.worker.message.connect(self._message_from_worker)
            self.worker.error.connect(self._error_from_worker)
            self.worker.progress.connect(self._progress_from_worker)

            self.thread.started.connect(self.worker.run)
            self.worker.finished.connect(self.thread.quit)
            self.worker.finished.connect(self.worker.deleteLater)
            self.thread.finished.connect(self.thread.deleteLater)

            # start thread
            self.thread.start()

            def worker_finished(corpus):
                if type(corpus) == Corpus and len(corpus) > 0:
                    self.corpus = corpus
                    self.progressBarFinished()
                    self.Outputs.articles.send(corpus)
                    self.isDownloading = False
                
            self.worker.finished.connect(worker_finished)
        

    def _message_from_worker(self, message):
        logging.info(message)
        self.info.set_output_summary(message)

    def _error_from_worker(self, error):
        logging.error(error)
        self.error(error)

        self.progressBarFinished()
        logging.info('quitting worker thread')

        self.thread.quit()
        self.isDownloading = False

    def _progress_from_worker(self, progress):
        self.progressBarSet(progress)
