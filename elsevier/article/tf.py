from selenium import webdriver
from article import Article
from webdriver_manager.chrome import ChromeDriverManager
import os
import tempfile
import shutil

"""
two ways to watch for selenium file downloads since webdriver does not fire any native events
    1. open chrome://downloads and watch progressbar for completion of download
    2. use filesystem observers like watchdog
"""
from watchdog.observers import Observer

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

        self.observer = Observer()
        self.observer.schedule(self._handle_download, self.dirpath, recursive=False)
        self.observer.start()

    def cleanup(self):
        # remove temporary directory during garbage collection
        shutil.rmtree(self.dirpath)
        self.driver.close()
        self.driver.quit()
        self.observer.stop()
        self.observer.join()

    def _handle_download(self):
        f = open(self._get_filename())
        return self._pdf_to_text(f)

    def _get_filename(self):
        filename = max([os.path.join(self.dirpath, f) for f in os.listdir(self.dirpath)], key=os.path.getctime)
        return filename

    def exec_request(self, doi):
        self.doi = doi
        url = f"https://www.tandfonline.com/doi/pdf/{doi}?download=true"
        self.driver.get(url)


client = TFClient()
t1=client.exec_request("10.1080/09669582.2019.1650054")
t2=client.exec_request("10.1080/16078055.2021.1887995")
t3=client.exec_request("10.1080/09669582.2021.1942478")
client.cleanup()
