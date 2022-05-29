# elsorange
Downloads elsevier article abstracts using scopus and renders them usable for viewing as a corpus in orange3.

## Installation
Install using batch file provided post modification

```bat
    powershell "start cmd -v runAs"

    cd <Orange installation location>\Scripts
    activate

    @echo off
    conda install -c jmgeiger elsapy
    conda install orange3
    conda install orange3-text
    conda install numpy
    conda install pandas
    conda install setuptools

    @echo on
    cd <widget installation location>
    pip install -e .
    pause
```