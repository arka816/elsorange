import time, tempfile, PyPDF2

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
        f.close()
        return text

    def _pdf_to_text(self, f):
        pdfReader = PyPDF2.PdfFileReader(f)
        text = ''

        for i in range(pdfReader.numPages):
            # extract text from page
            text += pdfReader.getPage(i).extractText()
        f.close()
        return text
